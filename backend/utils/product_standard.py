from __future__ import annotations

import hashlib
import html
import math
import re
from datetime import datetime, timezone
from typing import Any

GLOBAL_COUNTRIES = ['es', 'ma', 'dz', 'fr', 'pt', 'it', 'de', 'uk', 'us', 'ca', 'eg', 'sa', 'ae', 'mx']
_IMAGE_KEYS = [
    'mainImage', 'image', 'imageUrl', 'image_url', 'thumbnail', 'thumbnailUrl',
    'picture', 'pictureUrl', 'productImage', 'largeImage', 'smallImage',
]
_IMAGES_KEYS = ['images', 'imageUrls', 'gallery', 'galleryImages', 'additionalImages', 'media']
_URL_KEYS = ['affiliateUrl', 'productUrl', 'url', 'link', 'deeplink', 'trackingUrl']
_BAD_TITLE_BITS = {
    'wholesale', 'dropshipping', 'free shipping', 'hot sale', 'best seller',
    'new arrival', 'factory price', '2024', '2025', '2026', 'for men women',
}
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ('Smart Watches', ('smart watch', 'smartwatch', 'watch series', 'wristwatch', 'fitness tracker')),
    ('Phones', ('iphone', 'samsung', 'android phone', 'mobile phone', 'smartphone')),
    ('Phone Accessories', ('case', 'charger', 'usb c', 'screen protector', 'magsafe', 'earbuds', 'headphones')),
    ('Electronics', ('electronic', 'camera', 'bluetooth', 'speaker', 'microphone', 'audio', 'memory', 'ssd', 'laptop')),
    ('Beauty', ('beauty', 'hair', 'makeup', 'skin', 'cosmetic', 'laser', 'nail')),
    ('Kitchen', ('kitchen', 'cook', 'pan', 'knife', 'coffee', 'blender')),
    ('Home', ('home', 'house', 'furniture', 'lamp', 'decor', 'bathroom', 'bedroom')),
    ('Fashion', ('fashion', 'clothes', 'shirt', 'dress', 'shoes', 'bag', 'jewelry', 'bracelet')),
    ('Fitness', ('fitness', 'sport', 'gym', 'bike', 'running', 'yoga')),
    ('Gaming', ('gaming', 'game', 'console', 'controller', 'ps5', 'xbox')),
    ('Cars', ('car', 'auto', 'vehicle', 'motorcycle', 'obd', 'dash cam')),
    ('Kids', ('kid', 'baby', 'toy', 'child')),
    ('Tools', ('tool', 'hardware', 'welding', 'drill', 'screwdriver', 'repair')),
]


def _string(value: Any, default: str = '') -> str:
    if value is None:
        return default
    text = html.unescape(str(value)).replace('\u00a0', ' ').strip()
    return re.sub(r'\s+', ' ', text)


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    raw = _string(value)
    if not raw:
        return default
    raw = raw.replace('EUR', '').replace('USD', '').replace('€', '').replace('$', '')
    raw = raw.replace('%', '').strip()
    if raw.count(',') == 1 and raw.count('.') >= 1:
        raw = raw.replace('.', '').replace(',', '.')
    else:
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


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    return _string(value).lower() in {'1', 'true', 'yes', 'y', 'active'}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    raw: list[Any]
    if isinstance(value, list):
        raw = value
    elif isinstance(value, tuple):
        raw = list(value)
    else:
        raw = re.split(r'[,|;]', _string(value))
    out: list[str] = []
    for item in raw:
        text = _string(item)
        if text and text not in out:
            out.append(text)
    return out


def extract_images(product: dict[str, Any], *, max_images: int = 6) -> list[str]:
    images: list[str] = []
    for key in _IMAGE_KEYS:
        value = _string(product.get(key))
        if value.startswith('http') and value not in images:
            images.append(value)
    for key in _IMAGES_KEYS:
        for value in _list(product.get(key)):
            if value.startswith('http') and value not in images:
                images.append(value)
    return images[:max_images]


def clean_title(title: str, *, max_words: int = 9, max_chars: int = 68) -> str:
    text = _string(title, 'Product')
    text = re.sub(r'&#039;|&quot;', ' ', text)
    text = re.sub(r'\b(202[0-9])\b', '', text, flags=re.I)
    for bad in _BAD_TITLE_BITS:
        text = re.sub(re.escape(bad), '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip(' -|,')
    words = text.split()
    if len(words) > max_words:
        text = ' '.join(words[:max_words])
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0]
    return text or 'Product'


