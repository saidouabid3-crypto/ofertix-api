import csv
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from dotenv import load_dotenv

from core.firebase import db
from utils.product_normalizer import (
    SUPPORTED_COUNTRIES,
    clean_int,
    clean_price,
    clean_text,
    normalize_country_list,
    normalize_product,
    stable_product_id,
)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FEED_PATH = BASE_DIR / "data" / "impact_dhgate.txt"

# Override من .env إلا بغيتي:
# IMPACT_FEED_PATH=C:/Users/HP-PROBOOK/deal_bot/backend/data/impact_dhgate.txt
# IMPACT_IMPORT_LIMIT=200
IMPACT_FEED_PATH = Path(os.getenv("IMPACT_FEED_PATH", str(DEFAULT_FEED_PATH)))
IMPACT_IMPORT_LIMIT = int(os.getenv("IMPACT_IMPORT_LIMIT", "200"))

DEFAULT_DHGATE_COUNTRIES = [
    "es", "ma", "dz", "fr", "pt", "it", "de", "uk", "us", "ca", "eg", "sa", "ae", "mx"
]


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


def build_impact_product(row: dict) -> dict | None:
    sku = clean_text(row.get("Sku"))
    program_id = clean_text(row.get("Program Id"))
    catalog_id = clean_text(row.get("Catalog Id"))
    store = clean_text(row.get("Program Names")) or "Impact"

    full_title = clean_text(row.get("Name"))
    feed_description = clean_text(row.get("Description"))
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

    if not full_title or not image.startswith("http") or not affiliate_url.startswith("http") or new_price <= 0:
        return None

    available_countries = normalize_country_list(DEFAULT_DHGATE_COUNTRIES, fallback="global")

    raw_product = {
        "sku": sku,
        "programId": program_id,
        "catalogId": catalog_id,
        "fullTitle": full_title,
        "description": feed_description or full_title,
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
        "categoryName": category_name,
        "categoryPath": category_path,

        # Ofertix multi-country. DHgate marketplace دولي، لكن بثقة متوسطة.
        "countryCode": "global",
        "country": "global",
        "availableCountries": available_countries,
        "shipsTo": available_countries,
        "marketType": "international",
        "shippingConfidence": "medium",
        "deliveryCheckStatus": "assumed_international_marketplace",
        "pickupOnly": False,

        "language": clean_text(row.get("Language Locale")) or "en",
        "stockAvailability": stock or "InStock",
        "minimumDiscount": 5,
        "priceAccuracy": "estimated",
        "priceSource": "impact_feed",
        "finalPriceInStore": True,
        "priceNote": (
            "Precio aproximado desde el feed de afiliación. "
            "El precio final se confirma en la tienda."
        ),
        "commissionMin": clean_price(row.get("Min Commission Percentage")),
        "commissionMax": clean_price(row.get("Max Commission Percentage")),
        "commissionCurrency": clean_text(row.get("Commission Currency")),
        "lastUpdatedFromFeed": clean_text(row.get("Last Updated")),
    }

    return normalize_product(raw_product)


def impact_doc_id(product: dict) -> str:
    program_id = clean_text(product.get("programId"))
    sku = clean_text(product.get("sku"))

    if program_id and sku:
        return f"impact_{program_id}_{sku}"

    return stable_product_id(
        "impact",
        program_id,
        sku,
        product.get("fullTitle"),
        product.get("affiliateUrl"),
    )


def import_impact(feed_path: str | None = None, limit: int | None = None):
    path = Path(feed_path) if feed_path else IMPACT_FEED_PATH
    max_items = limit or IMPACT_IMPORT_LIMIT

    print("Impact importer started")
    print("Feed:", path)
    print("Limit:", max_items)

    if not path.exists():
        print(f"Impact importer skipped: feed file not found: {path}")
        print("Put the feed here: backend/data/impact_dhgate.txt")
        return {"imported": 0, "active": 0, "needs_review": 0, "skipped": 0}

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

            doc_ref = db.collection("products").document(impact_doc_id(product))
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

    return {"imported": imported, "active": active, "needs_review": review, "skipped": skipped}


if __name__ == "__main__":
    import_impact()
