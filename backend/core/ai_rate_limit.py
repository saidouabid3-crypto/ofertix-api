from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header, HTTPException, Request

from core.api_errors import localized_error_response
from core.firebase import db
from core.redis_client import redis_client

FREE_AI_DAILY_LIMIT = int(os.getenv("AI_FREE_DAILY_LIMIT", "20"))


def _utc_day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _quota_key(subject: str) -> str:
    return f"ai:quota:{subject}:{_utc_day_key()}"


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((tomorrow - now).total_seconds()), 60)


def _is_premium_user(uid: str | None) -> bool:
    if not uid or db is None:
        return False
    try:
        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            return False
        data = doc.to_dict() or {}
        if data.get("premium") is True or data.get("isPremium") is True:
            return True
        role = str(data.get("role") or "").lower().strip()
        return role in {"premium", "admin", "owner", "super_admin"}
    except Exception:
        return False


def resolve_ai_subject(
    *,
    authorization: str | None,
    x_device_id: str | None,
    request: Request,
) -> tuple[str, str | None]:
    uid: str | None = None
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            try:
                from firebase_admin import auth as firebase_auth

                decoded = firebase_auth.verify_id_token(parts[1].strip())
                uid = decoded.get("uid")
            except Exception:
                uid = None

    if uid:
        return f"uid:{uid}", uid

    device = (x_device_id or "").strip()
    if device:
        return f"device:{device[:128]}", None

    client = request.client.host if request.client else "unknown"
    return f"ip:{client}", None


async def enforce_ai_rate_limit(
    request: Request,
    authorization: str | None = Header(default=None),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
) -> dict[str, Any]:
    subject, uid = resolve_ai_subject(
        authorization=authorization,
        x_device_id=x_device_id,
        request=request,
    )

    if uid and await asyncio.to_thread(_is_premium_user, uid):
        return {"subject": subject, "uid": uid, "premium": True, "count": 0, "limit": FREE_AI_DAILY_LIMIT}

    key = _quota_key(subject)
    client = redis_client.raw

    count = await asyncio.to_thread(client.incr, key)
    if count == 1:
        await asyncio.to_thread(client.expire, key, _seconds_until_utc_midnight())

    ttl = await asyncio.to_thread(client.ttl, key)
    resets_at = (datetime.now(timezone.utc) + timedelta(seconds=max(ttl, 0))).isoformat()

    if count > FREE_AI_DAILY_LIMIT:
        await asyncio.to_thread(_log_ai_usage, subject, uid, count, blocked=True)
        raise HTTPException(
            status_code=402,
            detail={
                "code": "AI_QUOTA_EXCEEDED",
                "safeMessage": "Daily AI limit reached. Upgrade to Ofertix Premium for unlimited queries.",
                "meta": {
                    "limit": FREE_AI_DAILY_LIMIT,
                    "used": count,
                    "resetsAt": resets_at,
                },
            },
        )

    await asyncio.to_thread(_log_ai_usage, subject, uid, count, blocked=False)
    return {
        "subject": subject,
        "uid": uid,
        "premium": False,
        "count": count,
        "limit": FREE_AI_DAILY_LIMIT,
        "resetsAt": resets_at,
    }


def ai_quota_exceeded_response(exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "AI_QUOTA_EXCEEDED", "safeMessage": str(exc.detail)}
    meta = detail.get("meta") if isinstance(detail, dict) else {}
    return localized_error_response(
        status_code=402,
        code="AI_QUOTA_EXCEEDED",
        message_id="ai_quota_exceeded",
        detail=str(detail.get("code") or "AI_QUOTA_EXCEEDED"),
        extra_meta=meta if isinstance(meta, dict) else {},
    )


def _log_ai_usage(subject: str, uid: str | None, count: int, *, blocked: bool) -> None:
    if db is None:
        return
    try:
        db.collection("ai_usage_logs").add(
            {
                "subject": subject,
                "uid": uid,
                "count": count,
                "blocked": blocked,
                "limit": FREE_AI_DAILY_LIMIT,
                "createdAt": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception:
        pass
