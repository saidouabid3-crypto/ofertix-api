from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from core.firebase import db

logger = logging.getLogger("ofertix.push")


class PushNotificationService:
    async def notify_price_drop(
        self,
        *,
        product_id: str,
        product_name: str,
        old_price: float,
        new_price: float,
        currency: str,
    ) -> int:
        """Notify users who favorited or watchlisted this product."""

        user_ids = await asyncio.to_thread(self._collect_interested_users, product_id)
        if not user_ids:
            return 0

        title = "Price drop alert"
        body = f"{product_name}: {old_price:.2f} → {new_price:.2f} {currency}"

        sent = 0
        for uid in user_ids:
            tokens = await asyncio.to_thread(self._tokens_for_user, uid)
            for token in tokens:
                ok = await asyncio.to_thread(
                    self._send_fcm,
                    token,
                    title,
                    body,
                    {
                        "type": "price_drop",
                        "productId": product_id,
                        "oldPrice": str(old_price),
                        "newPrice": str(new_price),
                        "currency": currency,
                    },
                )
                if ok:
                    sent += 1

        await asyncio.to_thread(
            self._store_notification_records,
            user_ids,
            product_id,
            title,
            body,
        )
        return sent

    def _collect_interested_users(self, product_id: str) -> set[str]:
        users: set[str] = set()
        for collection, field in (
            ("favorites", "productId"),
            ("watchlist", "productId"),
            ("price_alerts", "productId"),
        ):
            try:
                docs = db.collection(collection).where(field, "==", product_id).limit(200).stream()
                for doc in docs:
                    data = doc.to_dict() or {}
                    uid = data.get("userId") or data.get("uid")
                    if uid:
                        users.add(str(uid))
            except Exception:
                continue
        return users

    def _tokens_for_user(self, uid: str) -> list[str]:
        tokens: list[str] = []
        try:
            doc = db.collection("users").document(uid).get()
            if not doc.exists:
                return tokens
            data = doc.to_dict() or {}
            single = data.get("fcmToken") or data.get("deviceToken")
            if single:
                tokens.append(str(single))
            for entry in data.get("fcmTokens") or []:
                if entry:
                    tokens.append(str(entry))
        except Exception:
            return []
        return list(dict.fromkeys(tokens))

    def _send_fcm(self, token: str, title: str, body: str, data: dict[str, str]) -> bool:
        try:
            from firebase_admin import messaging

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data,
                token=token,
            )
            messaging.send(message)
            return True
        except Exception as exc:
            logger.debug("FCM send skipped/failed: %s", exc)
            return False

    def _store_notification_records(
        self,
        user_ids: set[str],
        product_id: str,
        title: str,
        body: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for uid in user_ids:
            try:
                db.collection("notifications").add(
                    {
                        "userId": uid,
                        "productId": product_id,
                        "title": title,
                        "body": body,
                        "type": "price_drop",
                        "read": False,
                        "createdAt": now,
                    }
                )
            except Exception:
                continue


push_notification_service = PushNotificationService()
