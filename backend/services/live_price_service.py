from typing import Dict, Any


async def fetch_live_price(product: Dict[str, Any]) -> Dict[str, Any]:
    store = (product.get("store") or "").lower()

    if "dhgate" in store:
        return {
            "success": False,
            "error": "DHgate live scraping disabled: price is estimated from Impact feed",
            "priceAccuracy": "estimated",
            "priceSource": "impact_feed",
            "finalPriceInStore": True,
            "priceNote": (
                "Precio aproximado desde el feed de afiliación. "
                "El precio final se confirma en DHgate."
            ),
        }

    return {
        "success": False,
        "error": f"No live price adapter for store: {product.get('store')}",
        "priceAccuracy": "estimated",
        "priceSource": product.get("source") or "unknown",
        "finalPriceInStore": True,
    }