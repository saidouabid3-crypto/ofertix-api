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
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max docs to scan (default 500). Use --confirm-full-scan to remove cap.",
    )
    parser.add_argument(
        "--confirm-full-scan", action="store_true",
        help="DANGER: scan entire collection. Costs 1 read per document.",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    if not args.confirm_full_scan and args.limit <= 0:
        import sys
        print(
            "[ReadGuard] Refusing unbounded Firestore scan. "
            "Pass --limit N or --confirm-full-scan.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.confirm_full_scan:
        import sys
        print(
            "[ReadGuard] WARNING: --confirm-full-scan active. "
            "This will read the entire products collection.",
            file=sys.stderr,
        )

    scanned = 0
    matched = 0
    updated = 0
    already_hidden = 0
    batch = db.batch()
    batch_count = 0
    now = datetime.now(timezone.utc)
    issue = f"removed_{args.store.strip().lower().replace(' ', '_')}_store"

    _query = db.collection("products") if args.confirm_full_scan else db.collection("products").limit(args.limit)
    for doc in _query.stream():
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

        if not args.confirm_full_scan and args.limit and scanned >= args.limit:
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
