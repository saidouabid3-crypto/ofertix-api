from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
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
    safe_stream,
)
from services.deal_verdict_service import analyze_deal_verdict
from services.public_catalog_policy import evaluate_public_product, load_catalog_config
from services.public_product_service import (
    is_usable_public_product,
    prepare_public_product,
    sanitize_public_product,
)
from services.smart_search_service import rank_search_results


class ProductSearchRequest(BaseModel):
    query: str = ""
    country: str = "es"
    category: str | None = None
    limit: int = 30
    # New optional fields (Batch 14B) — all backward-compatible
    store: str | None = None
    minPrice: float | None = None
    maxPrice: float | None = None
    minDiscount: int | None = None
    trustedOnly: bool = False
    sort: str = "smart"

router = APIRouter()


def _stream_products(read_limit: int) -> list[dict]:
    # The visibleToUsers FieldFilter requires a Firestore composite index.
    # If the index is absent Firestore raises FailedPrecondition; fall back to
    # a full-collection scan and filter in Python.
    # Quota/deadline errors propagate so callers get an honest 5xx (or stale
    # cache) rather than a silent empty list that looks like "no products".
    try:
        docs = safe_stream(
            db.collection("products").where(filter=FieldFilter("visibleToUsers", "==", True)),
            limit=read_limit,
            context="products_public",
        )
    except FailedPrecondition:
        docs = safe_stream(
            db.collection("products"),
            limit=read_limit,
            context="products_fallback",
        )
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in docs]


async def _load_public_product(product_id: str, market: str) -> dict | None:
    """Load one product through the same public preparation as Product Details."""
    config = await asyncio.to_thread(load_catalog_config)

    def _prepare(raw: dict) -> dict | None:
        item = prepare_public_product(raw, market)
        if not is_usable_public_product(item, market):
            return None
        if not evaluate_public_product(item, config).get("visible", False):
            return None
        return sanitize_public_product(item)

    try:
        doc = await asyncio.to_thread(
            db.collection("products").document(product_id).get
        )
        if doc.exists:
            raw = {"id": doc.id, **(doc.to_dict() or {})}
            return _prepare(raw)
    except Exception:
        pass

    raw_docs = await asyncio.to_thread(_stream_products, 800)
    for raw in raw_docs:
        if str(raw.get("id") or "") != product_id:
            continue
        return _prepare(raw)
    return None


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
    limit = min(limit, 40)  # read governor: cap display limit
    read_limit = min(max(limit * 6, 120), 300)  # cap Firestore reads
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
    market = normalize_market(country)
    item = await _load_public_product(product_id, market)
    if item is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "ok": True,
        "country": market,
        "currency": SUPPORTED_MARKETS[market]["currency"],
        "product": item,
        "sections": {},
        "aiVerdict": {},
        "dealDNA": {},
    }


@router.get("/api/products/{product_id}/deal-verdict")
async def get_product_deal_verdict(product_id: str, country: str = "es"):
    market = normalize_market(country)
    item = await _load_public_product(product_id, market)
    if item is None:
        # Hidden and missing products intentionally share the same response.
        raise HTTPException(status_code=404, detail="Product not found")
    return analyze_deal_verdict(item, market=market)


@router.post("/api/products/search")
async def search_products(payload: ProductSearchRequest):
    market = normalize_market(payload.country)
    q = payload.query.strip()
    wanted_category = (payload.category or "").strip().lower()
    wanted_store = (payload.store or "").strip().lower()
    limit = max(1, min(payload.limit, 40))  # read governor: cap display limit
    read_limit = min(max(limit * 6, 120), 300)  # cap Firestore reads
    sort_mode = payload.sort if payload.sort in (
        "smart", "discount_desc", "price_asc", "price_desc", "newest", "trusted"
    ) else "smart"

    key = catalog_cache.build_key(
        "search",
        country=market,
        q=q.lower() or None,
        category=wanted_category or None,
        store=wanted_store or None,
        min_price=round(payload.minPrice, 2) if payload.minPrice else None,
        max_price=round(payload.maxPrice, 2) if payload.maxPrice else None,
        min_discount=payload.minDiscount,
        trusted_only=payload.trustedOnly or None,
        sort=sort_mode if sort_mode != "smart" else None,
        limit=limit,
    )

    async def _load() -> dict:
        config, raw_docs = await asyncio.gather(
            asyncio.to_thread(load_catalog_config),
            asyncio.to_thread(_stream_products, read_limit),
        )

        # Build public candidate pool (same eligibility as /products)
        candidates: list[dict] = []
        seen_fp: set[str] = set()

        for raw in raw_docs:
            item = prepare_public_product(raw, market)
            if not is_usable_public_product(item, market):
                continue
            fp = (
                item.get("fingerprint")
                or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
            )
            if fp in seen_fp:
                continue
            seen_fp.add(fp)

            decision = evaluate_public_product(item, config)
            if not decision["visible"]:
                continue
            item["publicRankScore"] = decision["rankScore"]
            candidates.append(item)

        # Smart search ranking engine
        smart = rank_search_results(
            candidates,
            query=q,
            category=wanted_category,
            store=wanted_store,
            min_price=payload.minPrice,
            max_price=payload.maxPrice,
            min_discount=payload.minDiscount,
            trusted_only=payload.trustedOnly,
            sort_mode=sort_mode,
            limit=limit,
        )

        return {
            "country": market,
            "currency": SUPPORTED_MARKETS[market]["currency"],
            "count": len(smart["ranked_products"]),
            "products": smart["ranked_products"],
            # New enrichment fields (non-breaking for old Flutter clients)
            "suggestions": smart["suggestions"],
            "detectedIntent": smart["detectedIntent"],
            "filters": smart["filters"],
        }

    return await catalog_cache.get_or_load(
        key, _load, fresh_ttl=SEARCH_FRESH_TTL, stale_ttl=SEARCH_STALE_TTL
    )
