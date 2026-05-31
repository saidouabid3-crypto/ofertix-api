from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

KITCHEN_POSITIVE = {
    'kitchen', 'cookware', 'pan', 'pot', 'knife', 'spoon', 'fork', 'plate', 'cup', 'mug',
    'sink', 'faucet', 'cabinet', 'drawer', 'organizer', 'blender', 'mixer', 'air fryer',
    'oven', 'dish', 'cutting board', 'colander', 'kettle', 'toaster', 'utensil', 'storage jar',
}
KITCHEN_NEGATIVE = {
    'shoe', 'sneaker', 'ring', 'jewelry', 'earring', 'necklace', 'bracelet', 'watch', 'smartwatch',
    'phone', 'iphone', 'samsung', 'dress', 'pants', 'jeans', 'bag', 'makeup', 'wig', 'toy', 'car',
}
CATEGORY_RULES = [
    ('Smart Watches', {'smartwatch', 'smart watch', 'watch band', 'wristband', 'fitness tracker'}, {'kitchen', 'pan', 'pot'}),
    ('Phones', {'iphone', 'samsung', 'phone', 'mobile', 'smartphone', 'case for iphone', 'usb-c'}, {'pan', 'pot'}),
    ('Electronics', {'camera', 'audio', 'speaker', 'headphone', 'earbuds', 'charger', 'usb', 'ssd', 'laptop', 'tablet'}, set()),
    ('Beauty', {'beauty', 'hair', 'makeup', 'cosmetic', 'skin', 'nail', 'perfume'}, {'pan', 'pot'}),
    ('Fashion', {'shirt', 'dress', 'pants', 'jeans', 'jacket', 'coat', 'bag', 'shoe', 'sneaker', 'fashion'}, {'kitchen'}),
    ('Jewelry', {'ring', 'earring', 'necklace', 'bracelet', 'jewelry'}, {'kitchen'}),
    ('Kitchen', KITCHEN_POSITIVE, KITCHEN_NEGATIVE),
    ('Home', {'home', 'house', 'furniture', 'lamp', 'sofa', 'bed', 'bathroom', 'decor', 'storage'}, set()),
    ('Tools', {'tool', 'drill', 'wrench', 'screwdriver', 'hardware', 'welding', 'cutter'}, set()),
    ('Cars', {'car', 'auto', 'vehicle', 'motorcycle', 'bike accessory'}, {'kitchen'}),
    ('Kids', {'kid', 'baby', 'toy', 'children'}, set()),
    ('Fitness', {'fitness', 'gym', 'sport', 'yoga', 'bike', 'running'}, set()),
    ('Gaming', {'gaming', 'console', 'controller', 'keyboard', 'mouse gamer'}, set()),
]
SUPPORTED_COUNTRIES = ['es', 'ma', 'dz', 'fr', 'pt', 'it', 'de', 'uk', 'us', 'ca', 'eg', 'sa', 'ae', 'mx']


def _text(value: Any, default: str = '') -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).replace('€', '').replace('$', '').replace('EUR', '').replace('USD', '').strip()
    if ',' in raw and '.' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        return float(raw)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_number(value, default)))
    except Exception:
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {'true', '1', 'yes', 'si', 'sí'}
    return default


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [x.strip() for x in re.split(r'[,|;]', value) if x.strip()]
    return []


def _short_name(title: str) -> str:
    title = re.sub(r'\s+', ' ', title).strip()
    title = re.sub(r'(?i)\b(wholesale|dropshipping|free shipping|hot sale|new arrival|best price)\b', '', title)
    parts = re.split(r'[,|\-–—]', title)
    name = parts[0].strip() if parts else title
    if len(name) < 10 and len(title) > len(name):
        name = title[:85].rsplit(' ', 1)[0]
    if len(name) > 70:
        name = name[:70].rsplit(' ', 1)[0]
    return name or title[:70]


def classify_category(item: dict[str, Any]) -> tuple[str, float, str]:
    hay = ' '.join([
        _text(item.get('name')),
        _text(item.get('title')),
        _text(item.get('description')),
        _text(item.get('category')),
        _text(item.get('sourceCategory')),
        _text(item.get('storeCategory')),
    ]).lower()
    best = ('General', 0.35, 'fallback')
    for category, positives, negatives in CATEGORY_RULES:
        if any(n in hay for n in negatives):
            continue
        hits = [p for p in positives if p in hay]
        if hits:
            confidence = min(0.98, 0.72 + len(hits) * 0.08)
            if confidence > best[1]:
                best = (category, confidence, f"matched: {', '.join(hits[:4])}")
    return best


