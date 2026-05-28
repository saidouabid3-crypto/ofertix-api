import csv
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

from core.firebase import db
from core.market_config import SUPPORTED_MARKETS, normalize_market

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FEED_PATH = BASE_DIR / "data" / "impact_dhgate.txt"

# Override من .env إلا بغيتي:
# IMPACT_FEED_PATH=C:/Users/HP-PROBOOK/deal_bot/backend/data/impact_dhgate.txt
# IMPACT_IMPORT_LIMIT=200
IMPACT_FEED_PATH = Path(os.getenv("IMPACT_FEED_PATH", str(DEFAULT_FEED_PATH)))
IMPACT_IMPORT_LIMIT = int(os.getenv("IMPACT_IMPORT_LIMIT", "200"))

# DHgate marketplace دولي، ولكن ما عندناش shipping-country field واضح داخل feed.
# لذلك كنخليوها Medium confidence، والفلترة كتخدم بالبلدان المدعومة ديال Ofertix.
DEFAULT_DHGATE_COUNTRIES = [
    "es", "ma", "dz", "fr", "pt", "it", "de", "uk", "us", "ca", "eg", "sa", "ae", "mx"
]

CATEGORY_MAP = {
    "watches": "fashion",
    "jewelry": "fashion",
    "apparel": "fashion",
    "clothing": "fashion",
    "phone": "electronics",
    "phones": "electronics",
    "electronics": "electronics",
    "computer": "electronics",
    "beauty": "beauty",
    "health": "health",
    "fitness": "fitness",
    "home": "home",
    "kitchen": "kitchen",
    "toys": "kids",
    "automotive": "auto",
}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "nan", "n/a"}:
        return ""
    return text


def clean_price(value) -> float:
    text = clean_text(value)
    if not text:
        return 0.0
    text = text.replace(",", ".")
    text = re.sub(r"[^0-9.]", "", text)
    try:
        return round(float(text), 2)
    except Exception:
        return 0.0


def clean_int(value) -> int:
    try:
        return int(round(clean_price(value)))
    except Exception:
        return 0


def normalize_country_list(countries: list[str]) -> list[str]:
    normalized = []
    for country in countries:
        code = normalize_market(country)
        if code in SUPPORTED_MARKETS and code not in normalized:
            normalized.append(code)
    return normalized


def extract_original_url(affiliate_url: str) -> str:
    affiliate_url = clean_text(affiliate_url)
    if not affiliate_url:
        return ""
    try:
        parsed = urlparse(affiliate_url)
        query = parse_qs(parsed.query)
        if query.get("u"):
            return unquote(query["u"][0])
    except Exception:
        pass
    return ""


def guess_category(category_name: str, category_path: str, name: str) -> str:
    raw = f"{category_name} {category_path} {name}".lower()
    for key, value in CATEGORY_MAP.items():
        if key in raw:
            return value
    return "deals"


def stable_doc_id(program_id: str, sku: str, name: str, affiliate_url: str) -> str:
    sku = clean_text(sku)
    program_id = clean_text(program_id)
    if sku and program_id:
        return f"impact_{program_id}_{sku}"
    raw = f"{program_id}-{sku}-{name}-{affiliate_url}".encode("utf-8")
    return "impact_" + hashlib.md5(raw).hexdigest()


