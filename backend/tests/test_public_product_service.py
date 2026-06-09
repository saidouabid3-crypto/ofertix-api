import asyncio

from core.image_validator import filter_valid_images_sync
from services.public_product_service import (
    is_usable_public_product,
    prepare_public_product,
)
from utils.market_filter import item_available_for_country, normalize_item_market_fields


def _active_global_product() -> dict:
    return {
        "id": "impact_product",
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


def test_explicit_global_availability_is_accepted_in_strict_market_mode():
    item = normalize_item_market_fields(_active_global_product(), fallback_country="es")

    assert item["isExplicitlyGlobal"] is True
    assert item_available_for_country(item, "es") is True
    assert item_available_for_country(item, "fr") is True


def test_public_preparation_preserves_stored_catalog_status(monkeypatch):
    raw = _active_global_product()

    def fake_normalize(item, *, fallback_country):
        return {**item, "status": "needs_market_review", "visibleToUsers": False}

    monkeypatch.setattr(
        "services.public_product_service.normalize_product",
        fake_normalize,
    )

    prepared = prepare_public_product(raw, "es")

    assert prepared["status"] == "active"
    assert prepared["visibleToUsers"] is True
    assert is_usable_public_product(prepared, "es") is True


def test_needs_review_is_publicly_eligible_but_quarantined_is_not():
    needs_review = prepare_public_product(
        {**_active_global_product(), "status": "needs_review"},
        "es",
    )
    quarantined = {
        **needs_review,
        "status": "quarantined",
        "trustStatus": "quarantined",
    }

    assert is_usable_public_product(needs_review, "es") is True
    assert is_usable_public_product(quarantined, "es") is False


def test_sync_image_filter_does_not_block_an_active_event_loop():
    async def invoke():
        return filter_valid_images_sync(
            ["https://example.com/one.jpg", "invalid"],
            max_images=3,
        )

    assert asyncio.run(invoke()) == ["https://example.com/one.jpg"]
