from __future__ import annotations

import asyncio
import logging

from core.firebase import db

logger = logging.getLogger("ofertix.push")

_SUPPORTED_LANGS = {"en", "es", "ar", "fr"}

_TITLE: dict[str, str] = {
    "en": "Price drop alert",
    "es": "Alerta de bajada de precio",
    "ar": "تنبيه انخفاض السعر",
    "fr": "Alerte baisse de prix",
}

_BODY: dict[str, str] = {
    "en": "{name} dropped to {new:.2f} {currency}",
    "es": "{name} bajó a {new:.2f} {currency}",
    "ar": "انخفض سعر {name} إلى {new:.2f} {currency}",
    "fr": "{name} est passé à {new:.2f} {currency}",
}

_MESSAGE_TITLE: dict[str, str] = {
    "en": "New message",
    "es": "Nuevo mensaje",
    "ar": "رسالة جديدة",
    "fr": "Nouveau message",
}

_MESSAGE_BODY: dict[str, str] = {
    "en": "{sender}: new message about {listing}",
    "es": "{sender}: nuevo mensaje sobre {listing}",
    "ar": "{sender}: رسالة جديدة بخصوص {listing}",
    "fr": "{sender} : nouveau message concernant {listing}",
}

_OFFER_TITLE: dict[str, str] = {
    "en": "New offer",
    "es": "Nueva oferta",
    "ar": "عرض جديد",
    "fr": "Nouvelle offre",
}

_OFFER_BODY: dict[str, str] = {
    "en": "{sender} made an offer on {listing}",
    "es": "{sender} hizo una oferta por {listing}",
    "ar": "قدّم {sender} عرضًا على {listing}",
    "fr": "{sender} a fait une offre sur {listing}",
}

_REEL_MESSAGE_BODY: dict[str, str] = {
    "en": "{sender}: new message about your reel",
    "es": "{sender}: nuevo mensaje sobre tu Reel",
    "ar": "{sender}: رسالة جديدة بخصوص Reel",
    "fr": "{sender} : nouveau message concernant votre reel",
}

_DIRECT_MESSAGE_BODY: dict[str, str] = {
    "en": "{sender}: new message",
    "es": "{sender}: nuevo mensaje",
    "ar": "{sender}: رسالة جديدة",
    "fr": "{sender} : nouveau message",
}


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
        try:
            user_ids = await asyncio.to_thread(self._collect_interested_users, product_id)
        except Exception as exc:
            logger.warning("notify_price_drop: failed to collect users: %s", exc)
            return 0

        if not user_ids:
            return 0

        sent = 0
        for uid in user_ids:
            try:
                profile = await asyncio.to_thread(self._user_profile, uid)
            except Exception as exc:
                logger.debug("notify_price_drop: could not read profile: %s", exc)
                continue

            lang = profile["language"]
            tokens = profile["tokens"]
            if not tokens:
                continue

            title = _TITLE.get(lang, _TITLE["en"])
            body = _BODY.get(lang, _BODY["en"]).format(
                name=product_name,
                new=new_price,
                currency=currency,
            )
            data = {
                "type": "price_drop",
                "productId": product_id,
                "oldPrice": str(old_price),
                "newPrice": str(new_price),
                "currency": currency,
            }

            for token in tokens:
                ok = await asyncio.to_thread(self._send_fcm, token, title, body, data)
                if ok:
                    sent += 1

        return sent

    def notify_new_message_sync(
        self,
        *,
        receiver_id: str,
        sender_name: str,
        listing_title: str,
        conversation_id: str,
        is_offer: bool = False,
        conversation_type: str = "marketplace",
    ) -> str:
        """Send a marketplace message/offer push synchronously.

        Never raises — failures are swallowed and reported via the return
        status so the calling message-send flow is never blocked.
        """
        receiver_id = str(receiver_id or "").strip()
        if not receiver_id:
            return "skipped"
        try:
            profile = self._user_profile(receiver_id)
        except Exception as exc:
            logger.warning("notify_new_message: profile lookup failed: %s", exc)
            return "failed"

        tokens = profile["tokens"]
        if not tokens:
            return "skipped"

        lang = profile["language"]
        sender_name = (sender_name or "User").strip()[:60]
        listing_title = (listing_title or "").strip()[:80]

        if is_offer:
            title = _OFFER_TITLE.get(lang, _OFFER_TITLE["en"])
            body = _OFFER_BODY.get(lang, _OFFER_BODY["en"]).format(
                sender=sender_name, listing=listing_title or "your listing"
            )
            msg_type = "marketplace_offer"
        elif conversation_type == "reel":
            title = _MESSAGE_TITLE.get(lang, _MESSAGE_TITLE["en"])
            body = _REEL_MESSAGE_BODY.get(lang, _REEL_MESSAGE_BODY["en"]).format(
                sender=sender_name
            )
            msg_type = "reel_message"
        elif conversation_type == "direct":
            title = _MESSAGE_TITLE.get(lang, _MESSAGE_TITLE["en"])
            body = _DIRECT_MESSAGE_BODY.get(lang, _DIRECT_MESSAGE_BODY["en"]).format(
                sender=sender_name
            )
            msg_type = "profile_message"
        else:
            title = _MESSAGE_TITLE.get(lang, _MESSAGE_TITLE["en"])
            body = _MESSAGE_BODY.get(lang, _MESSAGE_BODY["en"]).format(
                sender=sender_name, listing=listing_title or "your listing"
            )
            msg_type = "marketplace_message"

        data = {
            "type": msg_type,
            "conversationId": conversation_id,
        }

        sent_any = False
        for token in tokens:
            try:
                if self._send_fcm(token, title, body, data):
                    sent_any = True
            except Exception as exc:
                logger.debug("notify_new_message: send failed: %s", type(exc).__name__)

        status = "sent" if sent_any else "failed"
        logger.info(
            "[OfertixMessages] notify receiver=%s type=%s status=%s",
            receiver_id, msg_type, status,
        )
        return status

    def _collect_interested_users(self, product_id: str) -> set[str]:
        users: set[str] = set()
        for collection, field in (
            ("favorites", "productId"),
            ("watchlist", "productId"),
            ("price_alerts", "productId"),
        ):
            try:
                docs = (
                    db.collection(collection)
                    .where(field, "==", product_id)
                    .limit(200)
                    .stream()
                )
                for doc in docs:
                    d = doc.to_dict() or {}
                    uid = d.get("userId") or d.get("uid")
                    if uid:
                        users.add(str(uid))
            except Exception:
                continue
        return users

    def _user_profile(self, uid: str) -> dict:
        tokens: list[str] = []
        language = "en"
        try:
            doc = db.collection("users").document(uid).get()
            if not doc.exists:
                return {"tokens": tokens, "language": language}
            data = doc.to_dict() or {}

            raw_lang = (
                data.get("language")
                or data.get("preferredLanguage")
                or data.get("locale")
                or "en"
            )
            code = str(raw_lang).strip().lower()[:2]
            language = code if code in _SUPPORTED_LANGS else "en"

            single = data.get("fcmToken")
            if single and isinstance(single, str) and single.strip():
                tokens.append(single.strip())
            for entry in data.get("fcmTokens") or []:
                if entry and isinstance(entry, str) and entry.strip():
                    tokens.append(entry.strip())
        except Exception as exc:
            logger.debug("Could not read user profile: %s", exc)
        return {"tokens": list(dict.fromkeys(tokens)), "language": language}

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
            logger.debug("FCM send failed: %s", type(exc).__name__)
            return False


push_notification_service = PushNotificationService()
