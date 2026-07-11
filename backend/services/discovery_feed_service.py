from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from google.api_core.exceptions import FailedPrecondition

from core.firebase import db
from core.market_config import SUPPORTED_MARKETS, normalize_market
from services.catalog_edge_cache import safe_stream
from services.public_product_service import is_usable_public_product, prepare_public_product

_QUARANTINED = {'quarantined', 'blocked', 'rejected', 'hidden'}
_URL_TRACKING_PARAMS = {
    'affid',
    'aff_id',
    'affiliate_id',
    'clickid',
    'fbclid',
    'gclid',
    'irclickid',
    'msclkid',
    'ref',
    'subid',
    'tag',
    'utm_campaign',
    'utm_content',
    'utm_medium',
    'utm_source',
    'utm_term',
}


def _number(val: Any, default: float = 0.0) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        return default
    raw = re.sub(r'[^0-9.\-]', '', str(val).strip())
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _clean_identity_value(value: Any) -> str:
    return str(value or '').strip().lower()


def _canonical_url(value: Any) -> str:
    raw = _clean_identity_value(value)
    if not raw:
        return ''
    try:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.netloc:
            return raw.rstrip('/')
        query = urlencode(
            [
                (key, val)
                for key, val in parse_qsl(parts.query, keep_blank_values=True)
                if key.lower() not in _URL_TRACKING_PARAMS
            ],
            doseq=True,
        )
        return urlunsplit(
            (
                parts.scheme.lower(),
                parts.netloc.lower(),
                parts.path.rstrip('/'),
                query,
                '',
            )
        )
    except Exception:
        return raw.rstrip('/')


def _product_identity_keys(item: dict[str, Any]) -> list[str]:
    """
    Stable product identity for Home-screen dedupe.

    Prefer catalog ids, then fall back to offer/product URLs and SKU-like fields.
    Fingerprint is last for older catalog rows without complete ids or links.
    """
    keys: list[str] = []

    for field in ('id', 'productId', 'product_id'):
        value = _clean_identity_value(item.get(field))
        if value:
            keys.append(f'id:{value}')
            break

    for field in (
        'affiliateUrl',
        'affiliate_url',
        'productUrl',
        'product_url',
        'originalUrl',
        'url',
        'link',
    ):
        value = _canonical_url(item.get(field))
        if value:
            keys.append(f'url:{value}')

    for field in ('sku', 'SKU', 'itemSku', 'itemSKU', 'externalId', 'external_id', 'offerId', 'offer_id'):
        value = _clean_identity_value(item.get(field))
        if value:
            keys.append(f'sku:{value}')

    fingerprint = _clean_identity_value(
        item.get('fingerprint')
        or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
    )
    if fingerprint and fingerprint != 'none|none|none':
        keys.append(f'fp:{fingerprint}')

    return list(dict.fromkeys(keys))


def _has_seen_product(item: dict[str, Any], used: set[str]) -> bool:
    keys = _product_identity_keys(item)
    return bool(keys and any(key in used for key in keys))


def _mark_product_used(item: dict[str, Any], used: set[str]) -> None:
    keys = _product_identity_keys(item)
    if keys:
        used.update(keys)


def rotation_boost(product_id: str, seed: str) -> float:
    """Deterministic 0–8 daily boost — same product+seed always returns same value."""
    digest = hashlib.md5(f"{seed}:{product_id}".encode()).hexdigest()
    return float(int(digest[:2], 16) % 9)  # 0..8


def _freshness_hours(item: dict[str, Any]) -> float | None:
    """Return how many hours ago the product was last updated/synced, or None."""
    for field in ('updatedAt', 'lastSyncedAt', 'importedAt'):
        raw = item.get(field)
        if not raw:
            continue
        try:
            if isinstance(raw, datetime):
                dt = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
            else:
                ts = str(raw)[:26]
                for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
                    try:
                        dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except Exception:
            continue
    return None


