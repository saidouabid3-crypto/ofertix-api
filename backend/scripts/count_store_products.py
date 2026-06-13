import argparse
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


def main():
    parser = argparse.ArgumentParser(description="Count products for a store/source in Firestore.")
    parser.add_argument("--store", required=True, help="Store name, e.g. AliExpress, DHgate")
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max docs to scan (default 500). Use --confirm-full-scan to remove cap.",
    )
    parser.add_argument(
        "--confirm-full-scan", action="store_true",
        help="DANGER: scan entire collection. Costs 1 read per document.",
    )
    args = parser.parse_args()

    if not args.confirm_full_scan and args.limit <= 0:
        import sys
        print(
            "[ReadGuard] Refusing unbounded Firestore scan. "
            "Pass --limit N or --confirm-full-scan.",
            file=sys.stderr,
        )
        sys.exit(1)

    scanned = 0
    matched = 0
    visible = 0
    active = 0
    archived = 0
    missing_store = 0

    _query = db.collection("products") if args.confirm_full_scan else db.collection("products").limit(args.limit)
    for doc in _query.stream():
        scanned += 1
        data = doc.to_dict() or {}
        if not data.get("store"):
            missing_store += 1

        if matches_store(data, args.store):
            matched += 1
            if data.get("visibleToUsers") is True:
                visible += 1
            if _text(data.get("status")) == "active":
                active += 1
            if _text(data.get("status")) == "archived":
                archived += 1

        if not args.confirm_full_scan and args.limit and scanned >= args.limit:
            break

    print(f"Scanned: {scanned}")
    print(f"Matched store/source/url: {matched}")
    print(f"Visible: {visible}")
    print(f"Active: {active}")
    print(f"Archived: {archived}")
    print(f"Missing store field: {missing_store}")


if __name__ == "__main__":
    main()
