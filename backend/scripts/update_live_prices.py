import argparse
import asyncio
from datetime import datetime, timezone

from core.firebase import db
from services.live_price_service import fetch_live_price

try:
    from google.cloud.firestore_v1.base_query import FieldFilter
except Exception:  # fallback for older firebase package
    FieldFilter = None


def _where(query, field, op, value):
    if FieldFilter:
        return query.where(filter=FieldFilter(field, op, value))
    return query.where(field, op, value)


def get_products(limit: int, store: str, source: str):
    query = db.collection("products")
    query = _where(query, "status", "==", "active")
    query = _where(query, "source", "==", source)

    if store:
        query = _where(query, "store", "==", store)

    return list(query.limit(limit).stream())


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--store", type=str, default="DHgate")
    parser.add_argument("--source", type=str, default="impact")
    args = parser.parse_args()

    print("Live price updater started")
    print("Limit:", args.limit)
    print("Store:", args.store)
    print("Source:", args.source)

    docs = get_products(args.limit, args.store, args.source)
    print("Found:", len(docs))

    updated = 0
    failed = 0

    for index, doc in enumerate(docs, start=1):
        product = doc.to_dict() or {}
        name = (product.get("name") or "")[:90]
        print(f"[{index}/{len(docs)}] Checking: {name}")

        try:
            result = await fetch_live_price(product)

            if result.get("success") is True:
                min_qty = int(result.get("minOrderQuantity") or 1)

                update_data = {
                    "newPrice": result.get("newPrice"),
                    "currency": result.get("currency", product.get("currency", "EUR")),
                    "priceAccuracy": result.get("priceAccuracy", "live"),
                    "priceSource": result.get("priceSource", "dhgate_page"),
                    "finalPriceInStore": result.get("finalPriceInStore", True),
                    "priceLastCheckedAt": datetime.now(timezone.utc).isoformat(),
                    "priceNote": result.get("priceNote", ""),
                    "minOrderQuantity": min_qty,
                    "livePricePageUrl": result.get("pageUrl") or product.get("productUrl"),
                    "livePriceError": "",
                }

                if result.get("oldPrice"):
                    update_data["oldPrice"] = result.get("oldPrice")
                if result.get("discount") is not None:
                    update_data["discount"] = result.get("discount")
                    update_data["isHot"] = result.get("discount", 0) >= 40

                # فقط إلا DHgate قال صراحة min order أكثر من 1 نخفيه للمراجعة.
                if min_qty > 1:
                    update_data["status"] = "needs_market_review"
                    update_data["visibleToUsers"] = False
                    update_data["adminIssue"] = f"Minimum order quantity is {min_qty}"

                db.collection("products").document(doc.id).set(update_data, merge=True)

                print(f"   OK: {update_data['newPrice']} {update_data['currency']} | MOQ: {min_qty}")
                updated += 1

            else:
                db.collection("products").document(doc.id).set(
                    {
                        "priceAccuracy": "estimated",
                        "priceSource": "impact_feed",
                        "finalPriceInStore": True,
                        "priceLastCheckedAt": datetime.now(timezone.utc).isoformat(),
                        "livePriceError": result.get("error", "Unknown error"),
                    },
                    merge=True,
                )
                print("   FAIL:", result.get("error", "Unknown error"))
                failed += 1

        except Exception as e:
            db.collection("products").document(doc.id).set(
                {
                    "priceAccuracy": "estimated",
                    "priceSource": "impact_feed",
                    "finalPriceInStore": True,
                    "priceLastCheckedAt": datetime.now(timezone.utc).isoformat(),
                    "livePriceError": str(e),
                },
                merge=True,
            )
            print("   ERROR:", str(e))
            failed += 1

    print("Live price updater finished")
    print("Updated live:", updated)
    print("Failed/estimated:", failed)


if __name__ == "__main__":
    asyncio.run(main())
