import re
from typing import Any, Dict, Optional, Tuple
from playwright.async_api import async_playwright

EUR_RE = re.compile(r"([0-9]+(?:[.,][0-9]{1,2})?)\s*€", re.IGNORECASE)
USD_RE = re.compile(r"(?:US\s*\$|\$)\s*([0-9]+(?:[.,][0-9]{1,2})?)", re.IGNORECASE)
MOQ_RE = re.compile(
    r"(?:min\.?\s*order|min(?:imum)?\s*order\s*quantity|moq)\D{0,40}(\d+)",
    re.IGNORECASE,
)


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", ".").strip())
    except Exception:
        return None


def _extract_price_after_marker(text: str, marker: str) -> Tuple[Optional[str], Optional[float]]:
    idx = text.lower().find(marker.lower())
    if idx == -1:
        return None, None

    block = text[idx : idx + 450]

    eur = EUR_RE.search(block)
    if eur:
        price = _to_float(eur.group(1))
        if price and price > 0:
            return "EUR", price

    usd = USD_RE.search(block)
    if usd:
        price = _to_float(usd.group(1))
        if price and price > 0:
            return "USD", price

    return None, None


def _all_prices(text: str):
    prices = []
    for m in EUR_RE.finditer(text):
        p = _to_float(m.group(1))
        if p and 0.5 <= p <= 100000:
            prices.append(("EUR", p))
    for m in USD_RE.finditer(text):
        p = _to_float(m.group(1))
        if p and 0.5 <= p <= 100000:
            prices.append(("USD", p))
    return prices


def _pick_current_price(text: str) -> Tuple[Optional[str], Optional[float]]:
    # DHgate غالباً كيعرض الثمن الصحيح جنب Total Cost.
    priority_markers = [
        "Total Cost",
        "Price includes VAT",
        "Buy Now",
        "Add to Cart",
        "Shipping Cost",
    ]

    for marker in priority_markers:
        cur, price = _extract_price_after_marker(text, marker)
        if price:
            return cur, price

    prices = _all_prices(text)
    if not prices:
        return None, None

    # fallback: ناخدو أصغر ثمن معقول، حيث الأعلى غالباً oldPrice أو bundle.
    valid = [(cur, p) for cur, p in prices if p >= 1]
    if not valid:
        return None, None
    valid.sort(key=lambda x: x[1])
    return valid[0]


def _pick_old_price(text: str, new_price: float) -> Optional[float]:
    prices = [p for _, p in _all_prices(text) if p > new_price]
    if not prices:
        return None
    # ناخدو أقرب ثمن أكبر من الجديد، ماشي أكبر ثمن فالصفحة كامل حيث ممكن يكون منتج آخر.
    prices.sort()
    return prices[0]


def _extract_moq(text: str) -> int:
    match = MOQ_RE.search(text)
    if match:
        try:
            qty = int(match.group(1))
            if 1 <= qty <= 10000:
                return qty
        except Exception:
            pass
    return 1


def _looks_blocked(text: str, title: str, url: str) -> bool:
    low = f"{title}\n{url}\n{text[:2000]}".lower()
    block_phrases = [
        "captcha",
        "access denied",
        "unusual traffic",
        "are you human",
        "robot check",
        "security check",
        "blocked",
    ]
    return any(p in low for p in block_phrases)


async def scrape_dhgate_price(url: str, product: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Dict[str, Any]:
    if not url:
        return {"success": False, "error": "Missing url", "priceAccuracy": "estimated"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = await browser.new_context(
            locale="es-ES",
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(9000)

            # نحاول نسكر popups إلا بان شي واحد.
            for selector in ["text=Accept", "text=Aceptar", "text=Agree", "button:has-text('OK')"]:
                try:
                    loc = page.locator(selector).first
                    if await loc.count() > 0:
                        await loc.click(timeout=1200)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

            text = await page.locator("body").inner_text(timeout=15000)
            current_url = page.url
            title = await page.title()

            if _looks_blocked(text, title, current_url):
                return {
                    "success": False,
                    "error": "DHgate blocked or verification page",
                    "priceAccuracy": "estimated",
                    "pageUrl": current_url,
                    "pageTitle": title,
                }

            currency, new_price = _pick_current_price(text)
            if not new_price:
                return {
                    "success": False,
                    "error": "No price found on page",
                    "priceAccuracy": "estimated",
                    "pageUrl": current_url,
                    "pageTitle": title,
                }

            old_price = _pick_old_price(text, new_price)
            moq = _extract_moq(text)

            result = {
                "success": True,
                "newPrice": round(float(new_price), 2),
                "currency": currency or (product or {}).get("currency") or "EUR",
                "minOrderQuantity": moq,
                "priceAccuracy": "live",
                "priceSource": "dhgate_page",
                "finalPriceInStore": True,
                "pageUrl": current_url,
                "pageTitle": title,
                "priceNote": (
                    "Precio actualizado desde DHgate. El precio final puede variar por cupones, "
                    "IVA, envío, país o cantidad mínima."
                ),
            }

            if old_price:
                result["oldPrice"] = round(float(old_price), 2)
                if old_price > new_price:
                    result["discount"] = round(((old_price - new_price) / old_price) * 100)

            return result

        except Exception as e:
            return {"success": False, "error": str(e), "priceAccuracy": "estimated"}

        finally:
            await context.close()
            await browser.close()


async def get_live_price(url: str, product: Optional[Dict[str, Any]] = None, *args, **kwargs) -> Dict[str, Any]:
    return await scrape_dhgate_price(url, product, *args, **kwargs)
