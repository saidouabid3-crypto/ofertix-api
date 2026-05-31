"""Barcode / QR product scan endpoints.

The Flutter ``ScanService`` posts ``{code, countryCode}`` to
``/api/scan/product`` and expects ``{query, products: [...]}`` back, with each
product shaped like the ``/products`` payload (so ``Product.fromMap`` decodes it
directly). This route reuses the exact same Firestore retrieval and
normalization pipeline as ``routes/products.py`` to guarantee that alignment,
then matches the scanned code against product identifiers and titles.

All failures return a localized error payload via ``core.api_errors`` so the
client can show a friendly message in the user's language.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.api_errors import localized_error_response
from core.firebase import db
from core.market_config import SUPPORTED_MARKETS, normalize_market
from schemas.scan_schema import ScanRequest, ScanResponse
from utils.market_filter import item_available_for_country, normalize_item_market_fields
from utils.product_standard import normalize_product

logger = logging.getLogger("ofertix.scan")

router = APIRouter(prefix="/api/scan", tags=["Scan"])

# Fields on a product document that may carry a scannable identifier.
_IDENTIFIER_FIELDS: tuple[str, ...] = (
    "barcode", "ean", "ean13", "gtin", "upc", "sku", "mpn", "code",
    "id", "fingerprint", "asin",
)

# Fields searched for a substring match (model numbers, names).
_TEXT_FIELDS: tuple[str, ...] = ("name", "title", "fullTitle", "brand", "model")


def _read_limit() -> int:
    return 600


def _usable(item: dict[str, Any], market: str) -> bool:
    status = str(item.get("status", "active")).lower()
    if status not in {"active", "approved", "published"}:
        return False
    if item.get("visibleToUsers") is False:
        return False
    if not item.get("image") and not item.get("mainImage"):
        return False
    if float(item.get("newPrice") or item.get("price") or 0) <= 0:
        return False
    if not item_available_for_country(item, market):
        return False
    return True


def _identifier_match(item: dict[str, Any], code: str) -> bool:
    code_lower = code.lower()
    for field in _IDENTIFIER_FIELDS:
        value = item.get(field)
        if value is None:
            continue
        if str(value).strip().lower() == code_lower:
            return True
    return False


def _text_match(item: dict[str, Any], code: str) -> bool:
    # Only attempt a text match for codes that look like model names rather than
    # pure numeric barcodes, to avoid spurious substring hits.
    if code.isdigit():
        return False
    code_lower = code.lower()
    for field in _TEXT_FIELDS:
        value = item.get(field)
        if value and code_lower in str(value).lower():
            return True
    return False


def _best_query(item: dict[str, Any]) -> str:
    brand = str(item.get("brand") or "").strip()
    name = str(item.get("name") or item.get("title") or item.get("fullTitle") or "").strip()
    query = f"{brand} {name}".strip()
    return query or name or brand


@router.get("/health")
async def scan_health() -> dict[str, str]:
    return {"status": "ok", "service": "ofertix-scan"}


@router.post("/product", response_model=ScanResponse)
async def scan_product(request: ScanRequest, http_request: Request) -> Any:
    code = request.code
    if not code:
        return localized_error_response(
            status_code=422,
            code="SCAN_EMPTY_CODE",
            message_id="scan_failed",
        )

    market = normalize_market(request.countryCode)
    currency = SUPPORTED_MARKETS.get(market, {}).get("currency", "EUR")

    if db is None:
        # No datastore configured: respond gracefully so the client falls back
        # to its own name search instead of crashing.
        return ScanResponse(
            code=code, query=code, country=market, currency=currency, count=0,
            products=[],
        )

    try:
        try:
            docs = (
                db.collection("products")
                .where("visibleToUsers", "==", True)
                .limit(_read_limit())
                .stream()
            )
        except Exception:  # noqa: BLE001 - composite index/permission fallback
            docs = db.collection("products").limit(_read_limit()).stream()

        identifier_hits: list[dict[str, Any]] = []
        text_hits: list[dict[str, Any]] = []
        seen: set[str] = set()

        for doc in docs:
            raw = doc.to_dict() or {}
            raw["id"] = doc.id
            item = normalize_product(
                normalize_item_market_fields(raw, fallback_country=market),
                fallback_country=market,
            )
            if not _usable(item, market):
                continue

            fingerprint = item.get("fingerprint") or (
                f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
            )
            if fingerprint in seen:
                continue

            if _identifier_match(raw, code) or _identifier_match(item, code):
                seen.add(fingerprint)
                identifier_hits.append(item)
            elif _text_match(item, code):
                seen.add(fingerprint)
                text_hits.append(item)

            if len(identifier_hits) >= 20:
                break

        matched = identifier_hits or text_hits
        query = _best_query(matched[0]) if matched else code

        return ScanResponse(
            code=code,
            query=query,
            country=market,
            currency=currency,
            count=len(matched),
            products=matched[:20],
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Scan lookup failed for code=%s: %s", code, exc)
        return localized_error_response(
            status_code=500,
            code="SCAN_LOOKUP_FAILED",
            message_id="scan_failed",
            detail=str(exc),
        )
