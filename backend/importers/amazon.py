import os
import re
import hashlib
import requests

from urllib.parse import urljoin
from dotenv import load_dotenv

from core.firebase import db

load_dotenv()

ZENROWS_API_KEY = os.getenv("ZENROWS_API_KEY")
AMAZON_TAG = os.getenv("AMAZON_TAG", "hydesnav-21")


def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def clean_price(value):
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value)

    value = value.replace("€", "")
    value = value.replace("$", "")
    value = value.replace(",", ".")
    value = re.sub(r"[^0-9.]", "", value)

    try:
        return float(value)
    except:
        return 0.0


def extract_title(item):

    fields = [
        "title",
        "name",
        "product_title",
        "productName"
    ]

    for field in fields:

        value = clean_text(item.get(field))

        if len(value) > 5:
            return value

    return ""


def extract_image(item):

    fields = [
        "image",
        "image_url",
        "thumbnail",
        "thumbnail_url",
        "main_image",
        "img",
        "picture",
    ]

    for field in fields:

        value = item.get(field)

        if isinstance(value, dict):
            value = (
                value.get("url")
                or value.get("src")
                or ""
            )

        value = clean_text(value)

        if value.startswith("//"):
            value = "https:" + value

        if value.startswith("http"):
            return value

    return ""


def extract_link(item):

    fields = [
        "url",
        "link",
        "product_url",
        "href",
    ]

    for field in fields:

        value = clean_text(item.get(field))

        if value.startswith("/"):
            value = urljoin(
                "https://www.amazon.es",
                value
            )

        if "amazon." in value:
            return value

    return ""


def make_product_id(title, link):

    raw = f"{title}-{link}".lower()

    return hashlib.md5(
        raw.encode()
    ).hexdigest()


def save_product(product):

    product_id = make_product_id(
        product["name"],
        product["affiliateUrl"]
    )

    db.collection("products").document(product_id).set(
        product,
        merge=True
    )


def import_amazon():

    print("Amazon importer started")

    url = "https://www.amazon.es/s?k=iphone"

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
            return

        data = response.json()

        if isinstance(data, list):
            products = data

        else:
            products = data.get("products", [])

        print(f"Raw products: {len(products)}")

        imported = 0

        for item in products:

            title = extract_title(item)

            image = extract_image(item)

            link = extract_link(item)

            price = clean_price(
                item.get("price")
                or item.get("sale_price")
                or item.get("current_price")
            )

            old_price = clean_price(
                item.get("old_price")
                or item.get("original_price")
            )

            # STRICT FILTER
            if not title:
                continue

            if len(title) < 8:
                continue

            if not image.startswith("http"):
                continue

            if price <= 0:
                continue

            if "amazon." not in link:
                continue

            discount = 0

            if old_price > price:
                discount = round(
                    ((old_price - price) / old_price) * 100
                )

            product = {

                "name": title,

                "description": title,

                "image": image,

                "newPrice": price,

                "oldPrice": old_price,

                "discount": discount,

                "store": "Amazon",

                "category": "technology",

                "affiliateUrl": link,

                "country": "es",

                "isHot": discount >= 15,

                "isOnline": True,

                "featured": False,

                "sponsored": False,

                "views": 0,

                "clicks": 0,

                "sales": 0,
            }

            save_product(product)

            imported += 1

        print(f"Imported {imported} clean Amazon products")

    except Exception as e:

        print("Amazon importer error:", e)