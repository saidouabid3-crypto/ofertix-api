"""
Import affiliate banner ads from a CSV exported by your affiliate network into Firestore.

Usage from backend root:
    python -m scripts.import_ads_csv --csv "C:\Users\HP-PROBOOK\Downloads\Ads (9).csv"

Requirements:
    firebase-admin installed
    firebase_key.json present in backend root
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore


BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_PATH = BASE_DIR / "firebase_key.json"


def _init_firestore() -> firestore.Client:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def _safe_key(value: str) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unknown"


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _parse_datetime(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    # Keep ISO text from affiliate network. Firestore can store string safely.
    return raw


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _row_to_ad(row: dict[str, Any]) -> dict[str, Any]:
    ad_id = _clean(row.get("AdId"))
    name = _clean(row.get("Name"))
    program_id = _clean(row.get("ProgramId"))

    tracking_link = _clean(row.get("TrackingLink"))
    landing_page = _clean(row.get("LandingPage"))

    return {
        "adId": ad_id,
        "programId": program_id,
        "state": _clean(row.get("State")) or "ACTIVE",
        "title": name,
        "description": _clean(row.get("Description")),
        "type": _clean(row.get("AdType")) or "BANNER",
        "hostedBy": _clean(row.get("HostedBy")),
        "creativeName": _clean(row.get("Creative")),
        "iabAdUnit": _clean(row.get("IabAdUnit")),
        "width": int(float(row.get("ThirdPartyServableAdCreativeWidth") or 0)),
        "height": int(float(row.get("ThirdPartyServableAdCreativeHeight") or 0)),
        "language": _clean(row.get("Language")),
        "landingPage": landing_page,
        # Always open trackingLink first for affiliate attribution.
        "trackingLink": tracking_link or landing_page,
        "allowDeepLinking": _parse_bool(row.get("AllowDeepLinking")),
        "startDate": _parse_datetime(row.get("LimitedTimeStartDate")),
        "endDate": _parse_datetime(row.get("LimitedTimeEndDate")),
        "isActive": (_clean(row.get("State")).upper() == "ACTIVE") and bool(tracking_link or landing_page),
        "source": "affiliate_csv",
        "network": "dhgate",
        "placement": "home_top",
        "priority": 100,
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }


def import_ads(csv_path: Path, dry_run: bool = False) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    db = _init_firestore()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    print(f"Rows found: {len(rows)}")

    imported = 0
    for row in rows:
        ad = _row_to_ad(row)
        if not ad["adId"]:
            print("Skipped row without AdId")
            continue

        doc_id = f'{_safe_key(ad["network"])}_{ad["adId"]}'
        print(f'{"DRY " if dry_run else ""}UPSERT ads/{doc_id}: {ad["title"]}')

        if not dry_run:
            db.collection("ads").document(doc_id).set(ad, merge=True)

        imported += 1

    print(f"Done. Imported/updated: {imported}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Path to the ads CSV file")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Firestore")
    args = parser.parse_args()

    import_ads(Path(args.csv), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
