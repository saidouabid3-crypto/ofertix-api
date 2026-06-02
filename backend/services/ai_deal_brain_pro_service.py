from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.locale_context import get_locale
from services.llm_transport import LLMTransportError, llm_transport


_ALLOWED_VERDICTS = {
    "buy_now",
    "wait",
    "avoid",
    "fake_discount",
    "better_alternative",
    "watch_price",
    "hidden_gem",
}

_RESPONSE_CONTRACT = """{
  "mode": "chat | product_analysis | ask_before_buying | daily_hunt | card_verdict",
  "verdict": "buy_now | wait | avoid | fake_discount | better_alternative | watch_price | hidden_gem",
  "score": 0,
  "summary": "",
  "brutalTruth": "",
  "dealDNA": {
    "price": "strong | fair | weak | unknown",
    "trust": "high | medium | low | unknown",
    "discount": "real | suspicious | fake_possible | unknown",
    "risk": "low | medium | high",
    "value": "excellent | good | average | bad"
  },
  "reasons": [],
  "risks": [],
  "priceAdvice": {
    "isGoodPrice": false,
    "estimatedFairPrice": null,
    "youSave": null,
    "shouldWait": false,
    "recommendation": ""
  },
  "budgetAdvice": {
    "safeForBudget": null,
    "message": ""
  },
  "antiImpulseAdvice": {
    "isImpulseRisk": false,
    "cooldownSuggested": false,
    "message": ""
  },
  "alternatives": [],
  "dailyHunt": [],
  "confidence": 0.0
}"""


