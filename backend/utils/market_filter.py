from core.market_config import normalize_market

def _list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip().lower() for v in value.split(',') if v.strip()]
    return []

def item_available_for_country(item: dict, country: str) -> bool:
    code = normalize_market(country)
    item_country = str(item.get('countryCode') or item.get('country_code') or item.get('country') or 'global').lower()
    seller_country = str(item.get('sellerCountryCode') or item.get('seller_country_code') or item_country).lower()
    pickup_only = bool(item.get('pickupOnly') if 'pickupOnly' in item else item.get('pickup_only', False))
    available = _list(item.get('availableCountries') or item.get('available_countries'))
    ships_to = _list(item.get('shipsTo') or item.get('ships_to'))
    if pickup_only:
        return seller_country == code or item_country == code
    if item_country == 'global':
        return code in available or code in ships_to
    return item_country == code or seller_country == code or code in available or code in ships_to

def normalize_item_market_fields(item: dict, fallback_country: str = 'es') -> dict:
    country = normalize_market(item.get('countryCode') or item.get('country_code') or item.get('country') or fallback_country)
    item['countryCode'] = country
    item['country'] = country
    item.setdefault('availableCountries', [country])
    item.setdefault('shipsTo', [])
    return item
