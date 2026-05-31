import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_PATH = BASE_DIR / "firebase_key.json"

if not firebase_admin._apps:
    cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
    firebase_admin.initialize_app(cred)

db = firestore.client()

COLLECTION = "products"


def is_aliexpress_product(data: dict) -> bool:
    source = str(data.get("source", "")).lower()
    store = str(data.get("store", "")).lower()
    product_url = str(data.get("productUrl", "")).lower()
    affiliate_url = str(data.get("affiliateUrl", "")).lower()
    name = str(data.get("name", "")).lower()

    keywords = [
        "aliexpress",
        "ali express",
        "aliexpress.com",
        "s.click.aliexpress",
    ]

    full_text = " ".join([source, store, product_url, affiliate_url, name])

    return any(keyword in full_text for keyword in keywords)


def main():
    docs = db.collection(COLLECTION).stream()

    matched_docs = []

    for doc in docs:
        data = doc.to_dict() or {}

        if is_aliexpress_product(data):
            matched_docs.append(doc)

    print(f"FOUND AliExpress products: {len(matched_docs)}")

    if not matched_docs:
        print("No AliExpress products found.")
        return

    confirm = input("Type DELETE to confirm deletion: ").strip()

    if confirm != "DELETE":
        print("Cancelled.")
        return

    batch = db.batch()
    count = 0

    for doc in matched_docs:
        batch.delete(doc.reference)
        count += 1

        if count % 450 == 0:
            batch.commit()
            batch = db.batch()
            print(f"Deleted {count} products...")

    batch.commit()

    print(f"Done. Deleted {count} AliExpress products.")


if __name__ == "__main__":
    main()