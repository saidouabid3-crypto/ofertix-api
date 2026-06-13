from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.market_config import SUPPORTED_MARKETS

SUPPORTED_COUNTRIES = {'ES', 'FR', 'MA', 'PT', 'IT', 'DE', 'OTHER'}
SUPPORTED_CATEGORIES = {
    'electronics',
    'fashion',
    'home',
    'sports',
    'beauty',
    'toys',
    'books',
    'automotive',
    'other',
}
SUPPORTED_CONDITIONS = {'new', 'like_new', 'good', 'fair', 'poor'}
SUPPORTED_DELIVERY_METHODS = {'pickup', 'shipping', 'both'}
IMPORTANT_LISTING_FIELDS = {
    'title',
    'description',
    'price',
    'currencyCode',
    'countryCode',
    'city',
    'postalCode',
    'area',
    'categoryKey',
    'conditionKey',
    'deliveryMethodKey',
    'images',
    'coverImage',
}

_COUNTRY_NAMES = {
    'ES': 'Spain',
    'FR': 'France',
    'MA': 'Morocco',
    'PT': 'Portugal',
    'IT': 'Italy',
    'DE': 'Germany',
    'OTHER': 'Other',
}


class MarketplaceValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _required_text(
    payload: Dict[str, Any],
    key: str,
    *,
    minimum: int = 1,
    maximum: int = 5000,
) -> str:
    value = str(payload.get(key) or '').strip()
    if len(value) < minimum:
        raise MarketplaceValidationError(
            f'INVALID_{key.upper()}',
            f'{key} must contain at least {minimum} characters',
        )
    if len(value) > maximum:
        raise MarketplaceValidationError(
            f'INVALID_{key.upper()}',
            f'{key} must contain at most {maximum} characters',
        )
    return value


def _optional_text(payload: Dict[str, Any], key: str, maximum: int) -> str:
    value = str(payload.get(key) or '').strip()
    if len(value) > maximum:
        raise MarketplaceValidationError(
            f'INVALID_{key.upper()}',
            f'{key} must contain at most {maximum} characters',
        )
    return value


def _choice(
    payload: Dict[str, Any],
    key: str,
    aliases: Iterable[str],
    supported: set[str],
) -> str:
    raw = payload.get(key)
    if raw is None:
        for alias in aliases:
            if payload.get(alias) is not None:
                raw = payload.get(alias)
                break
    value = str(raw or '').strip().lower()
    if value not in supported:
        error_field = {
            'categoryKey': 'CATEGORY_KEY',
            'conditionKey': 'CONDITION_KEY',
            'deliveryMethodKey': 'DELIVERY_METHOD_KEY',
        }.get(key, key.upper())
        raise MarketplaceValidationError(
            f'INVALID_{error_field}',
            f'{key} must be one of: {", ".join(sorted(supported))}',
        )
    return value


def _country_code(payload: Dict[str, Any]) -> str:
    raw = (
        payload.get('countryCode')
        or payload.get('sellerCountryCode')
        or payload.get('country')
        or ''
    )
    code = str(raw).strip().upper()
    aliases = {
        'SPAIN': 'ES',
        'FRANCE': 'FR',
        'MOROCCO': 'MA',
        'PORTUGAL': 'PT',
        'ITALY': 'IT',
        'GERMANY': 'DE',
    }
    code = aliases.get(code, code)
    if code not in SUPPORTED_COUNTRIES:
        raise MarketplaceValidationError(
            'INVALID_COUNTRY_CODE',
            'countryCode must be ES, FR, MA, PT, IT, DE, or OTHER',
        )
    return code


def _price(payload: Dict[str, Any]) -> float:
    try:
        value = float(str(payload.get('price') or '').replace(',', '.'))
    except (TypeError, ValueError):
        value = 0
    if value <= 0 or value > 100_000_000:
        raise MarketplaceValidationError(
            'INVALID_PRICE',
            'price must be greater than zero',
        )
    return round(value, 2)


def _images(payload: Dict[str, Any]) -> List[str]:
    raw = payload.get('images') or payload.get('gallery') or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise MarketplaceValidationError('INVALID_IMAGES', 'images must be a list')
    images = [str(value or '').strip() for value in raw]
    images = list(dict.fromkeys(value for value in images if value))
    if not images:
        raise MarketplaceValidationError(
            'IMAGES_REQUIRED',
            'At least one image is required',
        )
    if len(images) > 10:
        raise MarketplaceValidationError(
            'TOO_MANY_IMAGES',
            'A maximum of 10 images is allowed',
        )
    return images


def validate_and_normalize_listing(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    country_code = _country_code(data)
    market = country_code.lower()
    currency = str(data.get('currencyCode') or data.get('currency') or '').upper()
    if country_code != 'OTHER':
        currency = SUPPORTED_MARKETS[market]['currency']
    elif len(currency) != 3 or not currency.isalpha():
        currency = 'EUR'

    category = _choice(
        data,
        'categoryKey',
        ('category',),
        SUPPORTED_CATEGORIES,
    )
    condition = _choice(
        data,
        'conditionKey',
        ('condition',),
        SUPPORTED_CONDITIONS,
    )
    delivery = _choice(
        data,
        'deliveryMethodKey',
        ('deliveryMethod',),
        SUPPORTED_DELIVERY_METHODS,
    )
    images = _images(data)
    cover = str(data.get('coverImage') or data.get('image') or images[0]).strip()
    if cover not in images:
        raise MarketplaceValidationError(
            'INVALID_COVER_IMAGE',
            'coverImage must be one of the listing images',
        )

    normalized = {
        'title': _required_text(data, 'title', minimum=3, maximum=120),
        'description': _required_text(
            data,
            'description',
            minimum=8,
            maximum=5000,
        ),
        'price': _price(data),
        'currencyCode': currency,
        'currency': currency,
        'countryCode': country_code,
        'countryName': _COUNTRY_NAMES[country_code],
        'country': market,
        'sellerCountryCode': market,
        'city': _required_text(data, 'city', maximum=120),
        'postalCode': _optional_text(data, 'postalCode', 24),
        'area': _optional_text(data, 'area', 120),
        'approximateLocationLabel': _optional_text(
            data,
            'approximateLocationLabel',
            180,
        ),
        'categoryKey': category,
        'category': category,
        'conditionKey': condition,
        'condition': condition,
        'deliveryMethodKey': delivery,
        'images': images,
        'coverImage': cover,
        'image': cover,
        'imageCount': len(images),
        'pickupOnly': delivery == 'pickup',
        'availableCountries': [market],
        'shipsTo': [market] if delivery in {'shipping', 'both'} else [],
    }
    if not normalized['approximateLocationLabel']:
        location = [normalized['city'], normalized['area']]
        normalized['approximateLocationLabel'] = ', '.join(
            value for value in location if value
        )
    return normalized
