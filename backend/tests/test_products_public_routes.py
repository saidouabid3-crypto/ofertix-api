import asyncio
import os

os.environ.setdefault("FIREBASE_REQUIRED", "false")

from routes import products as product_routes


def _product() -> dict:
    return {
        "id": "impact_1",
        "name": "Wireless charging station",
        "fullTitle": "Wireless charging station",
        "description": "Phone charging accessory",
        "status": "active",
        "visibleToUsers": True,
        "countryCode": "global",
        "country": "global",
        "availableCountries": ["es", "fr", "us"],
        "shipsTo": ["es", "fr", "us"],
        "image": "https://example.com/product.jpg",
        "mainImage": "https://example.com/product.jpg",
        "images": ["https://example.com/product.jpg"],
        "newPrice": 17.32,
        "currency": "EUR",
        "affiliateUrl": "https://example.com/offer",
        "store": "Example",
        "source": "impact",
    }


def test_list_and_search_share_public_product_preparation(monkeypatch):
    monkeypatch.setattr(product_routes, "_stream_products", lambda limit: [_product()])
    monkeypatch.setattr(
        product_routes,
        "load_catalog_config",
        lambda: {
            "publicFilteringEnabled": False,
            "smartRankingEnabled": True,
        },
    )

    listed = asyncio.run(
        product_routes.get_products(country="es", limit=10, page=1)
    )
    searched = asyncio.run(
        product_routes.search_products(
            product_routes.ProductSearchRequest(query="", country="es", limit=10)
        )
    )

    assert listed["count"] == 1
    assert searched["count"] == 1
    assert listed["products"][0]["id"] == searched["products"][0]["id"]
    assert listed["products"][0]["status"] == "active"
