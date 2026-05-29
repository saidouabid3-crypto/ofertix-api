"""
Normaliza المنتجات القديمة اللي كاينة فـ Firestore بدون ما تبدل importers.
Useful after adding utils/product_normalizer.py.

Run:
python -m scripts.normalize_existing_products --limit 500
"""

import argparse

from core.firebase import db
from utils.product_normalizer import normalize_product


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Normalize existing products started")
    print("Limit:", args.limit)
    print("Dry run:", args.dry_run)

    docs = list(db.collection("products").limit(args.limit).stream())

    updated = 0
    skipped = 0

    for doc in docs:
        old = doc.to_dict() or {}
        normalized = normalize_product(old)

        update_data = {
            "name": normalized["name"],
            "title": normalized["title"],
            "fullTitle": normalized["fullTitle"],
            "description": normalized["description"],
            "category": normalized["category"],
            "categoryName": normalized["categoryName"],
            "countryCode": normalized["countryCode"],
            "country": normalized["country"],
            "availableCountries": normalized["availableCountries"],
            "shipsTo": normalized["shipsTo"],
            "priceAccuracy": normalized["priceAccuracy"],
            "priceSource": normalized["priceSource"],
            "finalPriceInStore": normalized["finalPriceInStore"],
            "priceNote": normalized["priceNote"],
            "status": normalized["status"],
            "visibleToUsers": normalized["visibleToUsers"],
            "adminIssue": normalized["adminIssue"],
            "updatedAt": normalized["updatedAt"],
        }

        if args.dry_run:
            print(doc.id, "=>", update_data["name"], "|", update_data["status"])
        else:
            db.collection("products").document(doc.id).set(update_data, merge=True)

        updated += 1

    print("Normalize existing products finished")
    print("Updated:", updated)
    print("Skipped:", skipped)


if __name__ == "__main__":
    main()
