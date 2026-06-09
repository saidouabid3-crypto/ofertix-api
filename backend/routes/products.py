from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel

from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from services.catalog_edge_cache import (
    catalog_cache,
    HOME_FEED_FRESH_TTL, HOME_FEED_STALE_TTL,
    PRODUCTS_FRESH_TTL, PRODUCTS_STALE_TTL,
    SEARCH_FRESH_TTL, SEARCH_STALE_TTL,
)
from services.public_catalog_policy import evaluate_public_product, load_catalog_config
from services.public_product_service import (
    is_usable_public_product,
    prepare_public_product,
)


class ProductSearchRequest(BaseModel):
    query: str = ""
    country: str = "es"
    category: str | None = None
    limit: int = 30

router = APIRouter()


def _stream_products(read_limit: int) -> list[dict]:
    # The visibleToUsers FieldFilter requires a Firestore composite index.
    # If the index is absent Firestore raises FailedPrecondition; fall back to
    # a full-collection scan and filter in Python.
    # All other errors (quota, auth) propagate so callers get an honest 5xx
    # rather than a silent empty list that looks like "no products".
    try:
        docs = list(
            db.collection("products")
            .where(filter=FieldFilter("visibleToUsers", "==", True))
            .limit(read_limit)
            .stream()
        )
    except FailedPrecondition:
        docs = list(db.collection("products").limit(read_limit).stream())
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in docs]


def _build_products_response(
    raw_docs: list[dict],
    config: dict,
    market: str,
    limit: int,
    page: int,
    category: str,
    store: str,
) -> dict:
    """Process raw Firestore docs through public catalog pipeline."""
    candidates: list[dict] = []
    seen: set[str] = set()

    for raw in raw_docs:
        item = prepare_public_product(raw, market)
        if not is_usable_public_product(item, market):
            continue
        if category and category not in str(
            item.get("categoryGroup") or item.get("category") or ""
        ).lower():
            continue
        if store and store not in str(item.get("store") or item.get("source") or "").lower():
            continue
        fp = (
            item.get("fingerprint")
            or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
        )
        if fp in seen:
            continue
        seen.add(fp)

        decision = evaluate_public_product(item, config)
        if not decision["visible"]:
            continue
        item["publicRankScore"] = decision["rankScore"]
        candidates.append(item)

    if config.get("smartRankingEnabled", True):
        candidates.sort(key=lambda x: x.get("publicRankScore", 50), reverse=True)

    offset = (page - 1) * limit
    paginated = candidates[offset: offset + limit]

    return {
        "country": market,
        "currency": SUPPORTED_MARKETS[market]["currency"],
        "page": page,
        "limit": limit,
        "count": len(paginated),
        "hasMore": len(candidates) > offset + limit,
        "products": paginated,
    }


@router.get("/products")
async def get_products(
    country: str = "es",
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1, le=200),
    category: str | None = None,
    store: str | None = None,
):
    market = normalize_market(country)
    read_limit = min(max(limit * 6, 240), 1000)
    wanted_category = (category or "").strip().lower()
    wanted_store = (store or "").strip().lower()

    key = catalog_cache.build_key(
        "products",
        country=market,
        page=page,
        limit=limit,
        category=wanted_category or None,
        store=wanted_store or None,
    )

    async def _load() -> dict:
        config, raw_docs = await asyncio.gather(
            asyncio.to_thread(load_catalog_config),
            asyncio.to_thread(_stream_products, read_limit),
        )
        return _build_products_response(
            raw_docs, config, market, limit, page, wanted_category, wanted_store
        )

    return await catalog_cache.get_or_load(
        key, _load, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL
    )


@router.get("/product-detail/{product_id}")
async def get_product_detail(product_id: str, country: str = "es"):
    # Product detail reads a single document by ID — cheap and always fresh.
    market = normalize_market(country)

    try:
        doc = await asyncio.to_thread(db.collection("products").document(product_id).get)
        if doc.exists:
            raw = {"id": doc.id, **(doc.to_dict() or {})}
            item = prepare_public_product(raw, market)
            if is_usable_public_product(item, market):
                return {
                    "ok": True,
                    "country": market,
                    "currency": SUPPORTED_MARKETS[market]["currency"],
                    "product": item,
                    "sections": {},
                    "aiVerdict": {},
                    "dealDNA": {},
                }
    except Exception:
        pass

    raw_docs = await asyncio.to_thread(_stream_products, 800)
    for raw in raw_docs:
        if str(raw.get("id") or "") != product_id:
            continue
        item = prepare_public_product(raw, market)
        if not is_usable_public_product(item, market):
            break
        return {
            "ok": True,
            "country": market,
            "currency": SUPPORTED_MARKETS[market]["currency"],
            "product": item,
            "sections": {},
            "aiVerdict": {},
            "dealDNA": {},
        }

    return {"ok": False, "error": "Product not found", "productId": product_id}


@router.post("/api/products/search")
async def search_products(payload: ProductSearchRequest):
    market = normalize_market(payload.country)
    q = payload.query.strip().lower()
    wanted_category = (payload.category or "").strip().lower()
    limit = max(1, min(payload.limit, 200))
    read_limit = min(limit * 8, 800)

    key = catalog_cache.build_key(
        "search",
        country=market,
        q=q or None,
        category=wanted_category or None,
        limit=limit,
    )

    async def _load() -> dict:
        config, raw_docs = await asyncio.gather(
            asyncio.to_thread(load_catalog_config),
            asyncio.to_thread(_stream_products, read_limit),
        )

        results: list[dict] = []
        seen: set[str] = set()

        for raw in raw_docs:
            item = prepare_public_product(raw, market)
            if not is_usable_public_product(item, market):
                continue
            if wanted_category and wanted_category not in str(
                item.get("categoryGroup") or item.get("category") or ""
            ).lower():
                continue
            if q:
                haystack = " ".join(
                    str(item.get(k) or "")
                    for k in ("name", "fullTitle", "description", "category", "store")
                ).lower()
                if q not in haystack:
                    continue
            fp = (
                item.get("fingerprint")
                or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
            )
            if fp in seen:
                continue
            seen.add(fp)

            decision = evaluate_public_product(item, config)
            if not decision["visible"]:
                continue
            item["publicRankScore"] = decision["rankScore"]
            results.append(item)

        if config.get("smartRankingEnabled", True):
            results.sort(key=lambda x: x.get("publicRankScore", 50), reverse=True)

        return {
            "country": market,
            "currency": SUPPORTED_MARKETS[market]["currency"],
            "count": min(len(results), limit),
            "products": results[:limit],
        }

    return await catalog_cache.get_or_load(
        key, _load, fresh_ttl=SEARCH_FRESH_TTL, stale_ttl=SEARCH_STALE_TTL
    )
