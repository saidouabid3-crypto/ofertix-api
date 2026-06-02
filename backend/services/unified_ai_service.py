"""The single public entry point for AI in the Ofertix backend.

Routes talk to :data:`unified_ai_service` and nothing else. Internally it
composes the three capability engines behind one consistent, locale-aware
surface:

    * Structured global deal analysis  -> services.ai_engine_service
    * Conversational shopping search   -> services.ai_service
    * Authenticated rules+LLM brain    -> services.ai_brain_service
    * Seller negotiation script        -> services.ai_engine_service

Every method resolves the active request locale from the contextvar populated by
:class:`~core.middleware.locale_middleware.LocaleMiddleware`, so language
selection is uniform and automatic across all AI capabilities. The proven
deterministic mathematics live in the engine modules; this facade owns the
orchestration and the contract surface.
"""

from __future__ import annotations

import logging

from core.locale_context import LocaleState, get_locale
from schemas.ai_deal_brain import (
    AnalyzeGlobalRequest,
    GlobalDealAnalysisResponse,
    NegotiationRequest,
)
from services.ai_brain_service import ai_brain_service
from services.ai_engine_service import ai_engine_service
from services.ai_service import ai_service
from services.llm_transport import llm_transport

logger = logging.getLogger("ofertix.ai.unified")


class UnifiedAIService:
    """One AI service to orchestrate them all."""

    @property
    def locale(self) -> LocaleState:
        """The locale resolved for the current request."""
        return get_locale()

    def llm_available(
        self,
        preferred_provider: str | None = None,
        *,
        provider_role: str | None = None,
    ) -> bool:
        """Whether a usable LLM provider is configured for this deployment."""
        return llm_transport.is_configured(
            preferred_provider,
            provider_role=provider_role,
        )

    # --- AI Deal Brain Pro: structured global analysis -------------------

    async def analyze_global(
        self, request: AnalyzeGlobalRequest
    ) -> GlobalDealAnalysisResponse:
        return await ai_engine_service.analyze_global(request)

    async def generate_negotiation(self, request: NegotiationRequest) -> str:
        return await ai_engine_service.generate_negotiation(request)

    # --- Conversational shopping search ----------------------------------

    async def ai_search(
        self,
        *,
        query: str,
        country_code: str,
        currency: str,
        language: str,
        latitude: float | None,
        longitude: float | None,
        history: list[dict[str, str]] | None,
    ) -> dict:
        return await ai_service.analyze_query(
            query=query,
            country_code=country_code,
            currency=currency,
            language=language,
            latitude=latitude,
            longitude=longitude,
            history=history,
        )

    # --- Authenticated Deal Brain (rules + optional LLM summary) ----------

    async def deal_brain_analyze(self, *, payload, current_user: dict):
        return await ai_brain_service.analyze(payload=payload, current_user=current_user)

    def deal_brain_history(self, *, current_user: dict, limit: int = 30):
        return ai_brain_service.history(current_user=current_user, limit=limit)


# Process-wide singleton: the only AI object the routes import.
unified_ai_service = UnifiedAIService()
