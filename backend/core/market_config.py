from __future__ import annotations

from core.locale_context import currency_for_country


def _c(country_upper: str, fallback: str) -> str:
    return currency_for_country(country_upper) or fallback


SUPPORTED_MARKETS: dict[str, dict] = {
    "es": {"name": "Spain",                 "currency": _c("ES", "EUR"), "languages": ["es", "en", "ar", "fr"]},
    "ma": {"name": "Morocco",               "currency": _c("MA", "MAD"), "languages": ["ar", "fr", "es", "en"]},
    "dz": {"name": "Algeria",               "currency": _c("DZ", "DZD"), "languages": ["ar", "fr", "en"]},
    "fr": {"name": "France",                "currency": _c("FR", "EUR"), "languages": ["fr", "en", "ar"]},
    "pt": {"name": "Portugal",              "currency": _c("PT", "EUR"), "languages": ["pt", "en", "es"]},
    "it": {"name": "Italy",                 "currency": _c("IT", "EUR"), "languages": ["it", "en"]},
    "de": {"name": "Germany",               "currency": _c("DE", "EUR"), "languages": ["de", "en"]},
    "uk": {"name": "United Kingdom",        "currency": _c("GB", "GBP"), "languages": ["en"]},
    "us": {"name": "United States",         "currency": _c("US", "USD"), "languages": ["en", "es"]},
    "ca": {"name": "Canada",                "currency": _c("CA", "CAD"), "languages": ["en", "fr"]},
    "eg": {"name": "Egypt",                 "currency": _c("EG", "EGP"), "languages": ["ar", "en"]},
    "sa": {"name": "Saudi Arabia",          "currency": _c("SA", "SAR"), "languages": ["ar", "en"]},
    "ae": {"name": "United Arab Emirates",  "currency": _c("AE", "AED"), "languages": ["ar", "en"]},
    "mx": {"name": "Mexico",                "currency": _c("MX", "MXN"), "languages": ["es", "en"]},
}

_ALIASES: dict[str, str] = {
    "gb": "uk", "usa": "us", "united-states": "us",
    "spain": "es", "morocco": "ma", "algeria": "dz", "canada": "ca",
}


def normalize_market(country: str | None) -> str:
    raw = (country or "es").strip().lower().replace("_", "-")
    code = _ALIASES.get(raw, raw)
    return code if code in SUPPORTED_MARKETS else "es"
