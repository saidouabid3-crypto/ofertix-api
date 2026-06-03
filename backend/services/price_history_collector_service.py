from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.firebase import db

logger = logging.getLogger("ofertix.price_history")


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


class PriceHistoryCollectorService:
    """
    Records real product price snapshots to the Firestore price_history collection.

    Dedupe strategy: deterministic document ID encodes (productId, calendar-day, price).
    Writing the same product/price/day is idempotent (merge=True updates in place).
    A price change on the same day produces a new document ID automatically.

    Never invents prices. Returns a result dict — never raises.
    """

    def record(
        self,
        *,
        product_id: str,
        data: dict[str, Any],
        reason: str = "product_sync",
    ) -> dict[str, Any]:
        """
        Write one price history snapshot.

        Args:
            product_id: Firestore document id of the product.
            data:        Product fields dict (merged patch + original data OK).
            reason:      Label stored on the history doc ("product_sync", "backfill", …).

        Returns:
            {"recorded": bool, "skipped": bool, "reason": str,
             "productId": str, "price": float}
        """
        pid = str(product_id or data.get("id") or "").strip()
        if not pid:
            return {
                "recorded": False, "skipped": True,
                "reason": "missing_product_id", "productId": "", "price": 0.0,
            }

        price = _parse_price(
            data.get("newPrice") or data.get("price") or data.get("currentPrice")
        )
        if price <= 0:
            return {
                "recorded": False, "skipped": True,
                "reason": "invalid_price", "productId": pid, "price": price,
            }

        now = datetime.now(timezone.utc)
        day_key = now.strftime("%Y%m%d")
        price_cents = round(price * 100)
        # One document per (product, day, price) — changing price same day → new doc.
        doc_id = f"ph_{pid}_{day_key}_{price_cents}"

        old_price = _parse_price(data.get("oldPrice") or data.get("previousPrice"))
        now_iso = now.isoformat()

        doc = {
            "productId": pid,
            "price": price,
            "currency": str(data.get("currency") or "EUR").strip(),
            "name": str(data.get("name") or data.get("fullTitle") or data.get("title") or "")[:200],
            "store": str(data.get("store") or data.get("source") or ""),
            "source": str(data.get("source") or ""),
            "country": str(data.get("country") or data.get("countryCode") or "global"),
            "countryCode": str(data.get("countryCode") or data.get("country") or "global"),
            "productUrl": str(data.get("productUrl") or data.get("affiliateUrl") or ""),
            "affiliateUrl": str(data.get("affiliateUrl") or data.get("productUrl") or ""),
            "image": str(data.get("image") or data.get("mainImage") or ""),
            # Both field names for Flutter compatibility (Batch 10B: createdAt Timestamp fix)
            "createdAt": now_iso,
            "date": now_iso,
            "dayKey": day_key,
            "reason": reason,
        }
        if old_price > 0:
            doc["oldPrice"] = old_price

        try:
            db.collection("price_history").document(doc_id).set(doc, merge=True)
            logger.debug(
                "Price history recorded: %s price=%.2f %s day=%s",
                pid, price, doc["currency"], day_key,
            )
            return {"recorded": True, "skipped": False, "reason": reason,
                    "productId": pid, "price": price}
        except Exception as exc:
            logger.warning("Price history write failed for %s: %s", pid, exc)
            return {"recorded": False, "skipped": False, "reason": str(exc),
                    "productId": pid, "price": price}


price_history_collector_service = PriceHistoryCollectorService()