def category_group(product: dict[str, Any]) -> str:
    haystack = ' '.join([
        _string(product.get('category')),
        _string(product.get('categoryId')),
        _string(product.get('subcategory')),
        _string(product.get('name')),
        _string(product.get('title')),
        _string(product.get('description'))[:240],
    ]).lower()
    for label, needles in _CATEGORY_RULES:
        if any(n in haystack for n in needles):
            return label
    raw = _string(product.get('category') or product.get('categoryId') or 'General')
    if not raw or raw.lower() in {'other', 'general', 'unknown', 'null'}:
        return 'General'
    return clean_title(raw, max_words=3, max_chars=28).title()


def _affiliate_url(product: dict[str, Any]) -> str:
    for key in _URL_KEYS:
        value = _string(product.get(key))
        if value.startswith('http'):
            return value
    return ''


def _countries(product: dict[str, Any], fallback_country: str = 'es') -> tuple[str, list[str], list[str]]:
    country = _string(product.get('countryCode') or product.get('country') or product.get('market') or fallback_country).lower()
    available = [c.lower() for c in _list(product.get('availableCountries') or product.get('available_countries'))]
    ships = [c.lower() for c in _list(product.get('shipsTo') or product.get('ships_to'))]
    if country in {'global', 'worldwide', 'international'}:
        country = 'global'
    if not available and country == 'global':
        available = GLOBAL_COUNTRIES[:]
    if not available and country:
        available = [country]
    if not ships:
        ships = available[:]
    return country or fallback_country, available, ships


def product_fingerprint(product: dict[str, Any]) -> str:
    base = '|'.join([
        _string(product.get('store') or product.get('source')).lower(),
        re.sub(r'[^a-z0-9]+', '', _string(product.get('name') or product.get('title')).lower())[:60],
        _string(product.get('sku') or product.get('storeSku') or product.get('productId')).lower(),
    ])
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:18]


def _fake_discount_risk(discount: int, old_price: float, price: float) -> str:
    if old_price <= price or discount <= 0:
        return 'unknown'
    if discount >= 80:
        return 'high'
    if discount >= 55:
        return 'medium'
    return 'low'


def _scores(data: dict[str, Any]) -> tuple[int, int, int, int, int, str, str]:
    price = _number(data.get('newPrice') or data.get('price'))
    old = _number(data.get('oldPrice') or data.get('old_price'))
    discount = _int(data.get('discount'))
    if discount <= 0 and old > price > 0:
        discount = int(round(((old - price) / old) * 100))
    rating = _number(data.get('rating') or data.get('averageRating'))
    review_count = _int(data.get('reviewCount') or data.get('reviews') or data.get('reviewsCount'))
    sold_count = _int(data.get('soldCount') or data.get('sold') or data.get('sales'))
    has_link = bool(_affiliate_url(data))
    has_images = bool(extract_images(data))

    quality = 55
    if has_images: quality += 12
    if price > 0: quality += 12
    if has_link: quality += 10
    if rating >= 4.2: quality += 8
    if review_count >= 50: quality += 5
    quality = max(0, min(100, quality))

    trust = 50
    if rating >= 4.6: trust += 18
    elif rating >= 4.2: trust += 12
    elif rating > 0 and rating < 3.8: trust -= 15
    if review_count >= 1000: trust += 14
    elif review_count >= 100: trust += 8
    if sold_count >= 1000: trust += 8
    if not has_link: trust -= 18
    trust = max(0, min(100, trust))

    deal = 45
    if discount >= 50: deal += 28
    elif discount >= 30: deal += 20
    elif discount >= 15: deal += 12
    if rating >= 4.3: deal += 8
    if review_count >= 100: deal += 6
    if price > 0 and price <= 25: deal += 4
    deal = max(0, min(100, deal))

    risk = 100 - int((quality * .40) + (trust * .45) + (deal * .15))
    if discount >= 80: risk += 16
    if rating > 0 and rating < 3.8: risk += 15
    risk = max(0, min(100, risk))

    if risk >= 70:
        verdict, label = 'avoid', 'Avoid'
    elif discount >= 30 and trust >= 65 and quality >= 70:
        verdict, label = 'buy_now', 'Buy Now'
    elif deal >= 68 and risk < 55:
        verdict, label = 'safe_deal', 'Safe Deal'
    elif risk >= 50:
        verdict, label = 'risky', 'Risky'
    else:
        verdict, label = 'wait', 'Wait'
    return deal, trust, quality, risk, discount, verdict, label


