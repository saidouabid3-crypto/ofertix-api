from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from core.firebase import db

logger = logging.getLogger("ofertix.events")

router = APIRouter(prefix="/events", tags=["events"])

_ALLOWED_EVENTS = {
    "product-view",
    "offer-click",
    "ai-ask",
    "report-product",
}


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key)[:80]: value
        for key, value in payload.items()
        if key not in {"token", "authorization", "password", "secret"}
    }


@router.post("/{event_name}")
async def track_event(event_name: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if event_name not in _ALLOWED_EVENTS:
        return {"ok": True, "ignored": True}

    event = {
        "event": event_name,
        "payload": _safe_payload(payload),
        "path": str(request.url.path),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    try:
        db.collection("analytics_events").add(event)
    except Exception as exc:
        logger.debug("analytics event dropped: %s", type(exc).__name__)

    return {"ok": True}
