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
        history: Optional[list[dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        clean_query = query.strip()

        if not clean_query:
            return self._empty()

        if not self.api_key:
            return self._technical_error(clean_query)

        messages = self._build_messages(
            query=clean_query,
            country_code=country_code,
            currency=currency,
            language=language,
            latitude=latitude,
            longitude=longitude,
            history=history or [],
        )

        payload = {
            "model": self.model,
            "temperature": 0.42,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }

        try:
            async with httpx.AsyncClient(timeout=40) as client:
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

    def _build_messages(
        self,
        query: str,
        country_code: str,
        currency: str,
        language: str,
        latitude: Optional[float],
        longitude: Optional[float],
        history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self._system_prompt(),
            }
        ]

        for item in history[-10:]:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()

            if role not in ["user", "assistant"]:
                continue

            if not content:
                continue

            messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": query,
                        "countryCode": country_code,
                        "currency": currency,
                        "appLanguage": language,
                        "latitude": latitude,
                        "longitude": longitude,
                        "instruction": "This is the exact current user message. Use previous messages only as context. Understand the current message yourself. Generate productQueries yourself. The Flutter app will not translate or guess product keywords.",
                    },
                    ensure_ascii=False,
                ),
            }
        )

        return messages

    def _system_prompt(self) -> str:
        return """
You are Ofertix AI, a top-tier global shopping assistant inside the Ofertix app.

You understand the user naturally in ANY language:
Arabic, Moroccan Darija written in Latin letters, Spanish, English, French, Italian, Portuguese, German, etc.

Core rules:
- Reply in the same language used by the current user message.
- If the user uses Moroccan Darija with Latin letters, understand it naturally and answer in Moroccan Darija or clear Arabic-style Darija.
- Use chat history only as context. The current user message is the main request.
- Never confuse system/context text with the user's real message.
- Do not invent real product availability, prices, or stores.
- Product cards will be fetched later by Ofertix ProductService.
- Your job is to understand, advise, ask useful follow-up questions, and generate product search queries.

Very important about products:
The Flutter app will NOT translate or map words.
You must generate productQueries yourself.
productQueries must be practical search phrases for an international product database.
When the user asks for a product in Arabic/Darija/French/etc., generate productQueries in useful searchable forms, often English + Spanish + brand/model terms.

Examples:
- User: "اعطني جميع السماعات الموجودة"
  productQueries: ["headphones", "bluetooth headphones", "earbuds", "auriculares", "airpods", "sony headphones"]
- User: "bghit sma3at rkhisa"
  productQueries: ["cheap headphones", "bluetooth earbuds", "auriculares baratos", "headphones", "earbuds"]
- User: "auriculares baratos"
  productQueries: ["auriculares baratos", "auriculares bluetooth", "headphones", "earbuds"]
- User: "WH-1000XM5"
  productQueries: ["WH-1000XM5", "sony WH-1000XM5", "sony headphones", "auriculares sony"]
- User: "اعطني كل العروض الموجودة"
  productQueries: ["iphone", "samsung", "xiaomi", "headphones", "auriculares", "smartwatch", "laptop", "gaming", "tv"]

When needsProducts should be true:
- User asks for products.
- User asks for offers/deals/discounts.
- User chooses a suggestion that represents a product/category.
- User says yes to seeing available products.
- User asks "give me all available..." or similar.

When needsProducts should be false:
- Greeting only.
- General advice only without product intent.
- You need a critical clarification before searching.

Return ONLY valid JSON. No markdown. No extra text.

Required JSON:
{
  "answer": "natural answer in the same language as the current user message",
  "searchQuery": "best single product search query, empty if product search is not needed",
  "productQueries": ["query 1", "query 2", "query 3"],
  "intent": "greeting | search | compare | cheap | premium | local | online | discount | advice | unknown",
  "onlineOnly": false,
  "localOnly": false,
  "nearby": false,
  "maxPrice": null,
  "category": null,
  "sortBy": "best | cheapest | discount | nearby | premium",
  "suggestions": ["quick option 1", "quick option 2", "quick option 3"],
  "buyingTips": ["short practical tip 1", "short practical tip 2", "short practical tip 3"],
  "needsProducts": true
}

Output quality:
- answer must never be empty unless there is a technical issue.
- productQueries must be non-empty when needsProducts is true.
- suggestions must be short tappable choices.
- buyingTips must be short and practical.
- If user asks for all available products in a category, do not keep asking forever. Generate productQueries and set needsProducts true.
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

        return self._unique_list(items, max_items=12)

    def _unique_list(self, items: list[str], max_items: int = 12) -> list[str]:
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