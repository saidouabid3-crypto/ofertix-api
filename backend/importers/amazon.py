import os
import re
import hashlib
import requests

from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv

from core.firebase import db
from utils.product_normalizer import clean_price, clean_text, normalize_product

load_dotenv()

ZENROWS_API_KEY = os.getenv("ZENROWS_API_KEY")
AMAZON_TAG = os.getenv("AMAZON_TAG", "hydesnav-21")


def extract_title(item):
    for field in ["title", "name", "product_title", "productName"]:
        value = clean_text(item.get(field))
        if len(value) > 5:
            return value
    return ""


def extract_image(item):
    for field in ["image", "image_url", "thumbnail", "thumbnail_url", "main_image", "img", "picture"]:
        value = item.get(field)

        if isinstance(value, dict):
            value = value.get("url") or value.get("src") or ""

        value = clean_text(value)

        if value.startswith("//"):
            value = "https:" + value

        if value.startswith("http"):
            return value

    return ""


def extract_link(item):
    for field in ["url", "link", "product_url", "href"]:
        value = clean_text(item.get(field))

        if value.startswith("/"):
            value = urljoin("https://www.amazon.es", value)

        if "amazon." in value:
            return value

    return ""


def add_amazon_tag(link: str) -> str:
    link = clean_text(link)
    if not link or "amazon." not in link or not AMAZON_TAG:
        return link

    try:
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        query["tag"] = [AMAZON_TAG]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception:
        sep = "&" if "?" in link else "?"
        return f"{link}{sep}tag={AMAZON_TAG}"


def make_product_id(title, link):
    raw = f"{title}-{link}".lower()
    return "amazon_" + hashlib.md5(raw.encode()).hexdigest()


def save_product(product):
    product_id = make_product_id(product["fullTitle"], product["affiliateUrl"])
    db.collection("products").document(product_id).set(product, merge=True)


def import_amazon(keyword="iphone", country="es", limit=40):
    print("Amazon importer started")

    if not ZENROWS_API_KEY:
        print("Amazon error: missing ZENROWS_API_KEY in .env")
        return {"imported": 0, "skipped": 0}

    country = (country or "es").lower()
    domain = "www.amazon.es" if country == "es" else "www.amazon.com"
    url = f"https://{domain}/s?k={keyword}"

    params = {
        "url": url,
        "apikey": ZENROWS_API_KEY,
        "js_render": "true",
        "premium_proxy": "true",
        "autoparse": "true",
    }

    try:
        response = requests.get(
            "https://api.zenrows.com/v1/",
            params=params,
            timeout=120
        )

        print("Amazon status:", response.status_code)

        if response.status_code != 200:
            print(response.text[:500])
            return {"imported": 0, "skipped": 0, "error": response.text[:500]}

        data = response.json()
        products = data if isinstance(data, list) else data.get("products", [])

        print(f"Raw products: {len(products)}")

        imported = 0
        skipped = 0

        for item in products[:limit]:
            title = extract_title(item)
            image = extract_image(item)
            link = extract_link(item)
            affiliate_link = add_amazon_tag(link)

            price = clean_price(
                item.get("price")
                or item.get("sale_price")
                or item.get("current_price")
            )

            old_price = clean_price(
                item.get("old_price")
                or item.get("original_price")
            )

            raw_product = {
                "fullTitle": title,
                "description": title,
                "image": image,
                "newPrice": price,
                "oldPrice": old_price,
                "store": "Amazon",
                "source": "amazon",
                "affiliateNetwork": "amazon_associates",
                "affiliateUrl": affiliate_link,
                "productUrl": link,
                "category": "technology",
                "categoryName": keyword,
                "countryCode": country,
                "availableCountries": [country],
                "shipsTo": [country],
                "currency": "EUR" if country in {"es", "fr", "de", "it", "pt"} else "USD",
                "language": "es" if country == "es" else "en",
                "priceAccuracy": "estimated",
                "priceSource": "amazon_scraper",
                "finalPriceInStore": True,
                "shippingConfidence": "high",
                "deliveryCheckStatus": "store_country_domain",
                "minimumDiscount": 0,
            }

            product = normalize_product(raw_product)

            if product["status"] != "active":
                skipped += 1
                continue

            save_product(product)
            imported += 1

        print(f"Imported {imported} clean Amazon products")
        print(f"Skipped {skipped} Amazon products")
        return {"imported": imported, "skipped": skipped}

    except Exception as e:
        print("Amazon importer error:", e)
        return {"imported": 0, "skipped": 0, "error": str(e)}