def compute_discovery_score(
    item: dict[str, Any],
    *,
    day_seed: str,
    seen_ids: set[str],
) -> float:
    """
    Compute discovery score 0–100 for a product. Pure function — no Firestore.

    Uses qualityScore as the base (not publicRankScore) to leave headroom
    for discovery-specific bonuses and penalties to have visible effect.
    """
    base = _number(item.get('qualityScore') or item.get('catalogRankScore'), 50)
    score = max(0.0, min(100.0, base))

    trust = str(item.get('trustStatus') or '').lower()
    flags = {str(f).lower() for f in (item.get('qualityFlags') or [])}
    discount = _number(item.get('discount'))
    quality = _number(item.get('qualityScore'))
    images = item.get('images') or []
    link = str(item.get('affiliateUrl') or item.get('productUrl') or '').strip()
    item_id = str(item.get('id') or '')

    # --- Bonuses ---
    if trust in ('trusted', 'ok'):
        score += 20
    if discount >= 50:
        score += 15
    if item.get('isHot') or item.get('featured'):
        score += 10
    if quality >= 80:
        score += 10
    if link.startswith('http'):
        score += 8
    hours = _freshness_hours(item)
    if hours is not None and hours <= 48:
        score += 8

    # --- Penalties ---
    if flags & {'missing_price', 'suspicious_price', 'missing_currency'}:
        score -= 25
    if flags & {'missing_link', 'invalid_link'}:
        score -= 20
    if isinstance(images, list) and len(images) <= 1:
        score -= 15
    if 'duplicate_candidate' in flags:
        score -= 15
    if item_id and item_id in seen_ids:
        score -= 40
    if trust in _QUARANTINED:
        score -= 30

    # --- Deterministic daily rotation boost (+0..+8) ---
    score += rotation_boost(item_id or str(item.get('fingerprint') or ''), day_seed)

    return round(max(0.0, min(100.0, score)), 2)


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        if _has_seen_product(item, used):
            continue
        _mark_product_used(item, used)
        result.append(item)
    return result


def _apply_diversity(
    ranked: list[dict[str, Any]],
    limit: int,
    *,
    max_store_first12: int = 2,
    max_cat_first12: int = 3,
) -> list[dict[str, Any]]:
    """
    Two-bucket diversity placement:
    - slots_0_11: first 12 output positions, store/category capped.
    - slots_12_plus: positions 12 onward, unconstrained.
    - deferred: products that didn't fit in first 12 go here, then to slots_12_plus.

    When alternatives exist the first 12 positions stay diverse.
    If the catalog is too small to satisfy diversity (only one store/category),
    deferred products fill positions 12+ and the fallback loop adds the rest,
    so the feed is never artificially empty.
    """
    store_counts: dict[str, int] = {}
    cat_counts: dict[str, int] = {}
    slots_0_11: list[dict[str, Any]] = []
    slots_12_plus: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for item in ranked:
        store = str(item.get('store') or '').strip()
        cat = str(item.get('categoryGroup') or item.get('category') or '').strip()

        if len(slots_0_11) < 12:
            over_store = bool(store and store_counts.get(store, 0) >= max_store_first12)
            over_cat = bool(cat and cat_counts.get(cat, 0) >= max_cat_first12)
            if over_store or over_cat:
                deferred.append(item)
                continue
            slots_0_11.append(item)
            if store:
                store_counts[store] = store_counts.get(store, 0) + 1
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        else:
            # Position 12+ — no diversity constraint
            slots_12_plus.append(item)
            if len(slots_0_11) + len(slots_12_plus) >= limit:
                break

    # Place deferred into positions 12+ (after the diverse first 12)
    for item in deferred:
        if len(slots_0_11) + len(slots_12_plus) >= limit:
            break
        slots_12_plus.append(item)

    result = slots_0_11 + slots_12_plus

    # Fallback: small or single-store/category catalog — add remaining ranked products
    if len(result) < min(limit, len(ranked)):
        used_keys = {str(p.get('id') or p.get('fingerprint') or p.get('name')) for p in result}
        for item in ranked:
            if len(result) >= limit:
                break
            key = str(item.get('id') or item.get('fingerprint') or item.get('name'))
            if key not in used_keys:
                result.append(item)
                used_keys.add(key)

    return result


