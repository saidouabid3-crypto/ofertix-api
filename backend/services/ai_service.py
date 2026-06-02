from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.locale_context import get_locale
from services.llm_transport import LLMTransportError, llm_transport
from services.locale_prompt_engine import locale_prompt_engine

logger = logging.getLogger("ofertix.ai.search")


class AIService:
    """Conversational shopping assistant (Ofertix AI search).

    Uses the single LLM transport and the dynamic prompt engine. The reply
    language follows the user's own message (auto-detect), with the resolved
    request locale as a strong hint. All response normalization is preserved
    so the Flutter ``AISearchResponse`` contract is unchanged.
    """

    async def analyze_query(
        self,
        query: str,
        country_code: str = "global",
        currency: str = "EUR",
        language: str = "auto",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        if not clean_query:
            return self._empty()

        locale = get_locale().merged_with(
            language=language,
            country=country_code,
            currency=currency,
            allow_auto=True,
        )
        system_prompt = locale_prompt_engine.build_ai_search_system_prompt(locale)

        user_content = json.dumps(
            {
                "message": clean_query,
                "countryCode": country_code,
                "currency": currency,
                "appLanguage": language,
                "latitude": latitude,
                "longitude": longitude,
                "instruction": (
                    "This is the exact current user message. Use previous messages "
                    "only as context. Understand the current message yourself. "
                    "Generate productQueries yourself. The Flutter app will not "
                    "translate or guess product keywords."
                ),
            },
            ensure_ascii=False,
        )

        try:
            content = await llm_transport.complete_json(
                system_prompt=system_prompt,
                user_content=user_content,
                temperature=0.42,
                max_tokens=1200,
                provider_role="fast",
                history=history or [],
            )
            parsed = json.loads(content)
            return self._normalize(parsed, clean_query)
        except LLMTransportError:
            raise
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("AI search returned an invalid response: %s", exc)
            raise LLMTransportError(
                "AI search provider returned an invalid structured response.",
                code="AI_INVALID_RESPONSE",
                role="fast",
            ) from exc

    # --- normalization (unchanged contract) ------------------------------

    def _normalize(self, data: dict[str, Any], fallback_query: str) -> dict[str, Any]:
        answer = self._text(data.get("answer"))
        search_query = self._text(data.get("searchQuery"))
        product_queries = self._list_text(data.get("productQueries"))

        intent = self._text(data.get("intent")) or "unknown"
        sort_by = self._text(data.get("sortBy")) or "best"

        allowed_intents = {
            "greeting", "search", "compare", "cheap", "premium", "local",
            "online", "discount", "advice", "unknown",
        }
        allowed_sort = {"best", "cheapest", "discount", "nearby", "premium"}

        if intent not in allowed_intents:
            intent = "unknown"
        if sort_by not in allowed_sort:
            sort_by = "best"

        needs_products = data.get("needsProducts")
        if not isinstance(needs_products, bool):
            needs_products = bool(search_query or product_queries)

        if needs_products and not search_query:
            search_query = product_queries[0] if product_queries else fallback_query

        if needs_products and not product_queries:
            product_queries = [search_query or fallback_query]

        product_queries = self._unique_list(product_queries, max_items=12)

        return {
            "answer": answer,
            "searchQuery": search_query,
            "productQueries": product_queries,
            "intent": intent,
            "onlineOnly": bool(data.get("onlineOnly", False)),
            "localOnly": bool(data.get("localOnly", False)),
            "nearby": bool(data.get("nearby", False)),
            "maxPrice": self._number_or_none(data.get("maxPrice")),
            "category": self._nullable_text(data.get("category")),
            "sortBy": sort_by,
            "suggestions": self._list_text(data.get("suggestions")),
            "buyingTips": self._list_text(data.get("buyingTips")),
            "needsProducts": needs_products,
            "products": [],
        }

    def _empty(self) -> dict[str, Any]:
        return {
            "answer": "",
            "searchQuery": "",
            "productQueries": [],
            "intent": "unknown",
            "onlineOnly": False,
            "localOnly": False,
            "nearby": False,
            "maxPrice": None,
            "category": None,
            "sortBy": "best",
            "suggestions": [],
            "buyingTips": [],
            "needsProducts": False,
            "products": [],
        }

    def _text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() == "null":
            return ""
        return text

    def _nullable_text(self, value: Any) -> Optional[str]:
        text = self._text(value)
        return text if text else None

    def _list_text(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items = []
        for item in value:
            text = self._text(item)
            if text:
                items.append(text)
        return self._unique_list(items, max_items=12)

    def _unique_list(self, items: list[str], max_items: int = 12) -> list[str]:
        result: list[str] = []
        for item in items:
            clean = item.strip()
            if not clean:
                continue
            if not any(existing.lower() == clean.lower() for existing in result):
                result.append(clean)
        return result[:max_items]

    def _number_or_none(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return None
        return None


ai_service = AIService()
