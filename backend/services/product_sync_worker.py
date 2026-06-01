from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from core.firebase import db
from core.image_validator import filter_valid_images
from services.push_notification_service import push_notification_service
from utils.product_standard import normalize_product

logger = logging.getLogger("ofertix.sync")

SIGNIFICANT_DROP_PCT = float(os.getenv("PRICE_DROP_ALERT_PCT", "8"))
BATCH_LIMIT = int(os.getenv("SYNC_PRODUCT_BATCH_LIMIT", "250"))


def _parse_price(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).replace("€", "").replace("$", "").replace(",", ".").strip()
        return float(raw)
    except Exception:
        return 0.0


async def _verify_product_url(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.head(url)
            if response.status_code >= 400:
                response = await client.get(url)
            return response.status_code < 400
    except Exception:
        return False


async def _sync_single_product(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    product_url = str(
        data.get("affiliateUrl")
        or data.get("productUrl")
        or data.get("url")
        or ""
    ).strip()

    previous_price = _parse_price(data.get("newPrice") or data.get("price"))
    alive = await _verify_product_url(product_url) if product_url else True

    update: dict[str, Any] = {
        "lastSyncedAt": datetime.now(timezone.utc).isoformat(),
    }

    if not alive:
        update["isExpired"] = True
        update["status"] = "expired"
        update["visibleToUsers"] = False
        return update

    update["isExpired"] = False

    images = await filter_valid_images(
        [
            data.get("mainImage"),
            data.get("image"),
            *(data.get("images") or []),
            *(data.get("imageUrls") or []),
        ]
    )
    if images:
        update["images"] = images
        update["mainImage"] = images[0]
        update["image"] = images[0]

    live_price = _parse_price(data.get("livePrice") or data.get("scrapedPrice"))
    if live_price > 0:
        update["newPrice"] = live_price
        if previous_price > 0 and live_price < previous_price:
            drop_pct = ((previous_price - live_price) / previous_price) * 100.0
            update["previousPrice"] = previous_price
            update["priceDropPercent"] = round(drop_pct, 2)
            if drop_pct >= SIGNIFICANT_DROP_PCT:
                await push_notification_service.notify_price_drop(
                    product_id=doc_id,
                    product_name=str(data.get("name") or data.get("title") or "Product"),
                    old_price=previous_price,
                    new_price=live_price,
                    currency=str(data.get("currency") or "EUR"),
                )

    normalized = normalize_product({**data, **update}, fallback_country=str(data.get("countryCode") or "es"))
    update.update(
        {
            "category": normalized.get("category"),
            "categoryGroup": normalized.get("categoryGroup"),
            "newPrice": normalized.get("newPrice", previous_price),
            "images": normalized.get("images", images),
            "mainImage": normalized.get("mainImage"),
            "image": normalized.get("image"),
        }
    )
    return update


async def run_product_sync_batch() -> dict[str, int]:
    logger.info("Starting product sync batch (limit=%s)", BATCH_LIMIT)

    try:
        docs = list(
            db.collection("products")
            .where("visibleToUsers", "==", True)
            .limit(BATCH_LIMIT)
            .stream()
        )
    except Exception:
        docs = list(db.collection("products").limit(BATCH_LIMIT).stream())

    updated = 0
    expired = 0
    failed = 0

    for doc in docs:
        data = doc.to_dict() or {}
        try:
            patch = await _sync_single_product(doc.id, data)
            doc.reference.update(patch)
            updated += 1
            if patch.get("isExpired"):
                expired += 1
        except Exception as exc:
            failed += 1
            logger.warning("Sync failed for %s: %s", doc.id, exc)

    summary = {"updated": updated, "expired": expired, "failed": failed, "scanned": len(docs)}
    logger.info("Product sync finished: %s", summary)

    try:
        db.collection("system_jobs").document("product_sync").set(
            {
                "lastRunAt": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
            },
            merge=True,
        )
    except Exception:
        pass

    return summary


def run_product_sync_batch_sync() -> dict[str, int]:
    return asyncio.run(run_product_sync_batch())