def _take_pool(
    items: list[dict[str, Any]],
    used: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Pick up to `limit` items not already in `used`, mark them used."""
    out: list[dict[str, Any]] = []
    for item in items:
        if _has_seen_product(item, used):
            continue
        _mark_product_used(item, used)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _take_from_pools(
    pools: list[list[dict[str, Any]]],
    used: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Fill a section from preferred pools, falling back to broader real products."""
    out: list[dict[str, Any]] = []
    for pool in pools:
        if len(out) >= limit:
            break
        out.extend(_take_pool(pool, used, limit - len(out)))
    return out


def _fetch_usable_products(market: str, read_limit: int) -> list[dict[str, Any]]:
    """
    Fetch and normalize products from Firestore using the same public eligibility
    pipeline as /products.

    Read governor: read_limit is capped by the caller (build_discovery_feed).
    safe_stream enforces the limit and propagates ResourceExhausted so the
    cache layer can serve stale data instead of returning an empty feed.
    """
    try:
        docs = safe_stream(
            db.collection('products').where('visibleToUsers', '==', True),
            limit=read_limit,
            context='discovery_feed',
            route='/home-feed',
            collection='products',
        )
    except FailedPrecondition:
        docs = safe_stream(
            db.collection('products'),
            limit=read_limit,
            context='discovery_feed_fallback',
            route='/home-feed',
            collection='products',
        )

    products: list[dict[str, Any]] = []
    for doc in docs:
        raw = doc.to_dict() or {}
        raw['id'] = doc.id

        # Use the same normalization + eligibility path as /products
        item = prepare_public_product(raw, market)
        if not is_usable_public_product(item, market):
            continue

        # Discovery-layer safety: never show quarantined/rejected/hidden products
        # regardless of publicFilteringEnabled setting.
        status = str(item.get('status') or '').lower()
        trust = str(item.get('trustStatus') or '').lower()
        if status in _QUARANTINED or trust in _QUARANTINED:
            continue
        if item.get('active') is False or item.get('isActive') is False:
            continue

        products.append(item)

    return _dedupe(products)


def build_discovery_feed(
    *,
    country: str = 'es',
    limit: int = 40,
    day_seed: str,
    variant: str = 'A',
    seen_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build the living discovery feed.

    Cache key must include day_seed + variant + country + limit but NOT raw seen_ids.
    seen_ids are used for scoring (demote already-viewed products) when loading fresh.
    """
    market = normalize_market(country)
    seen_set: set[str] = set((seen_ids or [])[:50])
    # Read governor: was max(300, min(900, limit * 12)) = 480 reads for limit=40.
    # Reduced to min(200, max(60, limit * 3)) = 120 reads for limit=40 (4x reduction).
    read_limit = min(200, max(60, limit * 3))

    all_products = _fetch_usable_products(market, read_limit)

    if not all_products:
        return {
            'country': market,
            'currency': SUPPORTED_MARKETS[market]['currency'],
            'count': 0,
            'seedDay': day_seed,
            'variant': variant,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'sections': {
                'heroDeals': [], 'hotDeals': [], 'globalOnline': [],
                'topRated': [], 'recentlyAdded': [], 'surpriseDeals': [],
                'verifiedDeals': [], 'bestDiscountToday': [], 'freshArrivals': [],
                'trendingNow': [], 'notSeenRecently': [], 'forYouToday': [],
            },
            'products': [],
            'categories': [],
            'stores': [],
        }

    # Score and rank every product.
    # Combine day_seed + variant so different variants produce different orderings.
    rotation_seed = f"{day_seed}:{variant}"
    scored: list[tuple[float, dict[str, Any]]] = [
        (compute_discovery_score(p, day_seed=rotation_seed, seen_ids=seen_set), p)
        for p in all_products
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored]

    # Main discovery-ordered feed with store/category diversity
    diverse = _apply_diversity(ranked, limit=limit)

    # --- Specialty sub-lists for named sections ---
    trust_ok = [p for p in ranked if str(p.get('trustStatus') or '').lower() in ('trusted', 'ok')]

    high_discount = sorted(
        [p for p in ranked if _number(p.get('discount')) >= 30],
        key=lambda p: _number(p.get('discount')),
        reverse=True,
    )

    fresh = sorted(
        [p for p in ranked if (_freshness_hours(p) or 9999) <= 72],
        key=lambda p: _freshness_hours(p) or 9999,
    )

    hot_or_trending = [
        p for p in ranked
        if p.get('isHot') or p.get('isTrending') or p.get('featured')
    ]

    not_seen = [p for p in ranked if str(p.get('id') or '') not in seen_set]

    surprise_seed = f"{day_seed}:surprise"
    surprise_ranked = sorted(
        ranked,
        key=lambda p: rotation_boost(str(p.get('id') or ''), surprise_seed),
        reverse=True,
    )

    top_rated = sorted(
        ranked,
        key=lambda p: (float(p.get('rating') or 0), int(p.get('reviewCount') or 0)),
        reverse=True,
    )

    online = [p for p in diverse if p.get('isOnline') is not False]

    # Every Home section shares `used` to avoid cross-section repeats.
    used: set[str] = set()

    sections: dict[str, Any] = {
        # --- Legacy sections (keys unchanged — existing Flutter HomeFeed parses these) ---
        'heroDeals': _take_from_pools([diverse[:6], diverse, ranked], used, 6),
        'hotDeals': _take_from_pools([high_discount, diverse, ranked], used, 12),
        'globalOnline': _take_from_pools([online, diverse, ranked], used, 12),
        'topRated': _take_from_pools([top_rated, diverse, ranked], used, 12),
        'recentlyAdded': _take_from_pools([fresh, diverse, ranked], used, 12),
        'surpriseDeals': _take_from_pools([surprise_ranked, diverse, ranked], used, 12),
        # --- New discovery sections ---
        'verifiedDeals': _take_from_pools([trust_ok, diverse, ranked], used, 8),
        'bestDiscountToday': _take_from_pools([high_discount, diverse, ranked], used, 8),
        'freshArrivals': _take_from_pools([fresh, diverse, ranked], used, 8),
        'trendingNow': _take_from_pools([hot_or_trending, diverse, ranked], used, 8),
        'notSeenRecently': _take_from_pools([not_seen, diverse, ranked], used, 10),
        # If previous sections exhaust all unique products, this remains empty.
        'forYouToday': _take_from_pools([diverse, ranked], used, 12),
    }

    categories: dict[str, int] = {}
    stores: dict[str, int] = {}
    for p in all_products:
        cat = str(p.get('categoryGroup') or p.get('category') or 'General')
        if cat.lower() == 'general' or _number(p.get('categoryConfidence')) < 0.55:
            continue
        categories[cat] = categories.get(cat, 0) + 1
        store = str(p.get('store') or '').strip()
        if store:
            stores[store] = stores.get(store, 0) + 1

    return {
        'country': market,
        'currency': SUPPORTED_MARKETS[market]['currency'],
        'count': len(all_products),
        'seedDay': day_seed,
        'variant': variant,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'sections': sections,
        'products': diverse,  # flat discovery-ordered fallback for old clients
        'categories': [
            {'name': k, 'count': v}
            for k, v in sorted(categories.items(), key=lambda x: x[1], reverse=True)[:20]
        ],
        'stores': [
            {'name': k, 'count': v}
            for k, v in sorted(stores.items(), key=lambda x: x[1], reverse=True)[:20]
        ],
    }
