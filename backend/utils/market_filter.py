from core.market_config import SUPPORTED_MARKETS, normalize_market


def _normalize_country_code(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw == "global":
        return "global"
    return normalize_market(raw)


def _list(value):
    if value is None:
        return []

    if isinstance(value, list):
        raw_values = value
    elif isinstance(value, str):
        raw_values = value.split(",")
    else:
        return []

    result = []
    for item in raw_values:
        raw = str(item).strip().lower()
        if not raw:
            continue
        code = _normalize_country_code(raw)
        if code not in result:
            result.append(code)
    return result


def item_available_for_country(item: dict, country: str, *, strict: bool = True) -> bool:
    """Country isolation for Ofertix Elite.

    Strict mode (default): users only see products whose ``countryCode`` matches
    their market. Explicitly global catalog items remain available when
  ``isExplicitlyGlobal`` is true and the user's country is listed in
    ``availableCountries`` / ``shipsTo``.
    """

    if item.get("isExpired") is True:
        return False

    code = normalize_market(country)

    item_country = _normalize_country_code(
        item.get("countryCode") or item.get("country_code") or item.get("country") or "global"
    )
    seller_country = _normalize_country_code(
        item.get("sellerCountryCode") or item.get("seller_country_code") or item_country
    )

    pickup_only = bool(item.get("pickupOnly") if "pickupOnly" in item else item.get("pickup_only", False))
    available = _list(item.get("availableCountries") or item.get("available_countries"))
    ships_to = _list(item.get("shipsTo") or item.get("ships_to"))

    if pickup_only:
        return seller_country == code or item_country == code

    if strict:
        if bool(item.get("isExplicitlyGlobal") is True):
            return code in available or code in ships_to or "global" in available
        if item_country == "global":
            return False
        return item_country == code

    if item_country == "global":
        return "global" in available or code in available or code in ships_to

    return item_country == code or seller_country == code or code in available or code in ships_to


def normalize_item_market_fields(item: dict, fallback_country: str = "es") -> dict:
    raw_country = str(
        item.get("countryCode") or item.get("country_code") or item.get("country") or fallback_country
    ).strip().lower()

    country = "global" if raw_country == "global" else normalize_market(raw_country)

    item["countryCode"] = country
    item["country"] = country

    available = _list(item.get("availableCountries") or item.get("available_countries"))
    ships_to = _list(item.get("shipsTo") or item.get("ships_to"))

    if country == "global":
        item["availableCountries"] = [c for c in available if c in SUPPORTED_MARKETS]
        if not item["availableCountries"]:
            item["availableCountries"] = list(SUPPORTED_MARKETS.keys())
    else:
        item["availableCountries"] = [c for c in available if c in SUPPORTED_MARKETS] or [country]

    item["shipsTo"] = [c for c in ships_to if c in SUPPORTED_MARKETS]
    return item
