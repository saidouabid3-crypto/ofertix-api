import argparse
from datetime import datetime, timezone
from firebase_admin import firestore
from core.firebase import db


def _text(value):
    return str(value or "").strip().lower()


def matches_store(data: dict, store_query: str) -> bool:
    target = _text(store_query)
    store = _text(data.get("store"))
    source = _text(data.get("source"))
    merchant = _text(data.get("merchant"))
    provider = _text(data.get("provider"))
    product_url = _text(data.get("productUrl") or data.get("url"))
    affiliate_url = _text(data.get("affiliateUrl"))

    if target in {"aliexpress", "ali express"}:
        return source == "aliexpress" or "aliexpress" in store or store.startswith("ae-")

    if target in store or store in target:
        return True
    if target in source or source in target:
        return True
    if target in merchant or target in provider:
        return True

    compact = target.replace(" ", "")
    if compact and (compact in product_url or compact in affiliate_url):
        return True

    return False


def commit_batch(batch, count):
    if count:
        batch.commit()


def main():
    parser = argparse.ArgumentParser(
        description="Safely hide all products from one store/source in Firestore without deleting them."
    )
    parser.add_argument("--store", default="AliExpress", help="Store/source to hide. Defaults to AliExpress.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Only count matched docs, do not update")
    parser.add_argument("--apply", action="store_true", help="Archive matched docs. Without this flag the script is dry-run only.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max docs to scan")
    args = parser.parse_args()
    dry_run = not args.apply

    scanned = 0
    matched = 0
    updated = 0
    already_hidden = 0
    batch = db.batch()
    batch_count = 0
    now = datetime.now(timezone.utc)
    issue = f"removed_{args.store.strip().lower().replace(' ', '_')}_store"

    for doc in db.collection("products").stream():
        scanned += 1
        data = doc.to_dict() or {}

        if matches_store(data, args.store):
            matched += 1

            if data.get("visibleToUsers") is False and _text(data.get("status")) == "archived":
                already_hidden += 1
            else:
                if not dry_run:
                    batch.update(doc.reference, {
                        "visibleToUsers": False,
                        "status": "archived",
                        "adminIssue": issue,
                        "archivedReason": issue,
                        "archivedAt": firestore.SERVER_TIMESTAMP,
                        "updatedAt": firestore.SERVER_TIMESTAMP,
                        "previousStatus": data.get("status"),
                        "previousVisibleToUsers": data.get("visibleToUsers"),
                        "hiddenByScriptAt": now.isoformat(),
                    })
                    batch_count += 1
                    updated += 1

                    if batch_count >= 400:
                        commit_batch(batch, batch_count)
                        batch = db.batch()
                        batch_count = 0
                else:
                    updated += 1

        if args.limit and scanned >= args.limit:
            break

    if not dry_run:
        commit_batch(batch, batch_count)

    print(f"Scanned: {scanned}")
    print(f"Matched: {matched}")
    print(f"Already hidden: {already_hidden}")
    if dry_run:
        print(f"Would hide: {updated}")
    else:
        print(f"Hidden/archived now: {updated}")
    print("Done")


if __name__ == "__main__":
    main()
