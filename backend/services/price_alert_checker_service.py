from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from core.firebase import db
from services.push_notification_service import push_notification_service

logger = logging.getLogger("ofertix.price_alert_checker")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PriceAlertCheckerService:
    """
    Checks Firestore price_alerts against the latest product prices.

    Design rules:
    - Only triggers when latestPrice <= targetPrice (real comparison).
    - Errors on individual alerts are caught and logged; the batch continues.
    - No fake successes. If price cannot be resolved, the alert is skipped.
    - Updates lastCheckedAt on every processed alert so callers can see
      activity without needing to trigger.
    """

    async def run(self) -> dict[str, int]:
        """
        Runs one full pass over all active, non-triggered price alerts.

        Returns a summary dict: {checked, triggered, skipped, errors}
        """
        checked = triggered = skipped = errors = 0

        try:
            docs = await asyncio.to_thread(self._fetch_active_alerts)
        except Exception as exc:
            logger.error("Failed to fetch active alerts: %s", exc)
            return {"checked": 0, "triggered": 0, "skipped": 0, "errors": 1}

        logger.info("Price alert checker: %d active alert(s) to process", len(docs))

        for doc in docs:
            checked += 1
            try:
                outcome = await self._process_alert(doc)
                if outcome == "triggered":
                    triggered += 1
                elif outcome == "skipped":
                    skipped += 1
            except Exception as exc:
                errors += 1
                logger.warning("Alert %s failed unexpectedly: %s", doc.id, exc)
                self._safe_update(
                    doc,
                    {"lastError": str(exc)[:200], "lastCheckedAt": _now_iso()},
                )

        logger.info(
            "Price alert check done — checked=%d triggered=%d skipped=%d errors=%d",
            checked,
            triggered,
            skipped,
            errors,
        )
        return {
            "checked": checked,
            "triggered": triggered,
            "skipped": skipped,
            "errors": errors,
        }

    # ── Firestore helpers ──────────────────────────────────────────────────────

    def _fetch_active_alerts(self) -> list:
        return list(
            db.collection("price_alerts")
            .where("active", "==", True)
            .where("triggered", "==", False)
            .stream()
        )

    def _safe_update(self, doc: Any, payload: dict) -> None:
        try:
            doc.reference.update(payload)
        except Exception as exc:
            logger.debug("Could not update alert %s: %s", doc.id, exc)

    # ── Per-alert processing ───────────────────────────────────────────────────

    async def _process_alert(self, doc: Any) -> str:
        """Returns 'triggered', 'skipped', or 'no_change'."""
        data: dict[str, Any] = doc.to_dict() or {}

        product_id = str(data.get("productId") or "").strip()
        target_price = self._to_float(data.get("targetPrice"))
        stored_price = self._to_float(
            data.get("currentPrice") or data.get("newPrice")
        )
        currency = str(data.get("currency") or "EUR").strip()
        product_name = str(
            data.get("productName") or data.get("name") or product_id
        ).strip()
        user_id = str(data.get("userId") or "").strip()

        # Validation — skip malformed alerts rather than crashing.
        if not product_id or target_price is None or target_price <= 0:
            await asyncio.to_thread(
                self._safe_update,
                doc,
                {
                    "lastError": "missing or invalid productId/targetPrice",
                    "lastCheckedAt": _now_iso(),
                },
            )
            return "skipped"

        # Resolve the latest price.
        latest_price = await self._resolve_latest_price(product_id, stored_price)

        if latest_price is None:
            await asyncio.to_thread(
                self._safe_update,
                doc,
                {
                    "lastError": "could not resolve product price",
                    "lastCheckedAt": _now_iso(),
                },
            )
            return "skipped"

        base_update: dict[str, Any] = {
            "lastCheckedAt": _now_iso(),
            "latestPrice": latest_price,
        }

        if latest_price <= target_price:
            # ── Condition met: trigger ─────────────────────────────────────
            base_update.update(
                {
                    "triggered": True,
                    "active": False,
                    "triggeredAt": _now_iso(),
                    "updatedAt": _now_iso(),
                }
            )
            await asyncio.to_thread(self._safe_update, doc, base_update)

            # Send push notification (FCM) + store Firestore notification record.
            await push_notification_service.notify_price_drop(
                product_id=product_id,
                product_name=product_name,
                old_price=stored_price or latest_price,
                new_price=latest_price,
                currency=currency,
            )

            # Write a targeted notification record for the alert owner so
            # the Flutter NotificationsScreen can show it even without FCM.
            await self._write_notification_record(
                user_id=user_id,
                data=data,
                latest_price=latest_price,
                currency=currency,
            )

            logger.info(
                "Alert %s triggered — product=%s latestPrice=%.2f targetPrice=%.2f %s",
                doc.id,
                product_id,
                latest_price,
                target_price,
                currency,
            )
            return "triggered"

        # ── Condition not met: update tracking fields only ─────────────────
        await asyncio.to_thread(self._safe_update, doc, base_update)
        return "no_change"

    # ── Price resolution ───────────────────────────────────────────────────────

    async def _resolve_latest_price(
        self, product_id: str, fallback: float | None
    ) -> float | None:
        """
        Attempts to fetch the live price from the products collection.

        Strategy:
          1. Direct document lookup by product_id (fastest).
          2. Field query (products where id == product_id) if #1 misses.
          3. Falls back to the price stored on the alert document.
        """
        # Strategy 1: document lookup.
        try:
            doc = await asyncio.to_thread(
                db.collection("products").document(product_id).get
            )
            if doc.exists:
                price = self._price_from_doc(doc.to_dict() or {})
                if price is not None:
                    return price
        except Exception as exc:
            logger.debug("Direct product fetch failed for %s: %s", product_id, exc)

        # Strategy 2: field query.
        try:
            results = await asyncio.to_thread(
                lambda: list(
                    db.collection("products")
                    .where("id", "==", product_id)
                    .limit(1)
                    .stream()
                )
            )
            if results:
                price = self._price_from_doc(results[0].to_dict() or {})
                if price is not None:
                    return price
        except Exception as exc:
            logger.debug("Product field query failed for %s: %s", product_id, exc)

        # Strategy 3: fall back to stored price on the alert.
        return fallback

    @staticmethod
    def _price_from_doc(data: dict[str, Any]) -> float | None:
        for key in ("newPrice", "price", "currentPrice", "sale_price"):
            value = PriceAlertCheckerService._to_float(data.get(key))
            if value is not None:
                return value
        return None

    # ── Notification record ────────────────────────────────────────────────────

    async def _write_notification_record(
        self,
        *,
        user_id: str,
        data: dict[str, Any],
        latest_price: float,
        currency: str,
    ) -> None:
        """
        Writes a Firestore notifications record so Flutter can display it
        even if FCM delivery is not yet wired for this user.
        """
        if not user_id:
            return

        product_name = str(data.get("productName") or data.get("name") or "")
        target_price = self._to_float(data.get("targetPrice")) or 0.0
        product_id = str(data.get("productId") or "")

        record: dict[str, Any] = {
            "userId": user_id,
            "type": "price_drop",
            "title": f"Price drop: {product_name}" if product_name else "Price drop alert",
            "body": (
                f"{product_name} dropped to {latest_price:.2f} {currency}"
                f" (your target: {target_price:.2f})"
            ),
            "productId": product_id,
            "productName": product_name,
            "currentPrice": latest_price,
            "targetPrice": target_price,
            "currency": currency,
            "productImage": str(data.get("productImage") or data.get("image") or ""),
            "affiliateUrl": str(data.get("affiliateUrl") or ""),
            "source": "price_alert_checker",
            "read": False,
            "createdAt": _now_iso(),
        }
        try:
            await asyncio.to_thread(db.collection("notifications").add, record)
        except Exception as exc:
            logger.debug(
                "Could not write notification record for user %s: %s", user_id, exc
            )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            f = float(value)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None


price_alert_checker_service = PriceAlertCheckerService()
