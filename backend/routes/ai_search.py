from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core.api_errors import localized_error_response
from core.ai_rate_limit import enforce_ai_rate_limit
from schemas.ai_schema import AISearchRequest, AISearchResponse
from services.unified_ai_service import unified_ai_service

logger = logging.getLogger("ofertix.routes.ai_search")

router = APIRouter(prefix="/api/ai", tags=["AI"])


@router.post("/search", response_model=AISearchResponse)
async def ai_search(
    payload: AISearchRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
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


@router.post("/search/stream")
async def ai_search_stream(
    payload: AISearchRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    history = [
        {"role": item.role, "content": item.content} for item in payload.history
    ]

    async def event_generator():
        try:
            result = await unified_ai_service.ai_search(
                query=payload.query,
                country_code=payload.countryCode,
                currency=payload.currency,
                language=payload.language,
                latitude=payload.latitude,
                longitude=payload.longitude,
                history=history,
            )
            answer = str(result.get("answer") or "")
            chunk_size = 48
            for index in range(0, max(len(answer), 1), chunk_size):
                partial = answer[: index + chunk_size]
                yield json.dumps({"type": "token", "answer": partial}) + "\n"
            yield json.dumps({"type": "done", "payload": result}) + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai_search_stream failed: %s", exc)
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
