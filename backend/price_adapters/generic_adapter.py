import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class LivePriceResult:
    ok: bool
    new_price: Optional[float] = None
    old_price: Optional[float] = None
    currency: Optional[str] = None
    discount: Optional[int] = None
    source: str = "generic_page"
    error: str = ""


def _normalize_price(raw: str) -> Optional[float]:
    if not raw:
        return None
    value = raw.strip().replace("\xa0", " ")
    value = re.sub(r"[^0-9,\.]", "", value)
    if not value:
        return None

    # 1,234.56 => 1234.56 | 1.234,56 => 1234.56 | 54,42 => 54.42
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")

    try:
        price = float(value)
        if price <= 0 or price > 100000:
            return None
        return round(price, 2)
    except Exception:
        return None


def _detect_currency(text: str, url: str = "") -> str:
    t = f"{text} {url}".upper()
    if "€" in t or " EUR" in t:
        return "EUR"
    if "$" in t or " USD" in t:
        return "USD"
    if "£" in t or " GBP" in t:
        return "GBP"
    return "USD"


def _extract_prices_from_text(text: str) -> list[float]:
    if not text:
        return []

    patterns = [
        r"(?:€|\$|£)\s*([0-9][0-9\.,]*)",
        r"([0-9][0-9\.,]*)\s*(?:€|\$|£|EUR|USD|GBP)",
    ]
    prices: list[float] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            price = _normalize_price(m.group(1))
            if price is not None:
                prices.append(price)

    # remove duplicated prices while preserving order
    seen = set()
    cleaned = []
    for p in prices:
        key = round(p, 2)
        if key not in seen:
            seen.add(key)
            cleaned.append(key)
    return cleaned


def calculate_discount(old_price: Optional[float], new_price: Optional[float]) -> int:
    if not old_price or not new_price or old_price <= new_price:
        return 0
    return max(0, min(99, round(((old_price - new_price) / old_price) * 100)))


async def scrape_generic_price(page, url: str) -> LivePriceResult:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3500)

        text = await page.locator("body").inner_text(timeout=10000)
        title = await page.title()
        currency = _detect_currency(text, url)
        prices = _extract_prices_from_text(text)

        if not prices:
            return LivePriceResult(ok=False, currency=currency, error="No price found on page")

        # Generic fallback: use the smallest visible price as current price and the largest reasonable price as old price.
        new_price = min(prices)
        old_candidates = [p for p in prices if p > new_price]
        old_price = max(old_candidates) if old_candidates else new_price
        discount = calculate_discount(old_price, new_price)

        return LivePriceResult(
            ok=True,
            new_price=new_price,
            old_price=old_price,
            currency=currency,
            discount=discount,
            source="generic_page",
        )
    except Exception as exc:
        return LivePriceResult(ok=False, error=str(exc))
