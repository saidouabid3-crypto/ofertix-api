import os
import time
import hashlib
import requests

from dotenv import load_dotenv

from core.firebase import db
from utils.product_normalizer import clean_price, normalize_product

load_dotenv()

APP_KEY = os.getenv("ALIEXPRESS_APP_KEY")
APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")
TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID")


def sign_params(params):
    raw = APP_SECRET or ""
    for key in sorted(params.keys()):
        raw += key + str(params[key])
    raw += APP_SECRET or ""
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def import_aliexpress(keyword="iphone", limit=30, ship_to_country="ES", currency="EUR", language="EN"):
    print("AliExpress importer started")

    if not APP_KEY or not APP_SECRET:
        print("AliExpress error: missing API keys in .env")
        return {"imported": 0, "skipped": 0}

    market = (ship_to_country or "ES").lower()

    params = {
        "app_key": APP_KEY,
        "method": "aliexpress.affiliate.product.query",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "keywords": keyword,
        "page_no": 1,
        "page_size": limit,
        "target_currency": currency,
        "target_language": language,
        "ship_to_country": ship_to_country.upper(),
        "tracking_id": TRACKING_ID or "",
    }

    params["sign"] = sign_params(params)

    try:
        response = requests.get(
            "https://api-sg.aliexpress.com/sync",
            params=params,
            timeout=60,
        )

        print("AliExpress status:", response.status_code)
        data = response.json()

        result = data.get("aliexpress_affiliate_product_query_response", {})
        products_data = result.get("resp_result", {}).get("result", {})
        products = products_data.get("products", {}).get("product", [])

        imported = 0
        skipped = 0

        for item in products:
            title = item.get("product_title", "")
            image = item.get("product_main_image_url", "")
            link = item.get("promotion_link") or item.get("product_detail_url", "")
            product_url = item.get("product_detail_url", "")
            price = clean_price(item.get("target_sale_price"))
            old_price = clean_price(item.get("target_original_price"))
            product_id = str(item.get("product_id", ""))

            raw_product = {
                "productId": product_id,
                "fullTitle": title,
                "description": item.get("product_small_image_urls") or title,
                "image": image,
                "newPrice": price,
                "oldPrice": old_price,
                "store": "AliExpress",
                "source": "aliexpress",
                "affiliateNetwork": "aliexpress",
                "affiliateUrl": link,
                "productUrl": product_url,
                "category": keyword,
                "categoryName": keyword,
                "countryCode": market,
                "availableCountries": [market],
                "shipsTo": [market],
                "currency": currency,
                "language": language.lower(),
                "priceAccuracy": "estimated",
                "priceSource": "aliexpress_affiliate_api",
                "finalPriceInStore": True,
                "deliveryCheckStatus": "api_ship_to_country",
                "shippingConfidence": "high",
                "minimumDiscount": 0,
            }

            product = normalize_product(raw_product)

            if product["status"] != "active":
                skipped += 1
                continue

            doc_id = f"aliexpress_{product_id}" if product_id else None

            if doc_id:
                db.collection("products").document(doc_id).set(product, merge=True)
            else:
                db.collection("products").add(product)

            imported += 1

        print(f"Imported {imported} AliExpress products")
        print(f"Skipped {skipped} AliExpress products")
        return {"imported": imported, "skipped": skipped}

    except Exception as e:
        print("AliExpress importer error:", e)
        return {"imported": 0, "skipped": 0, "error": str(e)}