def score_product(item: dict[str, Any]) -> tuple[float, float, float, str]:
    price = _number(item.get('newPrice') or item.get('price'))
    old = _number(item.get('oldPrice'))
    discount = _int(item.get('discount'))
    if discount <= 0 and old > price > 0:
        discount = int(round(((old - price) / old) * 100))
    rating = _number(item.get('rating'))
    reviews = _int(item.get('reviewCount') or item.get('reviews'))
    sold = _int(item.get('soldCount') or item.get('sold') or item.get('orders'))
    has_image = bool(_text(item.get('mainImage') or item.get('image')) or _list(item.get('images')))
    deal = 45 + min(discount, 60) * 0.45 + max(rating - 3, 0) * 8 + min(reviews, 2000) / 120 + min(sold, 5000) / 350
    trust = (55 if has_image else 25) + max(rating - 3, 0) * 12 + min(reviews, 1500) / 60
    quality = 50 + (15 if price > 0 else 0) + (20 if has_image else 0)
    deal, trust, quality = [round(max(0, min(99, x)), 2) for x in (deal, trust, quality)]
    if trust < 45 or quality < 45:
        verdict = 'risky'
    elif deal >= 82 and trust >= 65:
        verdict = 'buy_now'
    elif _text(item.get('priceAccuracy'), 'estimated') == 'estimated':
        verdict = 'check_store'
    else:
        verdict = 'safe_deal'
    return deal, trust, quality, verdict


def product_fingerprint(item: dict[str, Any]) -> str:
    raw = '|'.join([
        _text(item.get('store')).lower(),
        re.sub(r'[^a-z0-9]+', ' ', _text(item.get('name') or item.get('title')).lower()).strip(),
        str(round(_number(item.get('newPrice') or item.get('price')), 2)),
    ])
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def normalize_product(item: dict[str, Any], *, fallback_country: str = 'global') -> dict[str, Any]:
    full_title = _text(item.get('fullTitle') or item.get('title') or item.get('name'), 'Product')
    name = _short_name(_text(item.get('name'), full_title))
    image = _text(item.get('mainImage') or item.get('image') or item.get('imageUrl') or item.get('image_url'))
    images = []
    for img in [image, *_list(item.get('images') or item.get('imageUrls') or item.get('gallery'))]:
        if img and img.startswith('http') and img not in images:
            images.append(img)
    category, confidence, reason = classify_category({**item, 'name': name, 'title': full_title})
    price = _number(item.get('newPrice') or item.get('price') or item.get('sale_price'))
    old = _number(item.get('oldPrice') or item.get('old_price') or item.get('original_price'))
    discount = _int(item.get('discount'))
    if discount <= 0 and old > price > 0:
        discount = int(round(((old - price) / old) * 100))
    country = _text(item.get('countryCode') or item.get('country') or fallback_country, 'global').lower()
    available = [x.lower() for x in _list(item.get('availableCountries'))]
    ships = [x.lower() for x in _list(item.get('shipsTo'))]
    if country == 'global' and not available and not ships:
        available = SUPPORTED_COUNTRIES
    deal, trust, quality, verdict = score_product({**item, 'newPrice': price, 'oldPrice': old, 'discount': discount, 'images': images, 'category': category})
    status = _text(item.get('status'), 'active').lower()
    visible = _bool(item.get('visibleToUsers'), True)
    admin_issue = _text(item.get('adminIssue'))
    if not images or price <= 0 or confidence < 0.55:
        status = 'needs_market_review'
        visible = False
        admin_issue = admin_issue or 'quality_gate_failed'
    if category == 'Kitchen':
        hay = f"{name} {full_title} {_text(item.get('description'))}".lower()
        if any(n in hay for n in KITCHEN_NEGATIVE):
            status = 'needs_market_review'
            visible = False
            admin_issue = 'category_kitchen_negative_match'
    normalized = dict(item)
    normalized.update({
        'name': name,
        'fullTitle': full_title,
        'description': _text(item.get('description'), full_title),
        'mainImage': images[0] if images else image,
        'image': images[0] if images else image,
        'images': images,
        'newPrice': price,
        'oldPrice': old,
        'discount': discount,
        'store': _text(item.get('store') or item.get('merchant') or item.get('source'), 'Store'),
        'category': category,
        'categoryGroup': category,
        'categoryConfidence': confidence,
        'categoryReason': reason,
        'countryCode': country,
        'country': country,
        'availableCountries': available,
        'shipsTo': ships,
        'currency': _text(item.get('currency'), 'EUR'),
        'rating': _number(item.get('rating')),
        'reviewCount': _int(item.get('reviewCount') or item.get('reviews')),
        'soldCount': _int(item.get('soldCount') or item.get('sold') or item.get('orders')),
        'dealScore': deal,
        'trustScore': trust,
        'qualityScore': quality,
        'verdict': verdict,
        'priceAccuracy': _text(item.get('priceAccuracy'), 'estimated'),
        'priceSource': _text(item.get('priceSource'), 'feed'),
        'finalPriceInStore': _bool(item.get('finalPriceInStore'), True),
        'visibleToUsers': visible,
        'status': status,
        'adminIssue': admin_issue,
        'fingerprint': _text(item.get('fingerprint')) or product_fingerprint({'store': item.get('store'), 'name': name, 'newPrice': price}),
        'updatedAt': item.get('updatedAt') or datetime.now(timezone.utc).isoformat(),
    })
    return normalized
