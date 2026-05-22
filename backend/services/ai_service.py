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
            return self._empty()

        if not self.api_key:
            return self._technical_error(clean_query)

        payload = {
            "model": self.model,
            "temperature": 0.45,
            "max_tokens": 1100,
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
                            "important": "Understand the user language yourself. Generate productQueries yourself. Do not rely on the app to translate.",
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

            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)

            return self._normalize(parsed, clean_query)

        except Exception:
            return self._technical_error(clean_query)

    def _system_prompt(self) -> str:
        return """
You are Ofertix AI, a smart global shopping assistant inside the Ofertix app.

Your job:
- Understand the user's message naturally in any language.
- Detect the language from the user's message.
- Answer in the same language used by the user.
- If the user writes Moroccan Darija with Latin letters, understand it and answer naturally.
- Give helpful shopping advice.
- Ask follow-up questions when the request is not clear.
- When the user asks for products, generate useful product search queries for the product database.

Very important:
The app will NOT translate or map words.
You must generate productQueries yourself.
productQueries must contain short useful search keywords that can match product names in an international product database.
If the user writes Arabic, Darija, French, Spanish, English, German, etc., you still generate productQueries using useful searchable terms, often in English and Spanish too.

Examples:
User asks in Arabic for سماعات:
productQueries could include:
["headphones", "bluetooth headphones", "earbuds", "auriculares", "airpods"]

User asks in Darija "bghit sma3at rkhisa":
productQueries could include:
["cheap headphones", "bluetooth earbuds", "auriculares baratos", "headphones", "earbuds"]

User asks "اعطني كل العروض الموجودة":
productQueries should include broad popular categories:
["iphone", "samsung", "xiaomi", "headphones", "auriculares", "smartwatch", "laptop", "gaming", "tv"]

User asks "WH-1000XM5":
productQueries should include:
["WH-1000XM5", "sony WH-1000XM5", "sony headphones", "auriculares sony"]

Rules:
- Do not invent real products, prices, stores, or availability.
- Product results are fetched later by Ofertix ProductService.
- Your answer can ask questions or give advice.
- needsProducts must be true whenever the app should search products.
- productQueries must be non-empty when needsProducts is true.
- searchQuery is the best single query.
- productQueries is a list of multiple queries to try.
- suggestions are quick options the user can tap.
- buyingTips are short useful tips.
- Return ONLY valid JSON. No markdown. No extra text.

Required JSON:
{
  "answer": "natural answer in the same language as user",
  "searchQuery": "best single product search query, empty if no product search needed",
  "productQueries": ["query 1", "query 2", "query 3"],
  "intent": "greeting | search | compare | cheap | premium | local | online | discount | advice | unknown",
  "onlineOnly": false,
  "localOnly": false,
  "nearby": false,
  "maxPrice": null,
  "category": null,
  "sortBy": "best | cheapest | discount | nearby | premium",
  "suggestions": ["short quick option", "short quick option", "short quick option"],
  "buyingTips": ["short practical tip", "short practical tip", "short practical tip"],
  "needsProducts": true
}
"""

    def _normalize(self, data: Dict[str, Any], fallback_query: str) -> Dict[str, Any]:
        answer = self._text(data.get("answer"))
        search_query = self._text(data.get("searchQuery"))
        product_queries = self._list_text(data.get("productQueries"))

        intent = self._text(data.get("intent")) or "unknown"
        sort_by = self._text(data.get("sortBy")) or "best"

        allowed_intents = {
            "greeting",
            "search",
            "compare",
            "cheap",
            "premium",
            "local",
            "online",
            "discount",
            "advice",
            "unknown",
        }

        allowed_sort = {
            "best",
            "cheapest",
            "discount",
            "nearby",
            "premium",
        }

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

        product_queries = self._unique_list(product_queries, max_items=10)

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

    def _empty(self) -> Dict[str, Any]:
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

    def _technical_error(self, query: str) -> Dict[str, Any]:
        return {
            "answer": "",
            "searchQuery": query,
            "productQueries": [query],
            "intent": "search",
            "onlineOnly": False,
            "localOnly": False,
            "nearby": False,
            "maxPrice": None,
            "category": None,
            "sortBy": "best",
            "suggestions": [],
            "buyingTips": [],
            "needsProducts": True,
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

        return self._unique_list(items, max_items=10)

    def _unique_list(self, items: list[str], max_items: int = 10) -> list[str]:
        result = []

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