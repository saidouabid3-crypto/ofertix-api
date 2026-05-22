import json
import os
from typing import Any, Dict, Optional

import httpx


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIService:
    def __init__(self) -> None:
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    async def analyze_query(
        self,
        query: str,
        country_code: str = "global",
        currency: str = "EUR",
        language: str = "auto",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:
        clean_query = query.strip()

        if not clean_query:
            return self._empty_response()

        if not self.api_key:
            return self._fallback_response(clean_query)

        payload = {
            "model": self.model,
            "temperature": 0.45,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": clean_query,
                            "countryCode": country_code,
                            "currency": currency,
                            "appLanguage": language,
                            "latitude": latitude,
                            "longitude": longitude,
                            "appContext": {
                                "name": "Ofertix",
                                "type": "global shopping deals app",
                                "features": [
                                    "AI shopping assistant",
                                    "product search",
                                    "voice search",
                                    "visual search",
                                    "barcode scan",
                                    "online stores",
                                    "local stores",
                                    "price alerts",
                                    "cashback",
                                    "rewards",
                                    "affiliate deals",
                                ],
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=35) as client:
                response = await client.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

            if response.status_code >= 400:
                return self._fallback_response(clean_query)

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)

            return self._normalize(parsed, clean_query)

        except Exception:
            return self._fallback_response(clean_query)

    def _system_prompt(self) -> str:
        return """
You are Ofertix AI, a powerful global shopping expert inside a deals app.

You must do everything intelligently:
- Understand the user's message in any language.
- Detect the user's language from the message itself.
- Reply naturally in the same language used by the user.
- If the user writes Moroccan Darija with Latin letters, understand it and answer naturally in Moroccan Darija or Arabic-style Darija.
- Do not use fixed scripted answers.
- Behave like a real expert shopping assistant.
- Help with buying advice, product comparison, price strategy, local stores, online deals, discounts, alternatives, warnings, and recommendations.
- If the user only greets you, answer naturally and guide them to ask for a product or deal.
- If the user asks for a product, extract a clean product search query.
- If the user asks for cheap products, detect cheapest intent.
- If the user asks for discounts, detect discount intent.
- If the user asks for local or nearby shops, detect local and nearby intent.
- If the user mentions Amazon, AliExpress, Temu, online, detect online intent.
- If the user mentions a budget, extract maxPrice.
- If the request is vague, ask a useful follow-up question instead of inventing product results.
- Do not invent real products, prices, stores, or availability.
- Product results will be fetched later by Ofertix ProductService.
- Your job is to understand, advise, suggest searches, give buying tips, and return structured shopping data.

Return ONLY valid JSON. No markdown. No extra text.

Required JSON schema:
{
  "answer": "natural helpful expert answer in the same language as the user",
  "searchQuery": "short clean product search query, or empty if no product search is needed",
  "intent": "greeting | search | compare | cheap | premium | local | online | discount | advice | unknown",
  "onlineOnly": false,
  "localOnly": false,
  "nearby": false,
  "maxPrice": null,
  "category": null,
  "sortBy": "best | cheapest | discount | nearby | premium",
  "suggestions": [
    "short product/search suggestion",
    "short product/search suggestion",
    "short product/search suggestion"
  ],
  "buyingTips": [
    "short practical buying tip",
    "short practical buying tip",
    "short practical buying tip"
  ],
  "needsProducts": true
}

Rules:
- answer must never be empty.
- answer must be conversational and expert.
- suggestions must be short search phrases.
- buyingTips must be practical and useful.
- needsProducts must be false for greeting, vague advice, or general questions with no product.
- needsProducts must be true when a product search should happen.
- searchQuery must be clean and useful for database search.
- sortBy must match intent.
"""

    def _normalize(self, data: Dict[str, Any], fallback_query: str) -> Dict[str, Any]:
        intent = self._safe_string(data.get("intent"), "search")

        search_query = self._safe_string(data.get("searchQuery"), "")
        if not search_query and intent not in ["greeting", "advice", "unknown"]:
            search_query = fallback_query

        sort_by = self._safe_string(data.get("sortBy"), "best")
        if sort_by not in ["best", "cheapest", "discount", "nearby", "premium"]:
            sort_by = "best"

        answer = self._safe_string(data.get("answer"), "")
        if not answer:
            answer = "I understood your request. I can help you compare options and find the best deal."

        suggestions = self._safe_list(data.get("suggestions"))
        buying_tips = self._safe_list(data.get("buyingTips"))

        needs_products = data.get("needsProducts")
        if not isinstance(needs_products, bool):
            needs_products = bool(search_query)

        return {
            "answer": answer,
            "searchQuery": search_query,
            "intent": intent,
            "onlineOnly": bool(data.get("onlineOnly", False)),
            "localOnly": bool(data.get("localOnly", False)),
            "nearby": bool(data.get("nearby", False)),
            "maxPrice": self._to_float_or_none(data.get("maxPrice")),
            "category": self._nullable_string(data.get("category")),
            "sortBy": sort_by,
            "suggestions": suggestions,
            "buyingTips": buying_tips,
            "needsProducts": needs_products,
            "products": [],
        }

    def _empty_response(self) -> Dict[str, Any]:
        return {
            "answer": "Tell me what you want to buy and I will help you find the best option.",
            "searchQuery": "",
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

    def _fallback_response(self, query: str) -> Dict[str, Any]:
        return {
            "answer": "I understood your request. I will search related products and help you compare the best options.",
            "searchQuery": query.strip(),
            "intent": "search",
            "onlineOnly": False,
            "localOnly": False,
            "nearby": False,
            "maxPrice": None,
            "category": None,
            "sortBy": "best",
            "suggestions": [query.strip()],
            "buyingTips": [
                "Compare the final price including delivery.",
                "Check seller reliability and return policy.",
                "Avoid offers with unclear warranty.",
            ],
            "needsProducts": True,
            "products": [],
        }

    def _safe_string(self, value: Any, fallback: str) -> str:
        if value is None:
            return fallback

        text = str(value).strip()
        return text if text else fallback

    def _safe_list(self, value: Any, max_items: int = 5) -> list[str]:
        if not isinstance(value, list):
            return []

        result = []

        for item in value:
            text = str(item).strip()
            if text and text.lower() != "null":
                result.append(text)

        return result[:max_items]

    def _to_float_or_none(self, value: Any) -> Optional[float]:
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

    def _nullable_string(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()

        if not text or text.lower() == "null":
            return None

        return text


ai_service = AIService()