from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from core.api_errors import localized_error_response
from core.ai_rate_limit import enforce_ai_rate_limit
from schemas.ai_schema import AISearchRequest, AISearchResponse
from services.ai_deal_brain_pro_service import ai_deal_brain_pro_service
from services.llm_transport import LLMTransportError
from services.unified_ai_service import unified_ai_service

logger = logging.getLogger("ofertix.routes.ai_search")

router = APIRouter(prefix="/api/ai", tags=["AI"])


async def _run_pro_max(payload: dict, mode: str, role: str):
    try:
        if mode == "chat":
            return await ai_deal_brain_pro_service.chat(payload)
        if mode == "product_analysis":
            return await ai_deal_brain_pro_service.analyze_product(payload)
        if mode == "ask_before_buying":
            return await ai_deal_brain_pro_service.ask_before_buying(payload)
        if mode == "daily_hunt":
            return await ai_deal_brain_pro_service.daily_hunt(payload)
        if mode == "card_verdict":
            return await ai_deal_brain_pro_service.card_verdict(payload)
        raise ValueError(f"Unsupported AI mode: {mode}")
    except LLMTransportError as exc:
        logger.warning("%s provider error: %s", mode, exc)
        return JSONResponse(
            status_code=503,
            content=ai_deal_brain_pro_service.provider_error(exc, role),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s failed: %s", mode, exc)
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "AI_RESPONSE_FAILED",
                "message": str(exc),
                "providerRole": role,
                "attemptedProviders": [],
            },
        )


@router.post("/chat")
async def ai_chat(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    return await _run_pro_max(payload, "chat", "fast")


@router.post("/analyze-product")
async def ai_analyze_product(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    return await _run_pro_max(payload, "product_analysis", "premium")


@router.post("/ask-before-buying")
async def ai_ask_before_buying(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    return await _run_pro_max(payload, "ask_before_buying", "premium")


@router.post("/daily-hunt")
async def ai_daily_hunt(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    return await _run_pro_max(payload, "daily_hunt", "fast")


@router.post("/card-verdict")
async def ai_card_verdict(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    return await _run_pro_max(payload, "card_verdict", "fast")


@router.post("/recommendations")
async def ai_recommendations(
    payload: dict,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"products": []}

    try:
        result = await unified_ai_service.ai_search(
            query=query,
            country_code=str(payload.get("countryCode") or payload.get("country") or "global"),
            currency=str(payload.get("currency") or "EUR"),
            language=str(payload.get("language") or "auto"),
            latitude=payload.get("latitude"),
            longitude=payload.get("longitude"),
            history=[],
        )
        return {"products": result.get("products") or []}
    except LLMTransportError as exc:
        logger.warning("ai_recommendations provider error: %s", exc)
        return localized_error_response(
            status_code=503,
            code=exc.code,
            message_id="ai_unavailable",
            detail=str(exc),
            extra_meta={"providers": exc.providers, "role": exc.role or "fast"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai_recommendations failed: %s", exc)
        return localized_error_response(
            status_code=503,
            code="AI_RECOMMENDATIONS_FAILED",
            message_id="ai_unavailable",
            detail=str(exc),
        )


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
    except LLMTransportError as exc:
        logger.warning("ai_search provider error: %s", exc)
        return localized_error_response(
            status_code=503,
            code=exc.code,
            message_id="ai_unavailable",
            detail=str(exc),
            extra_meta={"providers": exc.providers, "role": exc.role or "fast"},
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
        except LLMTransportError as exc:
            logger.warning("ai_search_stream provider error: %s", exc)
            yield json.dumps(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": str(exc),
                    "providers": exc.providers,
                    "role": exc.role or "fast",
                }
            ) + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai_search_stream failed: %s", exc)
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
