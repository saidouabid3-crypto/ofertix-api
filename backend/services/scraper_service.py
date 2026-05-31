from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, Page, Route, async_playwright

from schemas.ai_deal_brain import DarkPatternSignal, ExtractedProductResponse, ProductExtractRequest

logger = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

STORE_HINTS = {
    "amazon.": ("Amazon", "US", "en"),
    "aliexpress.": ("AliExpress", "CN", "en"),
    "ebay.": ("eBay", "US", "en"),
    "shein.": ("SHEIN", "CN", "en"),
    "temu.": ("Temu", "CN", "en"),
    "wallapop.": ("Wallapop", "ES", "es"),
    "elcorteingles.": ("El Corte Inglés", "ES", "es"),
    "dhgate.": ("DHgate", "CN", "en"),
    "carrefour.": ("Carrefour", "FR", "fr"),
    "mediamarkt.": ("MediaMarkt", "DE", "de"),
    "pccomponentes.": ("PcComponentes", "ES", "es"),
    "fnac.": ("Fnac", "FR", "fr"),
}

CURRENCY_SYMBOLS = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "MAD": "MAD",
    "د.م.": "MAD",
    "EUR": "EUR",
    "USD": "USD",
    "GBP": "GBP",
    "CNY": "CNY",
    "JPY": "JPY",
}

DARK_PATTERN_PATTERNS = {
    "countdown_timer": [
        r"\b\d{1,2}\s*:\s*\d{2}\s*:\s*\d{2}\b",
        r"\b\d{1,2}\s*:\s*\d{2}\b",
        r"expires?\s+(?:in|soon)",
        r"offer\s+ends",
        r"deal\s+ends",
        r"countdown",
        r"timer",
    ],
    "false_scarcity": [
        r"only\s+\d+\s+(?:left|remaining)",
        r"last\s+\d+\s+(?:items?|pieces?)",
        r"limited\s+stock",
        r"almost\s+gone",
        r"low\s+stock",
        r"últimas?\s+\d+",
        r"solo\s+queda",
        r"quedan\s+\d+",
    ],
    "social_pressure": [
        r"\d+\s+(?:people|users|customers)\s+(?:viewing|bought|purchased)",
        r"bought\s+in\s+the\s+last",
        r"popular\s+right\s+now",
        r"trending",
        r"personas\s+viendo",
        r"vendidos?\s+hoy",
    ],
    "forced_urgency": [
        r"buy\s+now",
        r"do\s+not\s+miss",
        r"hurry",
        r"last\s+chance",
        r"act\s+fast",
        r"compra\s+ahora",
        r"date\s+prisa",
        r"última\s+oportunidad",
    ],
}


@dataclass(slots=True)
class StoreInfo:
    store: str
    country: str
    seller_language: str


@dataclass(slots=True)
class CacheEntry:
    value: ExtractedProductResponse
    expires_at: float


class ScraperStrategy(ABC):
    def __init__(self, engine: "PlaywrightEngine") -> None:
        self.engine = engine

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def extract(self, request: ProductExtractRequest, store: StoreInfo) -> ExtractedProductResponse:
        raise NotImplementedError


class AmazonScraper(ScraperStrategy):
    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "amazon." in host

    async def extract(self, request: ProductExtractRequest, store: StoreInfo) -> ExtractedProductResponse:
        response = await self.engine.extract(request, store)
        response.extractionNotes.append("Strategy: AmazonScraper")
        return response


