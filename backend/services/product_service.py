from core.firebase import db


def save_product(product: dict):
    db.collection("products").add(product)