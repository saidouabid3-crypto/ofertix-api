import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from core.market_config import SUPPORTED_MARKETS, normalize_market
except Exception:
    SUPPORTED_MARKETS = {
        "es": {"currency": "EUR"},
        "ma": {"currency": "MAD"},
        "dz": {"currency": "DZD"},
        "fr": {"currency": "EUR"},
        "pt": {"currency": "EUR"},
        "it": {"currency": "EUR"},
        "de": {"currency": "EUR"},
        "uk": {"currency": "GBP"},
        "us": {"currency": "USD"},
        "ca": {"currency": "CAD"},
        "eg": {"currency": "EGP"},
        "sa": {"currency": "SAR"},
        "ae": {"currency": "AED"},
        "mx": {"currency": "MXN"},
    }

    def normalize_market(value: str) -> str:
        value = (value or "").strip().lower()
        aliases = {"gb": "uk", "en": "uk", "usa": "us", "morocco": "ma", "spain": "es"}
        return aliases.get(value, value if value in SUPPORTED_MARKETS else "es")


SUPPORTED_COUNTRIES = list(SUPPORTED_MARKETS.keys())

CATEGORY_MAP = {
    "watch": "fashion",
    "watches": "fashion",
    "jewelry": "fashion",
    "apparel": "fashion",
    "clothing": "fashion",
    "shoe": "fashion",
    "phone": "electronics",
    "phones": "electronics",
    "iphone": "electronics",
    "samsung": "electronics",
    "electronics": "electronics",
    "computer": "electronics",
    "laptop": "electronics",
    "beauty": "beauty",
    "health": "health",
    "fitness": "fitness",
    "gym": "fitness",
    "home": "home",
    "kitchen": "kitchen",
    "toy": "kids",
    "toys": "kids",
    "baby": "kids",
    "car": "auto",
    "automotive": "auto",
    "garden": "home",
    "tool": "tools",
    "bosch": "tools",
}

SHORT_NAME_STOP_PHRASES = [
    " for ",
    " with ",
    " compatible ",
    " waterproof ",
    " water proof ",
    " full touch ",
    " full screen ",
    " original ",
    " men ",
    " women ",
    " ladies ",
    " sports ",
    " sport ",
    " fitness ",
    " heart rate ",
    " blood pressure ",
    " answer call ",
    " custom dial ",
    " android ",
    " ios ",
    " iphone ",
    " huawei ",
    " xiaomi ",
    " samsung ",
    " apple watch ",
    " nfc ",
    " gps ",
    " ip67 ",
    " ip68 ",
    " new ",
    " cheap ",
    " best selling ",
    " hot sale ",
    " 2023 ",
    " 2024 ",
    " 2025 ",
    " 2026 ",
]

SHORT_NAME_REPLACEMENTS = {
    "smart watches": "Smart Watch",
    "smart watch": "Smart Watch",
    "smartwatch": "Smart Watch",
    "reloj inteligente": "Smart Watch",
    "wireless headphones": "Wireless Headphones",
    "bluetooth headphones": "Bluetooth Headphones",
    "bluetooth earphones": "Bluetooth Earphones",
    "wristbands": "Wristband",
    "wristband": "Wristband",
    "bracelet": "Bracelet",
    "bluetooth call": "Bluetooth Call",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "nan", "n/a", "undefined"}:
        return ""
    return re.sub(r"\s+", " ", text)


def clean_price(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = clean_text(value)
    if not text:
        return default

    # 1.234,56 -> 1234.56 ; 1,234.56 -> 1234.56
    text = text.replace("€", "").replace("$", "").replace("£", "")
    text = text.replace("USD", "").replace("EUR", "").replace("GBP", "")
    text = text.strip()

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")

    text = re.sub(r"[^0-9.]", "", text)

    try:
        return round(float(text), 2)
    except Exception:
        return default


def clean_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(clean_price(value, default)))
    except Exception:
        return default