class AliExpressScraper(ScraperStrategy):
    def can_handle(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return "aliexpress." in host

    async def extract(self, request: ProductExtractRequest, store: StoreInfo) -> ExtractedProductResponse:
        response = await self.engine.extract(request, store)
        response.extractionNotes.append("Strategy: AliExpressScraper")
        return response


class GenericScraper(ScraperStrategy):
    def can_handle(self, url: str) -> bool:
        return True

    async def extract(self, request: ProductExtractRequest, store: StoreInfo) -> ExtractedProductResponse:
        response = await self.engine.extract(request, store)
        response.extractionNotes.append("Strategy: GenericScraper")
        return response


class PlaywrightEngine:
    """
    Render RAM-optimized extractor.

    The engine tries a lightweight HTTP parse first, then falls back to Playwright.
    Playwright is always used through async context managers, and all contexts/pages
    are closed deterministically.
    """

    def __init__(self) -> None:
        self.navigation_timeout_ms = 14_000
        self.page_wait_ms = 1_000
        self.http_timeout = httpx.Timeout(8.0)

    async def extract(self, request: ProductExtractRequest, store: StoreInfo) -> ExtractedProductResponse:
        url = str(request.url)

        try:
            lightweight = await self._retry(lambda: self._extract_with_http(url, request, store), attempts=2)
            if lightweight.extractionConfidence >= 68:
                return lightweight
        except Exception as exc:
            logger.info("HTTP extraction failed for %s: %s", self._safe_url(url), exc)

        return await self._retry(lambda: self._extract_with_playwright(url, request, store), attempts=2)

    async def _extract_with_http(
        self,
        url: str,
        request: ProductExtractRequest,
        store: StoreInfo,
    ) -> ExtractedProductResponse:
        async with httpx.AsyncClient(
            timeout=self.http_timeout,
            follow_redirects=True,
            headers=self._headers(request.language),
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        result = self._parse_html(response.text, url, request.userCurrency, store)
        result.extractionNotes.append("Extracted with lightweight HTTP parser.")
        return result

    async def _extract_with_playwright(
        self,
        url: str,
        request: ProductExtractRequest,
        store: StoreInfo,
    ) -> ExtractedProductResponse:
        proxy = {"server": request.proxyUrl} if request.proxyUrl else None

        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(
                headless=True,
                proxy=proxy,
                args=[
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-translate",
                    "--disable-default-apps",
                    "--disable-popup-blocking",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    "--disable-client-side-phishing-detection",
                    "--mute-audio",
                    "--blink-settings=imagesEnabled=false",
                ],
            )
            try:
                context: BrowserContext = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1365, "height": 768},
                    locale=request.language,
                    java_script_enabled=True,
                    extra_http_headers={
                        "Accept-Language": self._accept_language(request.language),
                        "DNT": "1",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                try:
                    await context.route("**/*", self._route_filter)
                    page: Page = await context.new_page()
                    try:
                        page.set_default_navigation_timeout(self.navigation_timeout_ms)
                        page.set_default_timeout(self.navigation_timeout_ms)
                        await page.goto(url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(self.page_wait_ms)
                        html = await page.content()
                    finally:
                        await page.close()
                finally:
                    await context.close()
            finally:
                await browser.close()

        result = self._parse_html(html, url, request.userCurrency, store)
        result.extractionNotes.append("Extracted with ultra-light Playwright fallback.")
        return result

    async def _route_filter(self, route: Route) -> None:
        req = route.request
        resource_type = req.resource_type
        lower_url = req.url.lower()
        blocked_types = {"image", "media", "font", "stylesheet", "websocket", "manifest"}
        blocked_markers = (
            "google-analytics",
            "googletagmanager",
            "doubleclick",
            "facebook",
            "tiktok",
            "analytics",
            "tracking",
            "pixel",
            "adsystem",
            "adservice",
            "hotjar",
            "clarity",
        )
        if resource_type in blocked_types or any(marker in lower_url for marker in blocked_markers):
            await route.abort()
        else:
            await route.continue_()

    async def _retry(self, operation, attempts: int = 3, base_delay: float = 0.35):
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.15))
        assert last_error is not None
        raise last_error

    def _headers(self, language: str) -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self._accept_language(language),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }

    def _accept_language(self, language: str) -> str:
        lang = (language or "en").split("-")[0].lower()
        if lang == "es":
            return "es-ES,es;q=0.9,en;q=0.7"
        if lang == "fr":
            return "fr-FR,fr;q=0.9,en;q=0.7"
        if lang == "ar":
            return "ar,es;q=0.8,en;q=0.7"
        if lang == "de":
            return "de-DE,de;q=0.9,en;q=0.7"
        return "en-US,en;q=0.9"

    def _parse_html(
        self,
        html: str,
        url: str,
        fallback_currency: str,
        store: StoreInfo,
    ) -> ExtractedProductResponse:
        soup = BeautifulSoup(html, "html.parser")
        json_ld = self._extract_product_json_ld(soup)
        meta = self._extract_meta(soup)
        text = soup.get_text(" ", strip=True)[:8000]
        dark_signals = self._detect_dark_patterns(soup, text)

        title = self._first_non_empty(
            json_ld.get("name"),
            meta.get("og:title"),
            meta.get("twitter:title"),
            soup.title.string.strip() if soup.title and soup.title.string else "",
        )

        image = self._extract_image(json_ld, meta)
        price, currency = self._extract_price_and_currency(json_ld, meta, text, fallback_currency)
        old_price = self._extract_old_price(text, price)
        rating = self._safe_float(self._deep_get(json_ld, ["aggregateRating", "ratingValue"]))
        review_count = self._safe_int(self._deep_get(json_ld, ["aggregateRating", "reviewCount"]))
        category = self._first_non_empty(json_ld.get("category"), meta.get("product:category"))
        specs = self._extract_specs(soup, text)
        dimensions = self._extract_dimensions(text)
        weight = self._extract_weight_kg(text)

        confidence = 0
        notes: list[str] = []
        if title:
            confidence += 30
        else:
            notes.append("Missing product title.")
        if price > 0:
            confidence += 35
        else:
            notes.append("Missing product price.")
        if image:
            confidence += 8
        if specs:
            confidence += 10
        if rating:
            confidence += 4
        if review_count:
            confidence += 4
        if json_ld:
            confidence += 6
        if dark_signals:
            confidence += 3

        return ExtractedProductResponse(
            title=title[:500],
            store=store.store,
            storeCountry=store.country,
            sellerLanguage=store.seller_language,
            currentPrice=price,
            oldPrice=old_price,
            baseCurrency=currency or fallback_currency,
            shippingPrice=None,
            estimatedDeliveryDays=None,
            category=category[:160],
            dimensions=dimensions[:300],
            weightKg=weight,
            specs=specs[:5000],
            rating=rating,
            reviewCount=review_count,
            imageUrl=image,
            productUrl=url,
            darkPatternSignals=dark_signals[:12],
            extractionConfidence=min(confidence, 100),
            extractionNotes=notes,
        )

    def _extract_product_json_ld(self, soup: BeautifulSoup) -> dict[str, Any]:
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        for script in scripts:
            raw = script.string or script.get_text(strip=True)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            candidates = data if isinstance(data, list) else [data]
            for candidate in candidates:
                found = self._find_product_json(candidate)
                if found:
                    return found
        return {}

    def _find_product_json(self, data: Any) -> dict[str, Any] | None:
        if isinstance(data, dict):
            type_value = data.get("@type")
            if type_value == "Product" or (isinstance(type_value, list) and "Product" in type_value):
                return data
            graph = data.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    found = self._find_product_json(item)
                    if found:
                        return found
        return None

    def _extract_meta(self, soup: BeautifulSoup) -> dict[str, str]:
        result: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            key = tag.get("property") or tag.get("name")
            value = tag.get("content")
            if key and value:
                result[key.strip()] = value.strip()
        return result

    def _extract_image(self, json_ld: dict[str, Any], meta: dict[str, str]) -> str | None:
        image = json_ld.get("image")
        if isinstance(image, list) and image:
            image = image[0]
        return self._first_non_empty(
            image if isinstance(image, str) else "",
            meta.get("og:image"),
            meta.get("twitter:image"),
        ) or None

    def _extract_price_and_currency(
        self,
        json_ld: dict[str, Any],
        meta: dict[str, str],
        text: str,
        fallback_currency: str,
    ) -> tuple[float, str]:
        offers = json_ld.get("offers")
        if isinstance(offers, list) and offers:
            offers = offers[0]

        if isinstance(offers, dict):
            price = self._safe_price(offers.get("price") or offers.get("lowPrice"))
            currency = str(offers.get("priceCurrency") or fallback_currency).upper()
            if price > 0:
                return price, currency

        meta_price = self._safe_price(
            self._first_non_empty(
                meta.get("product:price:amount"),
                meta.get("og:price:amount"),
                meta.get("twitter:data1"),
            )
        )
        meta_currency = self._first_non_empty(
            meta.get("product:price:currency"),
            meta.get("og:price:currency"),
            fallback_currency,
        ).upper()

        if meta_price > 0:
            return meta_price, meta_currency

        return self._extract_price_from_text(text, fallback_currency)

    def _extract_price_from_text(self, text: str, fallback_currency: str) -> tuple[float, str]:
        patterns = [
            r"(€|\$|£)\s*([0-9][0-9\.,]{0,12})",
            r"([0-9][0-9\.,]{0,12})\s*(EUR|USD|GBP|MAD|CNY|JPY)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            groups = match.groups()
            if groups[0] in CURRENCY_SYMBOLS:
                currency = CURRENCY_SYMBOLS.get(groups[0], fallback_currency)
                price = self._safe_price(groups[1])
            else:
                price = self._safe_price(groups[0])
                currency = CURRENCY_SYMBOLS.get(groups[1].upper(), fallback_currency)
            if price > 0:
                return price, currency
        return 0.0, fallback_currency

    def _extract_old_price(self, text: str, current_price: float) -> float | None:
        if current_price <= 0:
            return None
        prices = []
        for raw in re.findall(r"(?:€|\$|£)?\s*([0-9][0-9\.,]{1,12})", text[:3500]):
            price = self._safe_price(raw)
            if current_price < price < current_price * 6:
                prices.append(price)
        if not prices:
            return None
        candidate = max(prices)
        return candidate if candidate > current_price else None

    def _extract_specs(self, soup: BeautifulSoup, text: str) -> str:
        selectors = [
            "#feature-bullets",
            "#productDetails_techSpec_section_1",
            ".product-specs",
            ".specification",
            ".specifications",
            ".product-description",
            "#description",
            "[class*=description]",
            "[class*=spec]",
        ]
        chunks: list[str] = []
        for selector in selectors:
            for node in soup.select(selector)[:3]:
                clean = node.get_text(" ", strip=True)
                if clean and len(clean) > 40:
                    chunks.append(clean[:1400])
        if chunks:
            return " ".join(chunks)[:4000]
        return text[:1400]

    def _detect_dark_patterns(self, soup: BeautifulSoup, text: str) -> list[DarkPatternSignal]:
        candidates: list[tuple[str, str, str]] = []

        for node in soup.find_all(["span", "div", "p", "strong", "em", "button"]):
            clean = node.get_text(" ", strip=True)
            if not clean or len(clean) > 250:
                continue
            selector = node.get("id") or " ".join(node.get("class", [])[:3])
            candidates.append((clean, selector[:250], node.name or ""))

        candidates.append((text[:3000], "page_text", "body"))

        signals: list[DarkPatternSignal] = []
        seen: set[str] = set()

        for clean, selector, _tag in candidates:
            lower = clean.lower()
            for signal_type, patterns in DARK_PATTERN_PATTERNS.items():
                if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in patterns):
                    key = f"{signal_type}:{clean[:80].lower()}"
                    if key in seen:
                        continue
                    seen.add(key)
                    severity = {
                        "countdown_timer": 70,
                        "false_scarcity": 82,
                        "social_pressure": 55,
                        "forced_urgency": 60,
                    }.get(signal_type, 45)
                    signals.append(
                        DarkPatternSignal(
                            type=signal_type,
                            text=clean[:500],
                            selector=selector,
                            severity=severity,
                        )
                    )
                    break

        return sorted(signals, key=lambda item: item.severity, reverse=True)[:12]

    def _extract_dimensions(self, text: str) -> str:
        match = re.search(
            r"(\d+(?:[\.,]\d+)?)\s*[x×]\s*(\d+(?:[\.,]\d+)?)(?:\s*[x×]\s*(\d+(?:[\.,]\d+)?))?\s*(cm|mm|in|inch|inches)",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(0) if match else ""

    def _extract_weight_kg(self, text: str) -> float | None:
        match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|lb|lbs)", text, flags=re.IGNORECASE)
        if not match:
            return None
        amount = self._safe_price(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            return None
        if unit == "g":
            return round(amount / 1000, 3)
        if unit in {"lb", "lbs"}:
            return round(amount * 0.453592, 3)
        return round(amount, 3)

    def _first_non_empty(self, *values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            parsed = float(str(value).replace(",", "."))
            return parsed if parsed >= 0 else None
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value: Any) -> int | None:
        try:
            if value is None:
                return None
            parsed = int(float(str(value).replace(",", ".")))
            return parsed if parsed >= 0 else None
        except (ValueError, TypeError):
            return None

    def _safe_price(self, value: Any) -> float:
        if value is None:
            return 0.0
        raw = str(value).strip()
        raw = re.sub(r"[^0-9,\.]", "", raw)
        if not raw:
            return 0.0
        if "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            decimal = Decimal(raw)
            if decimal <= 0:
                return 0.0
            return float(round(decimal, 2))
        except (InvalidOperation, ValueError):
            return 0.0

    def _deep_get(self, data: dict[str, Any], path: list[str]) -> Any:
        current: Any = data
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _safe_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path[:80]}"


