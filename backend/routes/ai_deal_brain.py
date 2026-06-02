from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from core.api_errors import localized_error_response
from core.ai_rate_limit import enforce_ai_rate_limit
from schemas.ai_deal_brain import (
    AnalyzeGlobalRequest,
    GlobalDealAnalysisResponse,
    NegotiationRequest,
    ProductExtractRequest,
)
from services.llm_transport import LLMTransportError
from services.scraper_service import scraper_service
from services.unified_ai_service import unified_ai_service

logger = logging.getLogger("ofertix.routes.ai_deal_brain")

router = APIRouter(prefix="/ai-deal-brain", tags=["AI Deal Brain Pro"])


@router.post("/extract-url")
async def extract_url(
    request: ProductExtractRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    try:
        return await scraper_service.extract_product(request)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract-url failed: %s", exc)
        return localized_error_response(
            status_code=502,
            code="EXTRACT_URL_FAILED",
            message_id="bad_data",
            detail=str(exc),
        )


@router.post("/analyze-global", response_model=GlobalDealAnalysisResponse)
async def analyze_global(
    request: AnalyzeGlobalRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    if not request.product.title and request.product.currentPrice <= 0:
        return localized_error_response(
            status_code=422,
            code="ANALYZE_MISSING_PRODUCT",
            message_id="bad_data",
            detail="Product title or price is required.",
        )

    try:
        return await unified_ai_service.analyze_global(request)
    except LLMTransportError as exc:
        logger.warning("analyze-global LLM error: %s", exc)
        return localized_error_response(
            status_code=503,
            code=exc.code,
            message_id="ai_unavailable",
            detail=str(exc),
            extra_meta={"providers": exc.providers, "role": exc.role or "premium"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("analyze-global failed: %s", exc)
        return localized_error_response(
            status_code=500,
            code="ANALYZE_GLOBAL_FAILED",
            message_id="ai_timeout",
            detail=str(exc),
        )


@router.post("/negotiate", response_model=None)
async def negotiate(
    request: NegotiationRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    try:
        script = await unified_ai_service.generate_negotiation(request)
        return {"script": script}
    except LLMTransportError as exc:
        logger.warning("negotiate LLM error: %s", exc)
        return localized_error_response(
            status_code=503,
            code=exc.code,
            message_id="ai_unavailable",
            detail=str(exc),
            extra_meta={"providers": exc.providers, "role": exc.role or "premium"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("negotiate failed: %s", exc)
        return localized_error_response(
            status_code=503,
            code="NEGOTIATE_FAILED",
            message_id="ai_unavailable",
            detail=str(exc),
        )


@router.post("/analyze-url", response_model=GlobalDealAnalysisResponse)
async def analyze_url(
    request: ProductExtractRequest,
    _quota: dict = Depends(enforce_ai_rate_limit),
):
    try:
        product = await scraper_service.extract_product(request)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("analyze-url extraction failed: %s", exc)
        return localized_error_response(
            status_code=502,
            code="ANALYZE_URL_EXTRACT_FAILED",
            message_id="bad_data",
            detail=str(exc),
        )

    analysis_request = AnalyzeGlobalRequest(
        product=product,
        user={
            "country": request.userCountry,
            "currency": request.userCurrency,
            "language": request.language,
        },
    )

    try:
        return await unified_ai_service.analyze_global(analysis_request)
    except LLMTransportError as exc:
        logger.warning("analyze-url LLM error: %s", exc)
        return localized_error_response(
            status_code=503,
            code=exc.code,
            message_id="ai_unavailable",
            detail=str(exc),
            extra_meta={"providers": exc.providers, "role": exc.role or "premium"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("analyze-url analysis failed: %s", exc)
        return localized_error_response(
            status_code=500,
            code="ANALYZE_URL_FAILED",
            message_id="ai_timeout",
            detail=str(exc),
        )
