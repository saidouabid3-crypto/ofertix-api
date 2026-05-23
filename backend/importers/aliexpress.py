import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv
from core.firebase import db

load_dotenv()

APP_KEY = os.getenv("ALIEXPRESS_APP_KEY")
APP_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")
TRACKING_ID = os.getenv("ALIEXPRESS_TRACKING_ID")


def clean_price(value):
    try:
        if value is None:
            return 0.0
        value = str(value).replace("€", "").replace("$", "").replace(",", ".")
        return float("".join(c for c in value if c.isdigit() or c == "."))
    except:
        return 0.0


def sign_params(params):
    raw = APP_SECRET
    for key in sorted(params.keys()):
        raw += key + str(params[key])
    raw += APP_SECRET
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def import_aliexpress(keyword="iphone", limit=30):
    print("AliExpress importer started")

    if not APP_KEY or not APP_SECRET:
        print("AliExpress error: missing API keys in .env")
        return

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
        "target_currency": "EUR",
        "target_language": "EN",
        "ship_to_country": "ES",
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

        for item in products:
            title = item.get("product_title", "")
            image = item.get("product_main_image_url", "")
            link = item.get("promotion_link") or item.get("product_detail_url", "")
            price = clean_price(item.get("target_sale_price"))
            old_price = clean_price(item.get("target_original_price"))

            if not title or not image or price <= 0 or not link:
                continue

            discount = 0
            if old_price > price:
                discount = round(((old_price - price) / old_price) * 100)

            product_id = str(item.get("product_id", ""))

            product = {
                "name": title,
                "description": title,
                "image": image,
                "newPrice": price,
                "oldPrice": old_price,
                "discount": discount,
                "store": "AliExpress",
                "category": keyword,
                "affiliateUrl": link,
                "country": "global",
                "isHot": discount >= 20,
                "isOnline": True,
                "featured": False,
                "sponsored": False,
                "views": 0,
                "clicks": 0,
                "sales": 0,
                "source": "aliexpress",
            }

            if product_id:
                db.collection("products").document(f"aliexpress_{product_id}").set(product, merge=True)
            else:
                db.collection("products").add(product)

            imported += 1

        print(f"Imported {imported} AliExpress products")

    except Exception as e:
        print("AliExpress importer error:", e)