class ScraperService:
    """
    Orchestrates scraper strategies and caches identical URLs for 30 minutes.
    """

    def __init__(self) -> None:
        self.engine = PlaywrightEngine()
        self.strategies: list[ScraperStrategy] = [
            AmazonScraper(self.engine),
            AliExpressScraper(self.engine),
            GenericScraper(self.engine),
        ]
        self._cache: dict[str, CacheEntry] = {}
        self._cache_ttl_seconds = 30 * 60
        self._cache_lock = asyncio.Lock()

    async def extract_product(self, request: ProductExtractRequest) -> ExtractedProductResponse:
        url = str(request.url)
        cache_key = self._cache_key(request)
        cached = await self._get_cached(cache_key)
        if cached:
            cached.extractionNotes.append("Served from 30-minute in-memory cache.")
            return cached

        store = self.detect_store(url)
        strategy = self._strategy_for(url)

        try:
            result = await strategy.extract(request, store)
        except Exception as exc:
            logger.exception("Extraction failed for %s: %s", self._safe_url(url), exc)
            result = ExtractedProductResponse(
                title="",
                store=store.store,
                storeCountry=store.country,
                sellerLanguage=store.seller_language,
                currentPrice=0,
                oldPrice=None,
                baseCurrency=request.userCurrency,
                specs="",
                productUrl=url,
                extractionConfidence=0,
                extractionNotes=[
                    "Automatic extraction failed. The store may block bots, require cookies, or change page structure.",
                ],
            )

        await self._set_cached(cache_key, result)
        return result

    def detect_store(self, url: str) -> StoreInfo:
        host = (urlparse(url).hostname or "").lower()
        for marker, data in STORE_HINTS.items():
            if marker in host:
                return StoreInfo(*data)

        country = self._country_from_tld(host)
        lang = self._language_for_country(country)
        return StoreInfo(host.replace("www.", "") or "Unknown", country, lang)

    def _strategy_for(self, url: str) -> ScraperStrategy:
        for strategy in self.strategies:
            if strategy.can_handle(url):
                return strategy
        return self.strategies[-1]

    def _country_from_tld(self, host: str) -> str:
        if host.endswith(".es"):
            return "ES"
        if host.endswith(".fr"):
            return "FR"
        if host.endswith(".de"):
            return "DE"
        if host.endswith(".it"):
            return "IT"
        if host.endswith(".pt"):
            return "PT"
        if host.endswith(".ma"):
            return "MA"
        if host.endswith(".cn"):
            return "CN"
        if host.endswith(".co.uk") or host.endswith(".uk"):
            return "GB"
        return "US"

    def _language_for_country(self, country: str) -> str:
        return {
            "ES": "es",
            "FR": "fr",
            "DE": "de",
            "IT": "it",
            "PT": "pt",
            "MA": "ar",
            "CN": "en",
            "GB": "en",
            "US": "en",
        }.get(country, "en")

    async def _get_cached(self, key: str) -> ExtractedProductResponse | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            now = time.time()
            if not entry:
                return None
            if entry.expires_at <= now:
                self._cache.pop(key, None)
                return None
            return entry.value.model_copy(deep=True)

    async def _set_cached(self, key: str, value: ExtractedProductResponse) -> None:
        async with self._cache_lock:
            self._cache[key] = CacheEntry(
                value=value.model_copy(deep=True),
                expires_at=time.time() + self._cache_ttl_seconds,
            )

            if len(self._cache) > 500:
                now = time.time()
                expired = [cache_key for cache_key, entry in self._cache.items() if entry.expires_at <= now]
                for cache_key in expired:
                    self._cache.pop(cache_key, None)

                if len(self._cache) > 500:
                    for cache_key in list(self._cache.keys())[:100]:
                        self._cache.pop(cache_key, None)

    def _cache_key(self, request: ProductExtractRequest) -> str:
        raw = f"{request.url}|{request.userCountry}|{request.userCurrency}|{request.language}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _safe_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path[:80]}"


scraper_service = ScraperService()