def standardize_product(product: dict[str, Any], *, document_id: str | None = None, fallback_country: str = 'es') -> dict[str, Any]:
    data = dict(product or {})
    pid = _string(document_id or data.get('id') or data.get('productId') or data.get('sku') or product_fingerprint(data))
    raw_title = _string(data.get('fullTitle') or data.get('title') or data.get('name') or 'Product')
    name = clean_title(_string(data.get('name') or raw_title))
    images = extract_images(data)
    country, available, ships = _countries(data, fallback_country=fallback_country)
    price = _number(data.get('newPrice') or data.get('price') or data.get('sale_price') or data.get('currentPrice'))
    old_price = _number(data.get('oldPrice') or data.get('old_price') or data.get('original_price'))
    deal, trust, quality, risk, discount, verdict, verdict_label = _scores({**data, 'newPrice': price, 'oldPrice': old_price})
    store = _string(data.get('store') or data.get('storeName') or data.get('source') or 'Store')
    category = category_group({**data, 'name': name, 'title': raw_title})
    rating = _number(data.get('rating') or data.get('averageRating'))
    review_count = _int(data.get('reviewCount') or data.get('reviews') or data.get('reviewsCount'))
    sold_count = _int(data.get('soldCount') or data.get('sold') or data.get('sales'))
    price_accuracy = _string(data.get('priceAccuracy') or ('estimated' if 'dhgate' in store.lower() or data.get('source') == 'impact' else 'live'))
    price_source = _string(data.get('priceSource') or ('impact_feed' if data.get('source') == 'impact' else 'api'))
    main_image = images[0] if images else ''
    now = datetime.now(timezone.utc).isoformat()
    return {
        **data,
        'id': pid,
        'name': name,
        'fullTitle': raw_title,
        'description': _string(data.get('description') or raw_title),
        'image': main_image,
        'mainImage': main_image,
        'images': images,
        'newPrice': price,
        'oldPrice': old_price,
        'discount': discount,
        'store': store,
        'category': category,
        'categoryGroup': category,
        'affiliateUrl': _affiliate_url(data),
        'country': country,
        'countryCode': country,
        'availableCountries': available,
        'shipsTo': ships,
        'currency': _string(data.get('currency') or ('EUR' if country == 'es' else 'USD')),
        'rating': rating,
        'reviewCount': review_count,
        'soldCount': sold_count,
        'views': _int(data.get('views')),
        'clicks': _int(data.get('clicks')),
        'sales': _int(data.get('sales') or sold_count),
        'dealScore': _int(data.get('dealScore'), deal) or deal,
        'trustScore': _int(data.get('trustScore'), trust) or trust,
        'qualityScore': _int(data.get('qualityScore'), quality) or quality,
        'riskScore': _int(data.get('riskScore'), risk) or risk,
        'aiVerdict': data.get('aiVerdict') or verdict,
        'aiVerdictLabel': data.get('aiVerdictLabel') or verdict_label,
        'fakeDiscountRisk': data.get('fakeDiscountRisk') or _fake_discount_risk(discount, old_price, price),
        'dealDNA': {
            'price': max(0, min(100, int(100 - min(price, 100)))) if price > 0 else 40,
            'quality': quality,
            'trust': trust,
            'discount': min(100, discount * 2),
            'delivery': 65 if ships else 45,
            'popularity': min(100, int((review_count / 20) + (sold_count / 100))),
            'risk': risk,
        },
        'priceAccuracy': price_accuracy,
        'priceSource': price_source,
        'finalPriceInStore': True,
        'priceNote': data.get('priceNote') or ('Precio aprox. · precio final en tienda' if price_accuracy == 'estimated' else 'Precio actual'),
        'shippingPrice': _number(data.get('shippingPrice') or data.get('shipping_price')),
        'freeShipping': _bool(data.get('freeShipping') or data.get('free_shipping')),
        'estimatedDelivery': _string(data.get('estimatedDelivery') or data.get('deliveryTime')),
        'couponText': _string(data.get('couponText') or data.get('coupon') or data.get('promoCode')),
        'hasCoupon': bool(_string(data.get('couponText') or data.get('coupon') or data.get('promoCode'))),
        'variants': data.get('variants') if isinstance(data.get('variants'), list) else [],
        'isHot': _bool(data.get('isHot')) or deal >= 75,
        'featured': _bool(data.get('featured')) or trust >= 75,
        'sponsored': _bool(data.get('sponsored')),
        'isOnline': not (_number(data.get('lat')) and _number(data.get('lng'))),
        'fingerprint': data.get('fingerprint') or product_fingerprint({**data, 'name': name, 'store': store}),
        'visibleToUsers': data.get('visibleToUsers', True),
        'status': _string(data.get('status') or 'active'),
        'standardVersion': 'ofertix-product-standard-v1',
        'standardizedAt': data.get('standardizedAt') or now,
    }


def available_for_country(product: dict[str, Any], country: str) -> bool:
    market = (country or 'es').lower()
    if market == 'global':
        return True
    code = _string(product.get('countryCode') or product.get('country')).lower()
    countries = [c.lower() for c in _list(product.get('availableCountries'))]
    ships = [c.lower() for c in _list(product.get('shipsTo'))]
    return code in {market, 'global'} or market in countries or market in ships
