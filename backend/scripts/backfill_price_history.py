"""
Backfill price history for existing products.

Records one price_history point per product that has a valid price.
Safe to re-run — dedupe via deterministic document ID prevents duplicate writes
for the same product/price/day.

Usage:
    cd backend
    python scripts/backfill_price_history.py
    python scripts/backfill_price_history.py --dry-run
    python scripts/backfill_price_history.py --limit 100
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

import os  # noqa: E402 — must come after path setup

from dotenv import load_dotenv

# Load backend/.env regardless of the working directory the script is invoked from.
load_dotenv(_BACKEND_DIR / ".env")

# Point firebase_admin at the key file using an absolute path so the script
# works whether invoked from backend/ or from the repo root.
if not os.getenv("FIREBASE_KEY_PATH") and not os.getenv("FIREBASE_CREDENTIALS_JSON"):
    _key = _BACKEND_DIR / "firebase_key.json"
    if _key.exists():
        os.environ["FIREBASE_KEY_PATH"] = str(_key)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill_price_history")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill price history for all products."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing to Firestore.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of products to process (default: 500).",
    )
    args = parser.parse_args()

    from core.firebase import db
    from services.price_history_collector_service import (
        _parse_price,
        price_history_collector_service,
    )

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info("Backfill started [%s] — limit=%d", mode, args.limit)

    try:
        docs = list(db.collection("products").limit(args.limit).stream())
    except Exception as exc:
        logger.error("Failed to fetch products: %s", exc)
        return

    logger.info("Found %d products to process", len(docs))

    checked = recorded = skipped = errors = 0

    for doc in docs:
        checked += 1
        data = doc.to_dict() or {}
        pid = doc.id
        name = str(data.get("name") or "")[:60]
        currency = str(data.get("currency") or "EUR")

        try:
            if args.dry_run:
                price = _parse_price(
                    data.get("newPrice") or data.get("price") or data.get("currentPrice")
                )
                if price > 0:
                    logger.info(
                        "[DRY] Would record: %s | %.2f %s | %s",
                        pid, price, currency, name,
                    )
                    recorded += 1
                else:
                    logger.debug("[DRY] Skip (no valid price): %s | %s", pid, name)
                    skipped += 1
            else:
                result = price_history_collector_service.record(
                    product_id=pid,
                    data=data,
                    reason="backfill",
                )
                if result["recorded"]:
                    recorded += 1
                    logger.debug(
                        "Recorded: %s | %.2f %s",
                        pid, result["price"], currency,
                    )
                else:
                    skipped += 1
                    logger.debug(
                        "Skipped: %s | reason=%s", pid, result["reason"]
                    )
        except Exception as exc:
            errors += 1
            logger.warning("Error for %s: %s", pid, exc)

    print("\n=== Backfill Price History ===")
    print(f"  Mode     : {mode}")
    print(f"  Checked  : {checked}")
    print(f"  Recorded : {recorded}")
    print(f"  Skipped  : {skipped}")
    print(f"  Errors   : {errors}")
    print("==============================\n")


if __name__ == "__main__":
    main()