class AiDealBrainProService:
    """Unified Deal Brain Pro Max surface for Flutter-facing AI routes."""

    async def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(
            mode="chat",
            provider_role="fast",
            task="Answer the user's shopping question as Ofertix Deal Brain.",
            payload=payload,
        )

    async def analyze_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(
            mode="product_analysis",
            provider_role="premium",
            task="Analyze this Ofertix product detail. Do not invent missing facts.",
            payload=payload,
        )

    async def ask_before_buying(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(
            mode="ask_before_buying",
            provider_role="premium",
            task=(
                "Analyze the pasted product URL or product text before purchase. "
                "If a URL cannot be fetched from provided data, say what is missing."
            ),
            payload=payload,
        )

    async def daily_hunt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(
            mode="daily_hunt",
            provider_role="fast",
            task=(
                "Return practical daily deal opportunities based only on the "
                "provided context, budget, country, currency, and interests."
            ),
            payload=payload,
        )

    async def card_verdict(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._run(
            mode="card_verdict",
            provider_role="fast",
            task="Return a fast lightweight product-card verdict.",
            payload=payload,
            max_tokens=700,
        )

    async def _run(
        self,
        *,
        mode: str,
        provider_role: str,
        task: str,
        payload: dict[str, Any],
        max_tokens: int = 1600,
    ) -> dict[str, Any]:
        context = self._context(payload)
        system_prompt = self._system_prompt(mode, task, context)
        user_content = json.dumps(
            {
                "mode": mode,
                "context": context,
                "input": payload,
                "rules": [
                    "Do not invent product facts, prices, reviews, stock, or stores.",
                    "Lower confidence when product data is incomplete.",
                    "Return only JSON matching the contract.",
                ],
            },
            ensure_ascii=False,
        )
        completion = await llm_transport.complete_json_with_metadata(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.25 if provider_role == "premium" else 0.35,
            max_tokens=max_tokens,
            provider_role=provider_role,
        )
        parsed = json.loads(self._extract_json(completion.content))
        normalized = self._normalize(parsed, mode, context)
        normalized["provider"] = completion.provider
        normalized["model"] = completion.model
        return normalized

    def provider_error(self, exc: LLMTransportError, role: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": "AI_NOT_CONFIGURED"
            if exc.code == "AI_PROVIDER_NOT_CONFIGURED"
            else exc.code,
            "message": "AI provider is not configured."
            if exc.code == "AI_PROVIDER_NOT_CONFIGURED"
            else str(exc),
            "providerRole": exc.role or role,
            "attemptedProviders": exc.providers,
        }

    def _context(self, payload: dict[str, Any]) -> dict[str, str]:
        locale = get_locale().merged_with(
            language=self._string(payload.get("language"), "auto"),
            country=self._string(
                payload.get("country")
                or payload.get("countryCode")
                or payload.get("userCountry"),
                "global",
            ),
            currency=self._string(
                payload.get("currency") or payload.get("userCurrency"),
                "EUR",
            ),
            allow_auto=True,
        )
        return {
            "language": locale.language,
            "country": locale.effective_country,
            "currency": locale.effective_currency,
            "displayLanguage": locale.display_name,
        }

    def _system_prompt(self, mode: str, task: str, context: dict[str, str]) -> str:
        return f"""You are Ofertix Deal Brain, a global shopping AI.

Mode: {mode}
Task: {task}
User language: {context["displayLanguage"]} [{context["language"]}]
Shopping country: {context["country"]}
Currency: {context["currency"]}

Write every user-facing string value in the user's language.
Keep all JSON keys and enum values in English exactly as specified.
Return ONLY valid JSON. No markdown. No extra text.

Required JSON contract:
{_RESPONSE_CONTRACT}
"""

    def _normalize(
        self,
        data: dict[str, Any],
        mode: str,
        context: dict[str, str],
    ) -> dict[str, Any]:
        verdict = self._string(data.get("verdict"), "watch_price")
        if verdict not in _ALLOWED_VERDICTS:
            verdict = "watch_price"
        score = max(0, min(self._int(data.get("score"), 0), 100))
        confidence = max(0.0, min(self._float(data.get("confidence"), 0), 1.0))
        if confidence > 1:
            confidence = confidence / 100

        return {
            "success": True,
            "mode": mode,
            "verdict": verdict,
            "score": score,
            "summary": self._string(data.get("summary")),
            "brutalTruth": self._string(data.get("brutalTruth")),
            "dealDNA": self._deal_dna(data.get("dealDNA")),
            "reasons": self._list(data.get("reasons")),
            "risks": self._list(data.get("risks")),
            "priceAdvice": self._price_advice(data.get("priceAdvice")),
            "budgetAdvice": self._budget_advice(data.get("budgetAdvice")),
            "antiImpulseAdvice": self._anti_impulse(data.get("antiImpulseAdvice")),
            "alternatives": self._list(data.get("alternatives")),
            "dailyHunt": self._daily_hunt(data.get("dailyHunt")),
            "confidence": confidence,
            "language": context["language"],
            "country": context["country"],
            "currency": context["currency"],
            "provider": "",
            "model": "",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

    def _deal_dna(self, value: Any) -> dict[str, str]:
        data = value if isinstance(value, dict) else {}
        return {
            "price": self._choice(data.get("price"), {"strong", "fair", "weak", "unknown"}, "unknown"),
            "trust": self._choice(data.get("trust"), {"high", "medium", "low", "unknown"}, "unknown"),
            "discount": self._choice(data.get("discount"), {"real", "suspicious", "fake_possible", "unknown"}, "unknown"),
            "risk": self._choice(data.get("risk"), {"low", "medium", "high"}, "medium"),
            "value": self._choice(data.get("value"), {"excellent", "good", "average", "bad"}, "average"),
        }

    def _price_advice(self, value: Any) -> dict[str, Any]:
        data = value if isinstance(value, dict) else {}
        return {
            "isGoodPrice": data.get("isGoodPrice") is True,
            "estimatedFairPrice": self._number_or_none(data.get("estimatedFairPrice")),
            "youSave": self._number_or_none(data.get("youSave")),
            "shouldWait": data.get("shouldWait") is True,
            "recommendation": self._string(data.get("recommendation")),
        }

    def _budget_advice(self, value: Any) -> dict[str, Any]:
        data = value if isinstance(value, dict) else {}
        safe = data.get("safeForBudget")
        return {
            "safeForBudget": safe if isinstance(safe, bool) else None,
            "message": self._string(data.get("message")),
        }

    def _anti_impulse(self, value: Any) -> dict[str, Any]:
        data = value if isinstance(value, dict) else {}
        return {
            "isImpulseRisk": data.get("isImpulseRisk") is True,
            "cooldownSuggested": data.get("cooldownSuggested") is True,
            "message": self._string(data.get("message")),
        }

    def _daily_hunt(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value[:8]:
            if isinstance(item, dict):
                items.append({str(k): v for k, v in item.items()})
            elif str(item).strip():
                items.append({"title": str(item).strip()})
        return items

    def _choice(self, value: Any, allowed: set[str], fallback: str) -> str:
        text = self._string(value, fallback).lower()
        return text if text in allowed else fallback

    def _extract_json(self, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("{") and raw.endswith("}"):
            return raw
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start : end + 1]
        raise ValueError("AI response did not contain JSON.")

    def _string(self, value: Any, fallback: str = "") -> str:
        text = "" if value is None else str(value).strip()
        return text if text and text.lower() != "null" else fallback

    def _list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [text for item in value if (text := self._string(item))]

    def _int(self, value: Any, fallback: int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return round(value)
        return int(float(str(value))) if str(value).replace(".", "", 1).isdigit() else fallback

    def _float(self, value: Any, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _number_or_none(self, value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None


ai_deal_brain_pro_service = AiDealBrainProService()
