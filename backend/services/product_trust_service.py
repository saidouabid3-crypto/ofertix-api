from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ─── field name maps ──────────────────────────────────────────────────────────

_NAME_FIELDS = ['name', 'title', 'productName', 'product_name', 'fullTitle']
_PRICE_FIELDS = ['price', 'currentPrice', 'current_price', 'newPrice', 'new_price', 'salePrice', 'sale_price']
_OLD_PRICE_FIELDS = ['oldPrice', 'old_price', 'originalPrice', 'original_price', 'compareAtPrice', 'compare_at_price']
_CURRENCY_FIELDS = ['currency', 'currencyCode', 'currency_code']
_COUNTRY_FIELDS = ['countryCode', 'country', 'country_code', 'availableCountries', 'available_countries']
_STORE_FIELDS = ['store', 'storeName', 'store_name', 'merchant', 'merchantName', 'source']
_CATEGORY_FIELDS = ['category', 'categoryId', 'category_id', 'department']
_IMAGE_FIELDS = [
    'image', 'imageUrl', 'image_url', 'mainImage', 'thumbnail',
    'images', 'imageUrls', 'image_urls',
    'gallery', 'galleryImages', 'gallery_images',
    'productImages', 'product_images',
    'media', 'photos', 'pictures',
]
_LINK_AFFILIATE = ['affiliateUrl', 'affiliate_url', 'affiliateURL']
_LINK_PRODUCT = ['productUrl', 'product_url', 'productURL']
_LINK_OTHER = ['sourceUrl', 'source_url', 'originalUrl', 'original_url', 'storeUrl', 'store_url', 'link', 'url']

# ─── score penalties ──────────────────────────────────────────────────────────

_PENALTIES: Dict[str, int] = {
    'missing_image': 25,
    'single_image_only': 5,
    'duplicate_images': 5,
    'missing_link': 25,
    'invalid_link': 20,
    'missing_price': 20,
    'suspicious_price': 15,
    'missing_currency': 8,
    'missing_country': 5,
    'weak_description': 8,
    'missing_store': 5,
    'unknown_category': 5,
    'duplicate_candidate': 15,
}

_CRITICAL_FLAGS = {'missing_link', 'missing_image', 'missing_price', 'invalid_link'}
_IGNORED_COUNTRY_VALUES = {'global', 'unknown', 'null', ''}
_IGNORED_CATEGORY_VALUES = {'general', 'other', 'unknown', ''}
_INVALID_CURRENCY_VALUES = {'global', 'unknown', 'null', 'none', 'n/a', 'na', '', 'undefined', 'mixed', 'other'}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _first_str(product: dict, fields: List[str]) -> str:
    for f in fields:
        val = product.get(f)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ''


def _parse_price(value: Any) -> float:
    """Returns parsed price or -1.0 if unparseable."""
    try:
        raw = str(value or '').replace('€', '').replace('$', '').replace('£', '').replace(',', '.').strip()
        return float(raw)
    except Exception:
        return -1.0


def _is_valid_http_url(url: str) -> bool:
    if not url:
        return False
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        return False
    return len(url) > 10


def _clean_currency(currency: str) -> str:
    """Return '' if currency value is not a real currency identifier."""
    if not currency:
        return ''
    if currency.lower().strip() in _INVALID_CURRENCY_VALUES:
        return ''
    return currency.strip()


# ─── media quality ────────────────────────────────────────────────────────────

