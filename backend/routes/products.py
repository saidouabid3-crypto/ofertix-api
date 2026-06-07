from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from services.public_catalog_policy import evaluate_public_product, load_catalog_config
from utils.market_filter import item_available_for_country, normalize_item_market_fields
from utils.product_standard import normalize_product


class ProductSearchRequest(BaseModel):
    query: str = ""
    country: str = "es"
    category: str | None = None
    limit: int = 30

router = APIRouter()


def _is_blocked_store(item: dict) -> bool:
    source = str(item.get("source") or "").strip().lower()
    store = str(item.get("store") or "").strip().lower()
    return source == "aliexpress" or "aliexpress" in store or store.startswith("ae-")


def _usable(item: dict, market: str) -> bool:
    if _is_blocked_store(item):
        return False
    if item.get("isExpired") is True:
        return False
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
    if str(item.get("categoryGroup") or item.get("category")).lower() == "kitchen":
        hay = f"{item.get('name', '')} {item.get('description', '')}".lower()
        negatives = ["shoe", "sneaker", "ring", "jewelry", "earring", "necklace", "watch", "phone", "dress", "pants", "bag"]
        if any(n in hay for n in negatives):
            return False
    return True


def _stream_products(read_limit: int) -> list[dict]:
    try:
        docs = db.collection("products").where("visibleToUsers", "==", True).limit(read_limit).stream()
    except Exception:
        docs = db.collection("products").limit(read_limit).stream()
    return [{"id": doc.id, **(doc.to_dict() or {})} for doc in docs]


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
    offset_to_skip = (page - 1) * limit

    config, raw_docs = await asyncio.gather(
        asyncio.to_thread(load_catalog_config),
        asyncio.to_thread(_stream_products, read_limit),
    )

    candidates: list[dict] = []
    seen: set[str] = set()
    wanted_category = (category or "").strip().lower()
    wanted_store = (store or "").strip().lower()

    for raw in raw_docs:
        item = normalize_product(
            normalize_item_market_fields(raw, fallback_country=market),
            fallback_country=market,
        )
        if not _usable(item, market):
            continue
        if wanted_category and wanted_category not in str(item.get("categoryGroup") or item.get("category") or "").lower():
            continue
        if wanted_store and wanted_store not in str(item.get("store") or item.get("source") or "").lower():
            continue
        fp = item.get("fingerprint") or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
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

    paginated = candidates[offset_to_skip: offset_to_skip + limit]

    return {
        "country": market,
        "currency": SUPPORTED_MARKETS[market]["currency"],
        "page": page,
        "limit": limit,
        "count": len(paginated),
        "hasMore": len(candidates) > offset_to_skip + limit,
        "products": paginated,
    }


@router.get("/product-detail/{product_id}")
async def get_product_detail(product_id: str, country: str = "es"):
    # Product detail is always accessible — trust section in UI explains the state.
    market = normalize_market(country)

    try:
        doc = await asyncio.to_thread(db.collection("products").document(product_id).get)
        if doc.exists:
            raw = {"id": doc.id, **(doc.to_dict() or {})}
            item = normalize_product(
                normalize_item_market_fields(raw, fallback_country=market),
                fallback_country=market,
            )
            if _usable(item, market):
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
        item = normalize_product(
            normalize_item_market_fields(raw, fallback_country=market),
            fallback_country=market,
        )
        if not _usable(item, market):
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

    config, raw_docs = await asyncio.gather(
        asyncio.to_thread(load_catalog_config),
        asyncio.to_thread(_stream_products, read_limit),
    )

    results: list[dict] = []
    seen: set[str] = set()

    for raw in raw_docs:
        item = normalize_product(
            normalize_item_market_fields(raw, fallback_country=market),
            fallback_country=market,
        )
        if not _usable(item, market):
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
        fp = item.get("fingerprint") or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
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
