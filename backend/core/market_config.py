SUPPORTED_MARKETS = {
    'es': {'name': 'Spain', 'currency': 'EUR', 'languages': ['es','en','ar','fr']},
    'ma': {'name': 'Morocco', 'currency': 'MAD', 'languages': ['ar','fr','es','en']},
    'dz': {'name': 'Algeria', 'currency': 'DZD', 'languages': ['ar','fr','en']},
    'fr': {'name': 'France', 'currency': 'EUR', 'languages': ['fr','en','ar']},
    'pt': {'name': 'Portugal', 'currency': 'EUR', 'languages': ['pt','en','es']},
    'it': {'name': 'Italy', 'currency': 'EUR', 'languages': ['it','en']},
    'de': {'name': 'Germany', 'currency': 'EUR', 'languages': ['de','en']},
    'uk': {'name': 'United Kingdom', 'currency': 'GBP', 'languages': ['en']},
    'us': {'name': 'United States', 'currency': 'USD', 'languages': ['en','es']},
    'ca': {'name': 'Canada', 'currency': 'CAD', 'languages': ['en','fr']},
    'eg': {'name': 'Egypt', 'currency': 'EGP', 'languages': ['ar','en']},
    'sa': {'name': 'Saudi Arabia', 'currency': 'SAR', 'languages': ['ar','en']},
    'ae': {'name': 'United Arab Emirates', 'currency': 'AED', 'languages': ['ar','en']},
    'mx': {'name': 'Mexico', 'currency': 'MXN', 'languages': ['es','en']},
}

def normalize_market(country: str | None) -> str:
    raw = (country or 'es').strip().lower().replace('_', '-')
    aliases = {'gb': 'uk', 'usa': 'us', 'united-states': 'us', 'spain': 'es', 'morocco': 'ma', 'algeria': 'dz', 'canada': 'ca'}
    code = aliases.get(raw, raw)
    return code if code in SUPPORTED_MARKETS else 'es'