def _collect_image_urls(product: dict) -> List[str]:
    seen: set = set()
    result: List[str] = []

    def _add(url: Any) -> None:
        if not isinstance(url, str):
            return
        url = url.strip()
        if not url or not url.startswith(('http://', 'https://')):
            return
        if url not in seen:
            seen.add(url)
            result.append(url)

    # Main image first to keep it at index 0
    for f in ['image', 'imageUrl', 'image_url', 'mainImage', 'thumbnail']:
        val = product.get(f)
        if val and isinstance(val, str):
            _add(val)
        if result:
            break

    # Then all image/gallery fields
    for f in _IMAGE_FIELDS:
        val = product.get(f)
        if val is None:
            continue
        if isinstance(val, str):
            _add(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    _add(item)
                elif isinstance(item, dict):
                    for k in ('url', 'src', 'href', 'image'):
                        v = item.get(k)
                        if v:
                            _add(v)
                            break

    return result


def analyze_media_quality(product: dict) -> Dict[str, Any]:
    all_urls = _collect_image_urls(product)

    seen: set = set()
    unique: List[str] = []
    dup_count = 0
    for url in all_urls:
        if url in seen:
            dup_count += 1
        else:
            seen.add(url)
            unique.append(url)

    valid_count = len(unique)
    return {
        'mainImage': unique[0] if unique else None,
        'gallery': unique,
        'validImageCount': valid_count,
        'duplicateImageCount': dup_count,
        'hasMultipleImages': valid_count >= 2,
    }


# ─── link health ──────────────────────────────────────────────────────────────

def analyze_link_health(product: dict) -> Dict[str, Any]:
    affiliate = _first_str(product, _LINK_AFFILIATE)
    product_url = _first_str(product, _LINK_PRODUCT)
    other = _first_str(product, _LINK_OTHER)
    primary = affiliate or product_url or other

    return {
        'hasAffiliateUrl': bool(affiliate),
        'hasProductUrl': bool(product_url),
        'primaryUrl': primary or None,
        'isValidHttpUrl': _is_valid_http_url(primary),
    }


# ─── price confidence ─────────────────────────────────────────────────────────

def analyze_price_confidence(product: dict) -> str:
    price_raw = None
    for f in _PRICE_FIELDS:
        val = product.get(f)
        if val is not None:
            price_raw = val
            break

    price = _parse_price(price_raw)
    # price <= 0 is always missing — 0 is not a valid price
    if price <= 0:
        return 'missing'

    old_price_raw = None
    for f in _OLD_PRICE_FIELDS:
        val = product.get(f)
        if val is not None:
            old_price_raw = val
            break

    if old_price_raw is not None:
        old_price = _parse_price(old_price_raw)
        if old_price > 0 and old_price < price:
            return 'needs_review'
        if old_price > 0:
            discount = (old_price - price) / old_price * 100
            if discount > 95:
                return 'needs_review'

    # Clean invalid currency values like 'global', 'unknown', etc.
    currency = _clean_currency(_first_str(product, _CURRENCY_FIELDS))
    country = _first_str(product, _COUNTRY_FIELDS)
    if country.lower() in _IGNORED_COUNTRY_VALUES:
        country = ''
    store = _first_str(product, _STORE_FIELDS)

    if currency and (country or store):
        return 'confirmed'
    if currency or country or store:
        return 'approximate'
    return 'needs_review'


# ─── product normalization ────────────────────────────────────────────────────

def normalize_product(product: dict) -> Dict[str, Any]:
    price_raw = None
    for f in _PRICE_FIELDS:
        if product.get(f) is not None:
            price_raw = product.get(f)
            break
    price = _parse_price(price_raw)

    old_price_raw = None
    for f in _OLD_PRICE_FIELDS:
        if product.get(f) is not None:
            old_price_raw = product.get(f)
            break
    old_price = _parse_price(old_price_raw) if old_price_raw is not None else None

    link = analyze_link_health(product)
    media = analyze_media_quality(product)

    return {
        'normalizedName': _first_str(product, _NAME_FIELDS),
        'normalizedStore': _first_str(product, _STORE_FIELDS),
        'normalizedCategory': _first_str(product, _CATEGORY_FIELDS),
        'normalizedCurrency': _first_str(product, _CURRENCY_FIELDS),
        'normalizedCountry': _first_str(product, _COUNTRY_FIELDS),
        'normalizedPrice': price if price >= 0 else None,
        'normalizedOldPrice': old_price if (old_price is not None and old_price >= 0) else None,
        'primaryUrl': link['primaryUrl'],
        'mainImage': media['mainImage'],
        'gallery': media['gallery'],
    }


# ─── quality flags ────────────────────────────────────────────────────────────

def compute_quality_flags(
    product: dict,
    media: Dict[str, Any],
    link: Dict[str, Any],
    price_confidence: str,
    normalized: Dict[str, Any],
) -> List[str]:
    flags: List[str] = []

    # Image
    if media['validImageCount'] == 0:
        flags.append('missing_image')
        flags.append('no_gallery')
    elif media['validImageCount'] == 1:
        flags.append('single_image_only')
    if media['duplicateImageCount'] > 0:
        flags.append('duplicate_images')

    # Link
    if not link['primaryUrl']:
        flags.append('missing_link')
    elif not link['isValidHttpUrl']:
        flags.append('invalid_link')

    # Price
    if price_confidence == 'missing':
        flags.append('missing_price')
    elif price_confidence == 'needs_review':
        flags.append('suspicious_price')

    # Currency — also reject known invalid values like 'global'
    raw_currency = _clean_currency(normalized.get('normalizedCurrency') or '')
    if not raw_currency:
        flags.append('missing_currency')

    # Country
    country = (normalized.get('normalizedCountry') or '').lower()
    if country in _IGNORED_COUNTRY_VALUES:
        flags.append('missing_country')

    # Weak description
    desc = str(product.get('description') or product.get('shortDescription') or '').strip()
    name = normalized.get('normalizedName', '')
    if len(desc) < 10 and len(name) < 5:
        flags.append('weak_description')

    # Store
    if not normalized.get('normalizedStore'):
        flags.append('missing_store')

    # Category
    cat = (normalized.get('normalizedCategory') or '').lower()
    if cat in _IGNORED_CATEGORY_VALUES:
        flags.append('unknown_category')

    return flags


# ─── quality score ────────────────────────────────────────────────────────────

def compute_quality_score(flags: List[str]) -> int:
    score = 100
    for flag in flags:
        score -= _PENALTIES.get(flag, 0)
    return max(0, min(100, score))


# ─── trust status ─────────────────────────────────────────────────────────────

def determine_trust_status(score: int, flags: List[str], existing_status: Optional[str] = None) -> str:
    if existing_status in {'hidden', 'rejected'}:
        return 'hidden'

    flag_set = set(flags)
    critical_combos = [
        {'missing_image', 'missing_link'},
        {'missing_link', 'missing_price'},
        {'missing_image', 'missing_price'},
    ]
    is_critical_combo = any(combo.issubset(flag_set) for combo in critical_combos)
    if score < 35 or is_critical_combo:
        return 'quarantined'

    # suspicious_price also blocks trusted — a product with unknown/zero price cannot be trusted
    trust_blocking = _CRITICAL_FLAGS | {'suspicious_price', 'missing_currency'}
    blocking_present = flag_set & trust_blocking
    if score >= 85 and not blocking_present:
        return 'trusted'
    if score >= 65:
        return 'ok'
    return 'needs_review'


# ─── duplicate fingerprint ────────────────────────────────────────────────────

def product_fingerprint(product: dict) -> str:
    name = _first_str(product, _NAME_FIELDS).lower()
    name_clean = re.sub(r'[^a-z0-9]', '', name)[:50]
    store = _first_str(product, _STORE_FIELDS).lower()

    price_raw = None
    for f in _PRICE_FIELDS:
        if product.get(f) is not None:
            price_raw = product.get(f)
            break
    price = _parse_price(price_raw)
    price_str = f'{price:.2f}' if price >= 0 else ''

    link = analyze_link_health(product)
    primary_url = link.get('primaryUrl') or ''
    url_part = re.sub(r'https?://', '', primary_url).split('?')[0][:80]

    media = analyze_media_quality(product)
    main_image = media.get('mainImage') or ''

    raw = f'{name_clean}|{store}|{price_str}|{url_part}|{main_image}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


# ─── duplicate grouping ───────────────────────────────────────────────────────

_CANDIDATE_THRESHOLD = 60

_DUPLICATE_REASONS = {
    'same_affiliate_url': 60,
    'same_product_url': 60,
    'same_primary_url': 60,
    'same_main_image': 30,
    'same_title_store_price': 30,
    'same_title_similar_price': 15,
    'same_price': 10,
    'same_category': 5,
}


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _url_key(url: str) -> str:
    url = re.sub(r'https?://', '', url).split('?')[0].split('#')[0].rstrip('/')
    return url.lower()[:120]


def _get_main_image_url(product: dict) -> str:
    for f in ['image', 'imageUrl', 'image_url', 'mainImage', 'thumbnail']:
        val = product.get(f)
        if val and isinstance(val, str) and val.startswith('http'):
            return val.strip()
    return ''


def compute_duplicate_score(p1: dict, p2: dict) -> tuple:
    """Returns (score: int, reasons: list[str]) for two products."""
    score = 0
    reasons: List[str] = []

    # Affiliate URL exact match
    aff1 = _first_str(p1, _LINK_AFFILIATE)
    aff2 = _first_str(p2, _LINK_AFFILIATE)
    if aff1 and aff1 == aff2:
        score += 60
        reasons.append('same_affiliate_url')

    # Product URL exact match
    pu1 = _first_str(p1, _LINK_PRODUCT)
    pu2 = _first_str(p2, _LINK_PRODUCT)
    if pu1 and pu1 == pu2 and 'same_affiliate_url' not in reasons:
        score += 60
        reasons.append('same_product_url')

    # Primary URL key (host+path normalized)
    if 'same_affiliate_url' not in reasons and 'same_product_url' not in reasons:
        pr1 = _first_str(p1, _LINK_AFFILIATE + _LINK_PRODUCT + _LINK_OTHER)
        pr2 = _first_str(p2, _LINK_AFFILIATE + _LINK_PRODUCT + _LINK_OTHER)
        if pr1 and pr2 and _url_key(pr1) == _url_key(pr2):
            score += 60
            reasons.append('same_primary_url')

    # Main image URL match
    img1 = _get_main_image_url(p1)
    img2 = _get_main_image_url(p2)
    if img1 and img1 == img2:
        score += 30
        reasons.append('same_main_image')

    # Normalized title + store match
    t1 = _normalize_text(_first_str(p1, _NAME_FIELDS))[:60]
    t2 = _normalize_text(_first_str(p2, _NAME_FIELDS))[:60]
    s1 = _first_str(p1, _STORE_FIELDS).lower().strip()
    s2 = _first_str(p2, _STORE_FIELDS).lower().strip()
    if t1 and len(t1) >= 6 and t1 == t2:
        if s1 and s1 == s2:
            score += 30
            reasons.append('same_title_store_price')

    # Same price
    pr1_raw = next((p1.get(f) for f in _PRICE_FIELDS if p1.get(f) is not None), None)
    pr2_raw = next((p2.get(f) for f in _PRICE_FIELDS if p2.get(f) is not None), None)
    px1 = _parse_price(pr1_raw)
    px2 = _parse_price(pr2_raw)
    if px1 > 0 and px2 > 0 and abs(px1 - px2) < 0.01:
        score += 10

    # Same category
    cat1 = _first_str(p1, _CATEGORY_FIELDS).lower()
    cat2 = _first_str(p2, _CATEGORY_FIELDS).lower()
    if cat1 and cat1 == cat2:
        score += 5

    return min(score, 100), reasons


def group_duplicate_candidates(products: List[dict]) -> List[dict]:
    """
    Group products into duplicate candidate groups using bucket matching + union-find.
    Returns list of group dicts: {groupId, highestScore, reasonSummary, duplicateReasons, products}.
    """
    from collections import defaultdict

    product_by_id: Dict[str, dict] = {}
    for p in products:
        pid = str(p.get('id') or '')
        if pid:
            p['id'] = pid
            product_by_id[pid] = p

    if len(product_by_id) < 2:
        return []

    # Build signal buckets (pid → bucket keys, bucket key → list of pids)
    url_bucket: Dict[str, List[str]] = defaultdict(list)
    img_bucket: Dict[str, List[str]] = defaultdict(list)
    title_bucket: Dict[str, List[str]] = defaultdict(list)

    for pid, p in product_by_id.items():
        # URL bucket: prefer affiliate, then product URL
        for fields in [_LINK_AFFILIATE, _LINK_PRODUCT]:
            url = _first_str(p, fields)
            if url:
                key = _url_key(url)
                if key and len(key) > 8:
                    url_bucket[key].append(pid)
                    break

        # Image bucket
        img = _get_main_image_url(p)
        if img:
            img_bucket[img].append(pid)

        # Title+store bucket
        t = _normalize_text(_first_str(p, _NAME_FIELDS))[:50]
        s = _first_str(p, _STORE_FIELDS).lower().strip()
        if t and len(t) >= 6 and s:
            title_bucket[f'{t}|{s}'].append(pid)

    # Union-Find
    parent: Dict[str, str] = {pid: pid for pid in product_by_id}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for bucket in (url_bucket, img_bucket, title_bucket):
        for pids in bucket.values():
            if len(pids) >= 2:
                for i in range(len(pids)):
                    for j in range(i + 1, len(pids)):
                        _union(pids[i], pids[j])

    # Collect groups
    groups_by_root: Dict[str, List[str]] = defaultdict(list)
    for pid in product_by_id:
        groups_by_root[_find(pid)].append(pid)

    result: List[dict] = []
    for root, pids in groups_by_root.items():
        if len(pids) < 2:
            continue
        # Score the group (check up to 5 pairs to keep it fast)
        max_score = 0
        all_reasons: set = set()
        pairs_checked = 0
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                if pairs_checked >= 10:
                    break
                sc, rs = compute_duplicate_score(product_by_id[pids[i]], product_by_id[pids[j]])
                max_score = max(max_score, sc)
                all_reasons.update(rs)
                pairs_checked += 1

        if max_score < _CANDIDATE_THRESHOLD:
            continue

        group_id = hashlib.md5('|'.join(sorted(pids)).encode()).hexdigest()[:12]
        result.append({
            'groupId': group_id,
            'highestScore': max_score,
            'reasonSummary': ', '.join(sorted(all_reasons)),
            'duplicateReasons': sorted(all_reasons),
            'products': [product_by_id[pid] for pid in pids],
        })

    return result


# ─── main entry point ─────────────────────────────────────────────────────────

def build_quality_update(product: dict) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    media = analyze_media_quality(product)
    link = analyze_link_health(product)
    price_confidence = analyze_price_confidence(product)
    normalized = normalize_product(product)
    flags = compute_quality_flags(product, media, link, price_confidence, normalized)
    score = compute_quality_score(flags)
    trust_status = determine_trust_status(score, flags, product.get('status'))

    return {
        'qualityScore': score,
        'trustStatus': trust_status,
        'qualityFlags': flags,
        'mediaQuality': media,
        'linkHealth': link,
        'priceConfidence': price_confidence,
        'qualityUpdatedAt': now,
        'normalizedAt': now,
        'normalizedName': normalized['normalizedName'],
        'normalizedStore': normalized['normalizedStore'],
        'normalizedCategory': normalized['normalizedCategory'],
        'normalizedCurrency': normalized['normalizedCurrency'],
        'normalizedCountry': normalized['normalizedCountry'],
    }
