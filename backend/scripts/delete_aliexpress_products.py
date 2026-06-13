"""
Delete AliExpress products from Firestore.

SAFETY: Full collection scans are blocked by default.
Use --limit N to scan at most N documents.
Use --confirm-full-scan to override (requires explicit acknowledgement of read cost).
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import firebase_admin
from firebase_admin import credentials, firestore

SERVICE_ACCOUNT_PATH = BASE_DIR / "firebase_key.json"

if not firebase_admin._apps:
    cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
    firebase_admin.initialize_app(cred)

db = firestore.client()

COLLECTION = "products"
_DEFAULT_LIMIT = 500


def is_aliexpress_product(data: dict) -> bool:
    source = str(data.get("source", "")).lower()
    store = str(data.get("store", "")).lower()
    product_url = str(data.get("productUrl", "")).lower()
    affiliate_url = str(data.get("affiliateUrl", "")).lower()
    name = str(data.get("name", "")).lower()

    keywords = ["aliexpress", "ali express", "aliexpress.com", "s.click.aliexpress"]
    full_text = " ".join([source, store, product_url, affiliate_url, name])
    return any(keyword in full_text for keyword in keywords)


def main():
    parser = argparse.ArgumentParser(description="Delete AliExpress products from Firestore.")
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=f"Max docs to scan (default {_DEFAULT_LIMIT}). Use --confirm-full-scan to remove cap.",
    )
    parser.add_argument(
        "--confirm-full-scan", action="store_true",
        help="DANGER: scan the entire collection. Costs 1 read per document.",
    )
    args = parser.parse_args()

    if not args.confirm_full_scan and args.limit <= 0:
        print(
            "[ReadGuard] Refusing unbounded Firestore scan. "
            "Pass --limit N or --confirm-full-scan.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.confirm_full_scan:
        print(
            "[ReadGuard] WARNING: --confirm-full-scan active. "
            "This will read the entire products collection and consume Firestore quota.",
            file=sys.stderr,
        )
        query = db.collection(COLLECTION)
    else:
        print(f"[ReadGuard] Scanning at most {args.limit} documents.", file=sys.stderr)
        query = db.collection(COLLECTION).limit(args.limit)

    matched_docs = []
    scanned = 0
    for doc in query.stream():
        scanned += 1
        if is_aliexpress_product(doc.to_dict() or {}):
            matched_docs.append(doc)

    print(f"Scanned: {scanned}")
    print(f"Found AliExpress products: {len(matched_docs)}")

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