def make_short_product_name(full_name: str, max_words: int = 5, max_chars: int = 45) -> str:
    text = clean_text(full_name)
    if not text:
        return "Producto destacado"

    lower = text.lower()
    for old, new in SHORT_NAME_REPLACEMENTS.items():
        if old in lower:
            text = re.sub(re.escape(old), new, text, count=1, flags=re.IGNORECASE)
            break

    lower = text.lower()
    cut_positions = []
    for phrase in SHORT_NAME_STOP_PHRASES:
        pos = lower.find(phrase)
        if pos > 8:
            cut_positions.append(pos)

    if cut_positions:
        text = text[: min(cut_positions)].strip()

    text = re.sub(r"[^A-Za-z0-9À-ÿ\s\-\+\.]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])

    if len(text) > max_chars:
        text = text[:max_chars].strip()

    if len(text) < 3:
        return "Producto destacado"

    return text


def normalize_country_list(values: Any, fallback: str = "global") -> List[str]:
    if values is None:
        values = []

    if isinstance(values, str):
        if values.lower().strip() == "global":
            return SUPPORTED_COUNTRIES
        values = [v.strip() for v in re.split(r"[,|;/\s]+", values) if v.strip()]

    normalized: List[str] = []

    for value in values:
        value = clean_text(value)
        if not value:
            continue
        if value.lower() == "global":
            return SUPPORTED_COUNTRIES
        code = normalize_market(value)
        if code in SUPPORTED_MARKETS and code not in normalized:
            normalized.append(code)

    if normalized:
        return normalized

    if fallback == "global":
        return SUPPORTED_COUNTRIES

    code = normalize_market(fallback)
    return [code] if code in SUPPORTED_MARKETS else ["es"]


def guess_category(*parts: Any) -> str:
    raw = " ".join(clean_text(p).lower() for p in parts if clean_text(p))
    for key, category in CATEGORY_MAP.items():
        if key in raw:
            return category
    return "deals"


def calculate_discount(old_price: float, new_price: float, given_discount: int = 0) -> int:
    if given_discount and given_discount > 0:
        return int(given_discount)
    if old_price and new_price and old_price > new_price:
        return int(round(((old_price - new_price) / old_price) * 100))
    return 0


def stable_product_id(prefix: str, *parts: Any) -> str:
    useful_parts = [clean_text(p) for p in parts if clean_text(p)]
    raw = "|".join(useful_parts)
    if not raw:
        raw = utc_now_iso()
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def normalize_product(raw: Dict[str, Any], *, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    نقطة مركزية لكل importers ديال Ofertix.

    أي importer جديد يعطي raw product فقط، وهذه الدالة كتخرج نفس schema:
    - name/title قصيرين للـ UI
    - fullTitle و description فيهم التفاصيل الطويلة
    - countries / priceAccuracy / visibility موحدين
    """
    defaults = defaults or {}
    data = {**defaults, **(raw or {})}

    full_title = clean_text(
        data.get("fullTitle")
        or data.get("longTitle")
        or data.get("product_title")
        or data.get("title")
        or data.get("name")
    )

    short_name = clean_text(data.get("shortName")) or make_short_product_name(full_title)

    description = clean_text(data.get("description"))
    if not description:
        description = full_title

    image = clean_text(data.get("image") or data.get("imageUrl") or data.get("thumbnail"))
    affiliate_url = clean_text(data.get("affiliateUrl") or data.get("promotionLink") or data.get("url"))
    product_url = clean_text(data.get("productUrl") or data.get("originalUrl") or data.get("detailUrl"))

    new_price = clean_price(data.get("newPrice") or data.get("price") or data.get("salePrice"))
    old_price = clean_price(data.get("oldPrice") or data.get("originalPrice") or data.get("regularPrice"))
    if old_price <= 0:
        old_price = new_price

    discount = calculate_discount(old_price, new_price, clean_int(data.get("discount")))

    store = clean_text(data.get("store")) or "Unknown"
    source = clean_text(data.get("source")) or "manual"
    category_name = clean_text(data.get("categoryName"))
    category_path = clean_text(data.get("categoryPath"))
    category = clean_text(data.get("category")) or guess_category(category_name, category_path, full_title, description, store)

    country_code = clean_text(data.get("countryCode") or data.get("country") or "global").lower()
    if country_code not in {"global", ""}:
        country_code = normalize_market(country_code)
    else:
        country_code = "global"

    available_countries = normalize_country_list(
        data.get("availableCountries") or data.get("shipsTo"),
        fallback=country_code,
    )

    currency = clean_text(data.get("currency"))
    if not currency:
        if country_code != "global" and country_code in SUPPORTED_MARKETS:
            currency = SUPPORTED_MARKETS[country_code].get("currency", "EUR")
        else:
            currency = "EUR"

    price_source = clean_text(data.get("priceSource"))
    price_accuracy = clean_text(data.get("priceAccuracy"))
    if not price_accuracy:
        if source in {"impact", "feed"} or "dhgate" in store.lower():
            price_accuracy = "estimated"
            price_source = price_source or "affiliate_feed"
        elif source in {"api", "official_api"}:
            price_accuracy = "live"
            price_source = price_source or "official_api"
        else:
            price_accuracy = "estimated"
            price_source = price_source or source

    stock = clean_text(data.get("stockAvailability") or data.get("stock") or "InStock")
    in_stock = stock.lower() not in {"outofstock", "out of stock", "false", "no", "sold out"}

    admin_issues = []
    if not full_title:
        admin_issues.append("Missing title")
    if not image.startswith("http"):
        admin_issues.append("Missing image")
    if new_price <= 0:
        admin_issues.append("Missing price")
    if not (affiliate_url.startswith("http") or product_url.startswith("http")):
        admin_issues.append("Missing product link")
    if not in_stock:
        admin_issues.append("Out of stock")
    if discount < int(data.get("minimumDiscount", 0) or 0):
        admin_issues.append("Discount too low")

    forced_status = clean_text(data.get("status"))
    if forced_status:
        status = forced_status
    else:
        status = "needs_market_review" if admin_issues else "active"

    visible = bool(data.get("visibleToUsers")) if "visibleToUsers" in data else status in {"active", "approved", "published"}

    product = {
        # UI clean fields
        "name": short_name,
        "title": short_name,
        "fullTitle": full_title,
        "description": description,

        # Media
        "image": image,
        "additionalImages": data.get("additionalImages") or data.get("images") or "",

        # Price
        "newPrice": new_price,
        "oldPrice": old_price,
        "discount": discount,
        "currency": currency,
        "priceAccuracy": price_accuracy,
        "priceSource": price_source,
        "finalPriceInStore": bool(data.get("finalPriceInStore", price_accuracy == "estimated")),
        "priceNote": clean_text(data.get("priceNote"))
        or (
            "Precio aproximado. El precio final se confirma en la tienda."
            if price_accuracy == "estimated"
            else "Precio actualizado desde la fuente del proveedor."
        ),

        # Store/source
        "store": store,
        "source": source,
        "affiliateNetwork": clean_text(data.get("affiliateNetwork")),
        "affiliateUrl": affiliate_url,
        "productUrl": product_url,

        # Category
        "category": category,
        "categoryName": category_name or category,
        "categoryPath": category_path,

        # Market
        "countryCode": country_code,
        "country": country_code,
        "availableCountries": available_countries,
        "shipsTo": data.get("shipsTo") or available_countries,
        "marketType": clean_text(data.get("marketType"))
        or ("international" if country_code == "global" or len(available_countries) > 1 else "local"),
        "shippingConfidence": clean_text(data.get("shippingConfidence")) or ("medium" if country_code == "global" else "high"),
        "deliveryCheckStatus": clean_text(data.get("deliveryCheckStatus")),

        # Visibility / quality
        "language": clean_text(data.get("language")) or "en",
        "status": status,
        "visibleToUsers": visible,
        "adminIssue": clean_text(data.get("adminIssue")) or "; ".join(admin_issues),
        "stockAvailability": stock,
        "isOnline": bool(data.get("isOnline", True)),
        "isHot": bool(data.get("isHot", discount >= 40)),
        "featured": bool(data.get("featured", discount >= 50)),
        "sponsored": bool(data.get("sponsored", False)),

        # Metrics
        "views": int(data.get("views") or 0),
        "clicks": int(data.get("clicks") or 0),
        "sales": int(data.get("sales") or 0),

        # Dates
        "updatedAt": utc_now_iso(),
    }

    # Preserve useful source-specific fields without forcing each importer to duplicate schema logic.
    preserve_keys = [
        "sku",
        "programId",
        "catalogId",
        "productId",
        "asin",
        "ean",
        "brand",
        "commissionMin",
        "commissionMax",
        "commissionCurrency",
        "lastUpdatedFromFeed",
        "importedAt",
        "minOrderQuantity",
    ]

    for key in preserve_keys:
        if key in data and data.get(key) not in [None, ""]:
            product[key] = data.get(key)

    if "importedAt" not in product:
        product["importedAt"] = utc_now_iso()

    return product


def product_is_valid_for_users(product: Dict[str, Any]) -> bool:
    return (
        product.get("status") in {"active", "approved", "published"}
        and product.get("visibleToUsers") is True
        and clean_text(product.get("image")).startswith("http")
        and clean_price(product.get("newPrice")) > 0
        and (
            clean_text(product.get("affiliateUrl")).startswith("http")
            or clean_text(product.get("productUrl")).startswith("http")
        )
    )
