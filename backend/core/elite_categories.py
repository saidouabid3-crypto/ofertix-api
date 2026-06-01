from __future__ import annotations

import re
from typing import Any

"""Canonical Ofertix Elite taxonomy — exactly 18 categories."""

ELITE_CATEGORIES: tuple[str, ...] = (
    "fashion",
    "electronics",
    "phones",
    "computers",
    "home",
    "beauty",
    "sports",
    "kids",
    "gaming",
    "food",
    "supermarket",
    "pharmacy",
    "travel",
    "tools",
    "pets",
    "automotive",
    "jewelry",
    "general",
)

_LEGACY_TO_ELITE: dict[str, str] = {
    "smart watches": "electronics",
    "smartwatches": "electronics",
    "phones": "phones",
    "phone": "phones",
    "electronics": "electronics",
    "electronica": "electronics",
    "electrónica": "electronics",
    "tech": "electronics",
    "gadgets": "electronics",
    "computers": "computers",
    "computer": "computers",
    "laptop": "computers",
    "pc": "computers",
    "beauty": "beauty",
    "belleza": "beauty",
    "skincare": "beauty",
    "makeup": "beauty",
    "perfume": "beauty",
    "cosmetic": "beauty",
    "fashion": "fashion",
    "moda": "fashion",
    "ropa": "fashion",
    "clothes": "fashion",
    "shoes": "fashion",
    "jewelry": "jewelry",
    "jewellery": "jewelry",
    "kitchen": "home",
    "home": "home",
    "casa": "home",
    "hogar": "home",
    "furniture": "home",
    "tools": "tools",
    "herramientas": "tools",
    "cars": "automotive",
    "car": "automotive",
    "automotive": "automotive",
    "auto": "automotive",
    "vehicle": "automotive",
    "kids": "kids",
    "baby": "kids",
    "toys": "kids",
    "gaming": "gaming",
    "gamer": "gaming",
    "fitness": "sports",
    "sports": "sports",
    "sport": "sports",
    "gym": "sports",
    "food": "food",
    "comida": "food",
    "restaurant": "food",
    "supermarket": "supermarket",
    "supermercado": "supermarket",
    "grocery": "supermarket",
    "pharmacy": "pharmacy",
    "farmacia": "pharmacy",
    "health": "pharmacy",
    "travel": "travel",
    "viajes": "travel",
    "hotel": "travel",
    "pets": "pets",
    "mascotas": "pets",
    "general": "general",
}

_CATEGORY_KEYWORDS: list[tuple[str, set[str]]] = [
    ("phones", {"iphone", "samsung", "smartphone", "mobile", "phone", "android phone"}),
    ("computers", {"laptop", "notebook", "macbook", "desktop", "pc", "ssd", "ram", "monitor"}),
    ("electronics", {"camera", "speaker", "headphone", "earbuds", "charger", "tablet", "tv", "smartwatch"}),
    ("beauty", {"beauty", "makeup", "cosmetic", "perfume", "skincare", "nail", "hair care"}),
    ("fashion", {"dress", "shirt", "pants", "jeans", "jacket", "shoe", "sneaker", "bag", "fashion"}),
    ("jewelry", {"ring", "necklace", "bracelet", "earring", "jewelry", "gold chain"}),
    ("home", {"kitchen", "cookware", "furniture", "lamp", "sofa", "bed", "decor", "home"}),
    ("tools", {"drill", "wrench", "screwdriver", "tool", "hardware"}),
    ("automotive", {"car", "auto", "vehicle", "motorcycle", "tire"}),
    ("kids", {"baby", "kid", "children", "toy", "stroller"}),
    ("gaming", {"gaming", "playstation", "xbox", "nintendo", "controller"}),
    ("sports", {"fitness", "gym", "yoga", "running", "sport", "football"}),
    ("food", {"food", "snack", "restaurant", "meal"}),
    ("supermarket", {"supermarket", "grocery", "supermercado"}),
    ("pharmacy", {"pharmacy", "vitamin", "medicine", "farmacia"}),
    ("travel", {"travel", "hotel", "flight", "luggage", "viaje"}),
    ("pets", {"pet", "dog", "cat", "mascota"}),
]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def map_to_elite_category(raw: str | None) -> str:
    if not raw:
        return "general"
    key = _slug(raw)
    if key in ELITE_CATEGORIES:
        return key
    if key in _LEGACY_TO_ELITE:
        return _LEGACY_TO_ELITE[key]
    for token, mapped in _LEGACY_TO_ELITE.items():
        if token in key or key in token:
            return mapped
    return "general"


def classify_elite_category(item: dict[str, Any]) -> tuple[str, float, str]:
    hay = " ".join(
        str(item.get(field) or "")
        for field in ("name", "title", "description", "category", "categoryGroup", "sourceCategory", "storeCategory")
    ).lower()

    best = ("general", 0.35, "fallback")
    for category, keywords in _CATEGORY_KEYWORDS:
        hits = [kw for kw in keywords if kw in hay]
        if hits:
            confidence = min(0.98, 0.72 + len(hits) * 0.08)
            if confidence > best[1]:
                best = (category, confidence, f"matched: {', '.join(hits[:4])}")

    mapped = map_to_elite_category(item.get("category") or item.get("categoryGroup"))
    if mapped != "general" and best[0] == "general":
        return mapped, 0.62, f"mapped legacy category: {item.get('category')}"

    return best
