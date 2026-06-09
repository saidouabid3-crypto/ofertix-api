from __future__ import annotations

from typing import Any

from utils.market_filter import item_available_for_country, normalize_item_market_fields
from utils.product_standard import normalize_product


PUBLIC_PRODUCT_STATUSES = {
    "active",
    "approved",
    "published",
    "trusted",
    "needs_review",
}

_PRESERVED_CATALOG_FIELDS = (
    "status",
    "visibleToUsers",
    "isExpired",
    "adminIssue",
)


def prepare_public_product(raw: dict[str, Any], market: str) -> dict[str, Any]:
    """Normalize display fields without overwriting stored catalog decisions."""
    source = dict(raw)
    item = normalize_product(
        normalize_item_market_fields(dict(source), fallback_country=market),
        fallback_country=market,
    )
    for key in _PRESERVED_CATALOG_FIELDS:
        if key in source:
            item[key] = source[key]
    return item


def public_product_exclusion_reason(item: dict[str, Any], market: str) -> str | None:
    source = str(item.get("source") or "").strip().lower()
    store = str(item.get("store") or "").strip().lower()
    if source == "aliexpress" or "aliexpress" in store or store.startswith("ae-"):
        return "blocked_store"
    if item.get("isExpired") is True:
        return "expired"

    status = str(item.get("status") or "active").strip().lower()
    if status not in PUBLIC_PRODUCT_STATUSES:
        return f"status:{status or '(empty)'}"
    if item.get("visibleToUsers") is False:
        return "visibleToUsers:false"
    if not item.get("image") and not item.get("mainImage"):
        return "missing_image"
    try:
        price = float(item.get("newPrice") or item.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return "missing_price"
    if not item_available_for_country(item, market):
        return "country_mismatch"
    if str(item.get("categoryGroup") or item.get("category")).lower() == "kitchen":
        haystack = f"{item.get('name', '')} {item.get('description', '')}".lower()
        negatives = {
            "shoe",
            "sneaker",
            "ring",
            "jewelry",
            "earring",
            "necklace",
            "watch",
            "phone",
            "dress",
            "pants",
            "bag",
        }
        if any(word in haystack for word in negatives):
            return "invalid_kitchen_category"
    return None


def is_usable_public_product(item: dict[str, Any], market: str) -> bool:
    return public_product_exclusion_reason(item, market) is None
