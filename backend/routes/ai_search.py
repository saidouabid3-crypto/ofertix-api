from __future__ import annotations

import logging

from fastapi import APIRouter

from core.api_errors import localized_error_response
from schemas.ai_schema import AISearchRequest, AISearchResponse
from services.unified_ai_service import unified_ai_service

logger = logging.getLogger("ofertix.routes.ai_search")

router = APIRouter(prefix="/api/ai", tags=["AI"])


@router.post("/search", response_model=AISearchResponse)
async def ai_search(payload: AISearchRequest):
    history = [
        {"role": item.role, "content": item.content} for item in payload.history
    ]

    try:
        return await unified_ai_service.ai_search(
            query=payload.query,
            country_code=payload.countryCode,
            currency=payload.currency,
            language=payload.language,
            latitude=payload.latitude,
            longitude=payload.longitude,
            history=history,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai_search failed: %s", exc)
        return localized_error_response(
            status_code=503,
            code="AI_SEARCH_FAILED",
            message_id="ai_unavailable",
            detail=str(exc),
        )