def build_impact_product(row: dict) -> dict | None:
    sku = clean_text(row.get("Sku"))
    program_id = clean_text(row.get("Program Id"))
    catalog_id = clean_text(row.get("Catalog Id"))
    store = clean_text(row.get("Program Names")) or "Impact"

    name = clean_text(row.get("Name"))
    description = clean_text(row.get("Description")) or name
    image = clean_text(row.get("Image Url"))
    affiliate_url = clean_text(row.get("Url"))
    product_url = clean_text(row.get("Original Url")) or extract_original_url(affiliate_url)

    new_price = clean_price(row.get("Current Price"))
    old_price = clean_price(row.get("Original Price"))
    discount = clean_int(row.get("Discount Percentage"))

    category_name = clean_text(row.get("Category Name"))
    category_path = clean_text(row.get("Category Path"))
    currency = clean_text(row.get("Currency")) or "USD"
    stock = clean_text(row.get("Stock Availability"))

    if not name or not image.startswith("http") or not affiliate_url.startswith("http") or new_price <= 0:
        return None

    if old_price <= 0:
        old_price = new_price

    if discount <= 0 and old_price > new_price:
        discount = round(((old_price - new_price) / old_price) * 100)

    in_stock = stock.lower() in {"instock", "in stock", "available", "true", "yes"} or not stock

    status = "active" if in_stock and discount >= 5 else "needs_market_review"
    visible = status == "active"

    admin_issue = ""
    if not in_stock:
        admin_issue = "Out of stock or unknown stock status"
    elif discount < 5:
        admin_issue = "Discount too low"

    available_countries = normalize_country_list(DEFAULT_DHGATE_COUNTRIES)

    return {
        "sku": sku,
        "programId": program_id,
        "catalogId": catalog_id,
        "name": name,
        "description": description,
        "image": image,
        "additionalImages": clean_text(row.get("Additional ImageUrls")),
        "newPrice": new_price,
        "oldPrice": old_price,
        "discount": discount,
        "currency": currency,
        "store": store,
        "source": "impact",
        "affiliateNetwork": "impact",
        "affiliateUrl": affiliate_url,
        "productUrl": product_url,
        "category": guess_category(category_name, category_path, name),
        "categoryName": category_name,
        "categoryPath": category_path,

        # مهم: Ofertix ماشي Spain فقط. هذا منتج international marketplace.
        "countryCode": "global",
        "country": "global",
        "availableCountries": available_countries,
        "shipsTo": available_countries,
        "marketType": "international",
        "shippingConfidence": "medium",
        "deliveryCheckStatus": "assumed_international_marketplace",
        "pickupOnly": False,

        "language": clean_text(row.get("Language Locale")) or "en",
        "status": status,
        "visibleToUsers": visible,
        "adminIssue": admin_issue,
        "stockAvailability": stock or "InStock",
        "isOnline": True,
        "isHot": discount >= 40,
        "featured": discount >= 50,
        "sponsored": False,
        "views": 0,
        "clicks": 0,
        "sales": 0,
        "commissionMin": clean_price(row.get("Min Commission Percentage")),
        "commissionMax": clean_price(row.get("Max Commission Percentage")),
        "commissionCurrency": clean_text(row.get("Commission Currency")),
        "lastUpdatedFromFeed": clean_text(row.get("Last Updated")),
        "importedAt": datetime.now(timezone.utc).isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def import_impact(feed_path: str | None = None, limit: int | None = None):
    path = Path(feed_path) if feed_path else IMPACT_FEED_PATH
    max_items = limit or IMPACT_IMPORT_LIMIT

    print("Impact importer started")
    print("Feed:", path)
    print("Limit:", max_items)

    if not path.exists():
        print(f"Impact importer skipped: feed file not found: {path}")
        print("Put the feed here: backend/data/impact_dhgate.txt")
        return

    imported = 0
    active = 0
    review = 0
    skipped = 0
    batch_count = 0
    batch = db.batch()

    with path.open("r", encoding="utf-8", errors="replace", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")

        for row in reader:
            if imported >= max_items:
                break

            product = build_impact_product(row)
            if not product:
                skipped += 1
                continue

            doc_id = stable_doc_id(
                product.get("programId", ""),
                product.get("sku", ""),
                product.get("name", ""),
                product.get("affiliateUrl", ""),
            )

            doc_ref = db.collection("products").document(doc_id)
            batch.set(doc_ref, product, merge=True)

            imported += 1
            batch_count += 1

            if product["status"] == "active":
                active += 1
            else:
                review += 1

            if batch_count >= 400:
                batch.commit()
                batch = db.batch()
                batch_count = 0

    if batch_count:
        batch.commit()

    print("Impact importer finished")
    print("Imported:", imported)
    print("Active:", active)
    print("Needs review:", review)
    print("Skipped:", skipped)
