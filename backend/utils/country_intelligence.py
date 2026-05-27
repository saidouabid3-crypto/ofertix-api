from __future__ import annotations

from typing import Any, Dict, Iterable, List

GLOBAL_CODES = {'global', 'ww', 'world', 'all', '*'}


def normalize_country(value: Any, default: str = 'global') -> str:
    raw = str(value or default).strip().lower()
    if not raw:
        return default
    aliases = {
        'spain': 'es', 'espana': 'es', 'españa': 'es',
        'morocco': 'ma', 'maroc': 'ma', 'marruecos': 'ma',
        'france': 'fr', 'egypt': 'eg', 'egypte': 'eg', 'us': 'us', 'usa': 'us',
        'united states': 'us', 'uk': 'gb', 'united kingdom': 'gb',
    }
    return aliases.get(raw, raw)


def normalize_country_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(';', ',').split(',')]
    elif isinstance(value, Iterable):
        parts = [str(part).strip() for part in value]
    else:
        parts = [str(value).strip()]
    return [normalize_country(part) for part in parts if part]


def item_country_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    country = normalize_country(
        item.get('countryCode')
        or item.get('country_code')
        or item.get('storeCountry')
        or item.get('sellerCountryCode')
        or item.get('seller_country_code')
        or item.get('country')
        or 'global'
    )

    available = normalize_country_list(
        item.get('availableCountries')
        or item.get('available_countries')
        or item.get('countries')
    )
    ships_to = normalize_country_list(
        item.get('shipsTo')
        or item.get('ships_to')
        or item.get('shippingCountries')
        or item.get('shipping_countries')
    )

    if country and country not in GLOBAL_CODES and country not in available:
        available.append(country)

    return {'country': country, 'availableCountries': available, 'shipsTo': ships_to}


def item_matches_country(item: Dict[str, Any], country: str) -> bool:
    requested = normalize_country(country)
    if requested in GLOBAL_CODES:
        return True

    fields = item_country_fields(item)
    country_code = fields['country']
    available = set(fields['availableCountries'])
    ships_to = set(fields['shipsTo'])

    pickup_only = bool(item.get('pickupOnly') or item.get('pickup_only'))

    if country_code in GLOBAL_CODES:
        return requested in available or requested in ships_to or bool(item.get('isGlobal'))

    if country_code == requested or requested in available:
        return True

    if not pickup_only and requested in ships_to:
        return True

    return False


def enrich_country_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(item)
    fields = item_country_fields(data)
    data['countryCode'] = fields['country']
    data['country'] = fields['country']
    data['availableCountries'] = fields['availableCountries']
    data['shipsTo'] = fields['shipsTo']
    return data
