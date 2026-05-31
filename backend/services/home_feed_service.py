from __future__ import annotations

import random
from typing import Any

from core.firebase import db
from core.market_config import SUPPORTED_MARKETS, normalize_market
from utils.market_filter import item_available_for_country, normalize_item_market_fields
from utils.product_standard import normalize_product


def _score(item: dict[str, Any]) -> float:
    return float(item.get('dealScore') or 0) + float(item.get('trustScore') or 0) * 0.35 + float(item.get('qualityScore') or 0) * 0.20


def _usable(item: dict[str, Any], market: str) -> bool:
    status = str(item.get('status', 'active')).lower()
    if status not in {'active', 'approved', 'published'}:
        return False
    if item.get('visibleToUsers') is False:
        return False
    if not item.get('image') and not item.get('mainImage'):
        return False
    if float(item.get('newPrice') or item.get('price') or 0) <= 0:
        return False
    if not item_available_for_country(item, market):
        return False
    if str(item.get('categoryGroup') or item.get('category')).lower() == 'kitchen':
        hay = f"{item.get('name','')} {item.get('description','')}".lower()
        negatives = ['shoe', 'sneaker', 'ring', 'jewelry', 'earring', 'necklace', 'watch', 'phone', 'dress', 'pants', 'bag']
        if any(n in hay for n in negatives):
            return False
    return True


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_fp: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get('id') or '')
        fp = str(item.get('fingerprint') or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}").lower()
        if item_id and item_id in seen_ids:
            continue
        if fp and fp in seen_fp:
            continue
        if item_id:
            seen_ids.add(item_id)
        if fp:
            seen_fp.add(fp)
        result.append(item)
    return result


def _take_pool(items: list[dict[str, Any]], used: set[str], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get('id') or item.get('fingerprint') or item.get('name'))
        if key in used:
            continue
        used.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def build_home_feed(country: str = 'es', limit: int = 40) -> dict[str, Any]:
    market = normalize_market(country)
    read_limit = max(240, min(800, limit * 10))
    try:
        docs = db.collection('products').where('visibleToUsers', '==', True).limit(read_limit).stream()
    except Exception:
        docs = db.collection('products').limit(read_limit).stream()

    products: list[dict[str, Any]] = []
    for doc in docs:
        raw = doc.to_dict() or {}
        raw['id'] = doc.id
        item = normalize_product(normalize_item_market_fields(raw, fallback_country=market), fallback_country=market)
        if _usable(item, market):
            products.append(item)

    products = _dedupe(products)
    products.sort(key=_score, reverse=True)
    rng = random.Random()
    fresh = sorted(products, key=lambda x: str(x.get('updatedAt') or ''), reverse=True)
    top_rated = sorted(products, key=lambda x: (float(x.get('rating') or 0), int(x.get('reviewCount') or 0)), reverse=True)
    hot = [p for p in products if int(p.get('discount') or 0) >= 25 or float(p.get('dealScore') or 0) >= 70]
    online = [p for p in products if p.get('isOnline') is not False]
    surprise = products[:]
    rng.shuffle(surprise)

    used: set[str] = set()
    sections = {
        'heroDeals': _take_pool(hot or products, used, 6),
        'hotDeals': _take_pool(hot or products, used, 12),
        'globalOnline': _take_pool(online or products, used, 12),
        'topRated': _take_pool(top_rated, used, 12),
        'recentlyAdded': _take_pool(fresh, used, 12),
        'surpriseDeals': _take_pool(surprise, used, 12),
    }

    categories: dict[str, int] = {}
    stores: dict[str, int] = {}
    for p in products:
        cat = str(p.get('categoryGroup') or p.get('category') or 'General')
        if cat.lower() == 'general' or float(p.get('categoryConfidence') or 0) < 0.55:
            continue
        categories[cat] = categories.get(cat, 0) + 1
        store = str(p.get('store') or '').strip()
        if store:
            stores[store] = stores.get(store, 0) + 1

    return {
        'country': market,
        'currency': SUPPORTED_MARKETS[market]['currency'],
        'count': len(products),
        'sections': sections,
        'categories': [{'name': k, 'count': v} for k, v in sorted(categories.items(), key=lambda x: x[1], reverse=True)[:20]],
        'stores': [{'name': k, 'count': v} for k, v in sorted(stores.items(), key=lambda x: x[1], reverse=True)[:20]],
    }
