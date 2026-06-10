from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

os.environ.setdefault("FIREBASE_REQUIRED", "false")

from routes import products as product_routes
from services.deal_verdict_service import analyze_deal_verdict


def _product(**overrides):
    product = {
        "id": "deal-1",
        "name": "Trusted running shoes",
        "status": "active",
        "visibleToUsers": True,
        "newPrice": 60,
        "oldPrice": 100,
        "discount": 40,
        "currency": "EUR",
        "priceConfidence": "confirmed",
        "priceAccuracy": "live",
        "priceSource": "store_feed",
        "finalPriceInStore": False,
        "priceLastCheckedAt": datetime.now(timezone.utc).isoformat(),
        "trustStatus": "trusted",
        "qualityScore": 90,
        "qualityFlags": [],
        "category": "shoes",
        "categoryGroup": "shoes",
        "categoryConfidence": 0.9,
        "stockAvailability": "InStock",
        "shippingConfidence": "high",
        "affiliateUrl": "https://example.com/deal-1",
        "images": [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
        ],
    }
    product.update(overrides)
    return product


def test_trusted_product_is_buy_now_or_check_store():
    result = analyze_deal_verdict(_product())
    assert result["verdict"] in {"buy_now", "check_store"}
    assert result["confidence"] >= 75


def test_estimated_affiliate_price_prefers_check_store():
    result = analyze_deal_verdict(_product(
        priceAccuracy="estimated",
        priceSource="impact_feed",
        finalPriceInStore=True,
    ))
    assert result["verdict"] == "check_store"
    assert "Final price may change in store." in result["warnings"]


def test_extreme_estimated_discount_is_high_risk():
    result = analyze_deal_verdict(_product(
        newPrice=5,
        oldPrice=100,
        discount=95,
        priceConfidence="approximate",
        priceAccuracy="estimated",
        finalPriceInStore=True,
    ))
    assert result["riskLevel"] in {"high", "critical"}
    assert result["verdict"] in {"wait", "avoid"}


def test_missing_price_is_avoid():
    result = analyze_deal_verdict(
        _product(newPrice=0, qualityFlags=["missing_price"])
    )
    assert result["verdict"] == "avoid"


def test_missing_link_is_avoid():
    result = analyze_deal_verdict(_product(affiliateUrl="", productUrl=""))
    assert result["verdict"] == "avoid"


def test_expired_product_is_avoid():
    result = analyze_deal_verdict(_product(status="expired", isExpired=True))
    assert result["verdict"] == "avoid"


def test_hidden_product_is_avoid_in_pure_engine():
    result = analyze_deal_verdict(_product(visibleToUsers=False))
    assert result["verdict"] == "avoid"


def test_duplicate_candidate_adds_penalty():
    clean = analyze_deal_verdict(_product())
    duplicate = analyze_deal_verdict(_product(
        duplicateStatus="candidate",
        qualityFlags=["duplicate_candidate"],
    ))
    assert duplicate["confidence"] < clean["confidence"]
    assert any(r["code"] == "duplicate_candidate" for r in duplicate["reasons"])


def test_single_image_warning_is_not_automatic_avoid():
    result = analyze_deal_verdict(_product(
        images=["https://example.com/1.jpg"],
        qualityFlags=["single_image_only"],
    ))
    assert result["verdict"] != "avoid"
    assert any(r["code"] == "single_image_only" for r in result["reasons"])


def test_unknown_category_lowers_confidence():
    known = analyze_deal_verdict(_product())
    unknown = analyze_deal_verdict(_product(
        category="general",
        categoryGroup="general",
        categoryConfidence=0,
        qualityFlags=["unknown_category"],
    ))
    assert unknown["confidence"] < known["confidence"]


def test_trusted_high_quality_increases_confidence():
    weak = analyze_deal_verdict(_product(
        trustStatus="needs_review",
        qualityScore=40,
    ))
    strong = analyze_deal_verdict(_product())
    assert strong["confidence"] > weak["confidence"]


def test_no_fake_price_history_claims():
    result = analyze_deal_verdict(_product())
    text = " ".join([
        result["summary"],
        *(reason["message"] for reason in result["reasons"]),
        *result["warnings"],
    ]).lower()
    forbidden = (
        "historical low",
        "best price ever",
        "guaranteed",
        "fake discount",
    )
    assert not any(phrase in text for phrase in forbidden)
    assert result["signals"]["priceHistoryAvailable"] is False


def test_response_shape_is_stable():
    result = analyze_deal_verdict(_product())
    assert set(result) == {
        "verdict",
        "label",
        "confidence",
        "riskLevel",
        "discountRiskScore",
        "discountRiskLabel",
        "summary",
        "reasons",
        "warnings",
        "actionHints",
        "signals",
        "generatedAt",
    }


@pytest.mark.parametrize(
    "product",
    [
        _product(),
        _product(newPrice=0, discount=999, qualityScore=-20),
        _product(discount=95, priceAccuracy="estimated", finalPriceInStore=True),
    ],
)
def test_scores_are_clamped(product):
    result = analyze_deal_verdict(product)
    assert 0 <= result["confidence"] <= 100
    assert 0 <= result["discountRiskScore"] <= 100


def test_route_returns_verdict_for_public_product(monkeypatch):
    async def fake_loader(product_id, market):
        assert product_id == "deal-1"
        assert market == "es"
        return _product()

    monkeypatch.setattr(product_routes, "_load_public_product", fake_loader)
    result = asyncio.run(
        product_routes.get_product_deal_verdict("deal-1", country="es")
    )
    assert result["verdict"] in {"buy_now", "check_store", "wait", "avoid"}
    assert 0 <= result["confidence"] <= 100


def test_route_does_not_leak_hidden_product_details(monkeypatch):
    async def fake_loader(product_id, market):
        return None

    monkeypatch.setattr(product_routes, "_load_public_product", fake_loader)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            product_routes.get_product_deal_verdict(
                "hidden-secret", country="es"
            )
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Product not found"
    assert "hidden-secret" not in str(exc.value.detail)
