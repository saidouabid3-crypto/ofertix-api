from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable

import firebase_admin

from core.firebase import db
from services.public_catalog_policy import evaluate_public_product, load_catalog_config
from services.public_product_service import (
    prepare_public_product,
    public_product_exclusion_reason,
)


SAMPLE_LIMIT = 5
POLICY_LIMIT = 100
ROUTE_SIMULATION_LIMIT = 20
MARKETS = ("es", "fr", "us")


def _label(value: Any) -> str:
    if value is None:
        return "(missing)"
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value).strip()
    return text or "(empty)"


def _count_scalar(products: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(_label(product.get(key)) for product in products)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _count_list(products: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for product in products:
        value = product.get(key)
        if isinstance(value, list):
            entries = value or ["(empty)"]
        elif isinstance(value, str):
            entries = [part.strip() for part in value.split(",") if part.strip()]
            entries = entries or ["(empty)"]
        elif value is None:
            entries = ["(missing)"]
        else:
            entries = [_label(value)]
        counts.update(_label(entry) for entry in entries)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _has_offer_link(product: dict[str, Any]) -> bool:
    return bool(
        str(
            product.get("affiliateUrl")
            or product.get("productUrl")
            or product.get("url")
            or ""
        ).strip()
    )


def _safe_sample(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": product.get("id"),
        "name": str(product.get("name") or product.get("fullTitle") or "")[:100],
        "status": product.get("status"),
        "countryCode": product.get("countryCode"),
        "country": product.get("country"),
        "availableCountries": product.get("availableCountries"),
        "visibleToUsers": product.get("visibleToUsers"),
        "publicVisible": product.get("publicVisible"),
        "admissionStatus": product.get("admissionStatus"),
        "trustStatus": product.get("trustStatus"),
        "newPrice": product.get("newPrice"),
        "currency": product.get("currency"),
        "hasOfferLink": _has_offer_link(product),
        "importBatchId": product.get("importBatchId"),
    }


def _project_id() -> str | None:
    try:
        return firebase_admin.get_app().project_id
    except Exception:
        return None


def build_report(products: list[dict[str, Any]]) -> dict[str, Any]:
    config = load_catalog_config()
    policy_sample = products[:POLICY_LIMIT]
    policy_visible = 0
    hidden_reasons: Counter[str] = Counter()
    ranks: list[float] = []

    for product in policy_sample:
        decision = evaluate_public_product(product, config)
        ranks.append(float(decision.get("rankScore") or 0))
        if decision.get("visible"):
            policy_visible += 1
        else:
            hidden_reasons[str(decision.get("hiddenReason") or "unknown")] += 1

    route_products = [
        product for product in products if product.get("visibleToUsers") is True
    ][:ROUTE_SIMULATION_LIMIT]
    route_simulation: dict[str, Any] = {}
    for market in MARKETS:
        reasons: Counter[str] = Counter()
        visible = 0
        for raw in route_products:
            normalized = prepare_public_product(raw, market)
            reason = public_product_exclusion_reason(normalized, market)
            if reason:
                reasons[reason] += 1
            else:
                visible += 1
        route_simulation[market] = {
            "scanned": len(route_products),
            "passesPrePolicyRouteGates": visible,
            "excludedByReason": dict(reasons.most_common()),
        }

    return {
        "firebaseProjectId": _project_id(),
        "productTotal": len(products),
        "counts": {
            "status": _count_scalar(products, "status"),
            "countryCode": _count_scalar(products, "countryCode"),
            "country": _count_scalar(products, "country"),
            "availableCountries": _count_list(products, "availableCountries"),
            "visibleToUsers": _count_scalar(products, "visibleToUsers"),
            "publicVisible": _count_scalar(products, "publicVisible"),
            "admissionStatus": _count_scalar(products, "admissionStatus"),
            "trustStatus": _count_scalar(products, "trustStatus"),
            "priceConfidence": _count_scalar(products, "priceConfidence"),
            "sourceKey": _count_scalar(products, "sourceKey"),
        },
        "sampleProducts": [_safe_sample(product) for product in products[:SAMPLE_LIMIT]],
        "catalogGovernanceConfig": config,
        "publicPolicySimulation": {
            "scanned": len(policy_sample),
            "visible": policy_visible,
            "hidden": len(policy_sample) - policy_visible,
            "hiddenReasons": dict(hidden_reasons.most_common()),
            "rankMin": min(ranks) if ranks else None,
            "rankMax": max(ranks) if ranks else None,
        },
        "publicRoutePrePolicySimulation": route_simulation,
    }


def main() -> None:
    if db is None:
        raise RuntimeError("Firestore is not configured for this environment")

    products = [
        {"id": doc.id, **(doc.to_dict() or {})}
        for doc in db.collection("products").stream()
    ]
    print(json.dumps(build_report(products), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
