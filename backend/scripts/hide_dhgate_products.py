from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from firebase_admin import firestore

from core.firebase import db

PRODUCTS_COLLECTION = "products"
HIDDEN_REASON = "dhgate_removed_by_owner"
BATCH_LIMIT = 400
EXAMPLE_LIMIT = 12
DEFAULT_DHGATE_FEED = BASE_DIR / "data" / "impact_dhgate.txt"

DHGATE_PROGRAM_IDS = {
    # Known DHgate Impact program id used by the catalog importer tests and
    # the default DHgate feed. More ids are discovered from impact_dhgate.txt.
    "12108",
}

DHGATE_TEXT_FIELDS = (
    "store",
    "Store",
    "merchant",
    "Merchant",
    "provider",
    "Provider",
    "programName",
    "programNames",
    "Program Name",
    "Program Names",
    "sourceName",
    "source",
    "sourceType",
    "affiliateNetwork",
    "network",
    "catalogSource",
    "feedName",
    "feedPath",
    "sourceFile",
    "importSource",
    "priceSource",
)

DHGATE_URL_FIELDS = (
    "affiliateUrl",
    "affiliate_url",
    "productUrl",
    "product_url",
    "originalUrl",
    "original_url",
    "sourceUrl",
    "source_url",
    "url",
    "link",
)


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reasons: tuple[str, ...] = ()


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _compact(value: Any) -> str:
    return "".join(ch for ch in _text(value) if ch.isalnum())


def _decode_url_text(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return ""
    decoded = unquote(raw)
    try:
        parsed = urlparse(raw)
        return " ".join(part for part in (raw, decoded, parsed.netloc, parsed.path, parsed.query) if part)
    except Exception:
        return f"{raw} {decoded}"


def discover_dhgate_program_ids(feed_path: Path = DEFAULT_DHGATE_FEED) -> set[str]:
    """Best-effort local feed scan; never required for Firestore safety."""
    ids = set(DHGATE_PROGRAM_IDS)
    if not feed_path.exists():
        return ids

    try:
        with feed_path.open("r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
            reader = csv.DictReader(fh, delimiter=delimiter)
            for row in reader:
                program_id = str(
                    row.get("Program Id")
                    or row.get("Program ID")
                    or row.get("ProgramId")
                    or ""
                ).strip()
                program_name = _compact(
                    row.get("Program Names")
                    or row.get("Program Name")
                    or row.get("Merchant")
                    or row.get("Store")
                    or ""
                )
                if program_id and (not program_name or "dhgate" in program_name):
                    ids.add(program_id)
    except Exception:
        return ids
    return ids


def is_dhgate_product(
    data: dict[str, Any],
    *,
    doc_id: str = "",
    dhgate_program_ids: set[str] | None = None,
) -> MatchResult:
    reasons: list[str] = []
    ids = dhgate_program_ids or DHGATE_PROGRAM_IDS

    for field in DHGATE_TEXT_FIELDS:
        if "dhgate" in _compact(data.get(field)):
            reasons.append(f"{field}:dhgate")

    for field in DHGATE_URL_FIELDS:
        if "dhgate" in _decode_url_text(data.get(field)):
            reasons.append(f"{field}:dhgate_url")

    program_id = str(
        data.get("programId")
        or data.get("program_id")
        or data.get("Program Id")
        or data.get("Program ID")
        or ""
    ).strip()
    is_impact = _compact(data.get("source")) == "impact" or "impact" in _compact(
        data.get("importSource") or data.get("priceSource") or data.get("affiliateNetwork")
    )
    if program_id and program_id in ids and is_impact:
        reasons.append(f"impact_program_id:{program_id}")

    clean_doc_id = str(doc_id or data.get("id") or "").strip()
    if clean_doc_id.startswith("impact_"):
        parts = clean_doc_id.split("_", 2)
        if len(parts) >= 2 and parts[1] in ids:
            reasons.append(f"impact_doc_id_program:{parts[1]}")

    return MatchResult(bool(reasons), tuple(sorted(set(reasons))))


def is_already_hidden(data: dict[str, Any]) -> bool:
    status = _text(data.get("status"))
    return (
        data.get("active") is False
        and data.get("visibleToUsers") is False
        and status in {"hidden", "removed"}
        and data.get("hiddenReason") == HIDDEN_REASON
    )


def hide_update(data: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {
        "active": False,
        "isActive": False,
        "visibleToUsers": False,
        "publicVisible": False,
        "status": "hidden",
        "hiddenReason": HIDDEN_REASON,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "hiddenAt": firestore.SERVER_TIMESTAMP,
    }
    if data.get("status") != "hidden":
        update["previousStatusBeforeDhgateRemoval"] = data.get("status")
    if data.get("visibleToUsers") is not False:
        update["previousVisibleToUsersBeforeDhgateRemoval"] = data.get("visibleToUsers")
    return update


def _example(doc_id: str, data: dict[str, Any], reasons: Iterable[str]) -> dict[str, Any]:
    return {
        "id": doc_id,
        "name": str(data.get("name") or data.get("title") or data.get("fullTitle") or "")[:100],
        "store": str(data.get("store") or data.get("programName") or data.get("Program Names") or "")[:80],
        "source": str(data.get("source") or data.get("importSource") or "")[:80],
        "status": data.get("status"),
        "visibleToUsers": data.get("visibleToUsers"),
        "reasons": list(reasons),
    }


def scan_and_hide(
    docs: Iterable[Any],
    *,
    apply: bool,
    batch_factory: Any | None = None,
    dhgate_program_ids: set[str] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "totalProductsScanned": 0,
        "dhgateProductsMatched": 0,
        "productsThatWillBeHidden": 0,
        "productsHidden": 0,
        "alreadyHidden": 0,
        "productsSkipped": 0,
        "batchesCommitted": 0,
        "writesAttempted": 0,
        "examples": [],
    }

    batch = batch_factory() if apply and batch_factory is not None else None
    batch_count = 0

    for doc in docs:
        data = doc.to_dict() or {}
        doc_id = getattr(doc, "id", "") or data.get("id") or ""
        report["totalProductsScanned"] += 1
        match = is_dhgate_product(data, doc_id=str(doc_id), dhgate_program_ids=dhgate_program_ids)
        if not match.matched:
            report["productsSkipped"] += 1
            continue

        report["dhgateProductsMatched"] += 1
        if len(report["examples"]) < EXAMPLE_LIMIT:
            report["examples"].append(_example(str(doc_id), data, match.reasons))

        if is_already_hidden(data):
            report["alreadyHidden"] += 1
            report["productsSkipped"] += 1
            continue

        report["productsThatWillBeHidden"] += 1
        if not apply:
            continue

        if batch is None:
            raise RuntimeError("batch_factory is required when apply=True")
        batch.update(doc.reference, hide_update(data))
        batch_count += 1
        report["writesAttempted"] += 1
        report["productsHidden"] += 1

        if batch_count >= BATCH_LIMIT:
            batch.commit()
            report["batchesCommitted"] += 1
            batch = batch_factory()
            batch_count = 0

    if apply and batch is not None and batch_count:
        batch.commit()
        report["batchesCommitted"] += 1

    return report


def _query_products(limit: int | None) -> Any:
    query = db.collection(PRODUCTS_COLLECTION)
    if limit is not None:
        query = query.limit(limit)
    return query


def _visible_dhgate_count(dhgate_program_ids: set[str]) -> int | str:
    """Targeted post-apply check; returns an error string instead of failing report output."""
    try:
        probes = [
            db.collection(PRODUCTS_COLLECTION).where("store", "==", "DHgate").limit(20),
            db.collection(PRODUCTS_COLLECTION).where("programName", "==", "DHgate").limit(20),
            db.collection(PRODUCTS_COLLECTION).where("programId", "in", sorted(dhgate_program_ids)[:10]).limit(20),
        ]
        visible_ids: set[str] = set()
        for query in probes:
            for doc in query.stream():
                data = doc.to_dict() or {}
                if data.get("visibleToUsers") is not False and is_dhgate_product(
                    data,
                    doc_id=doc.id,
                    dhgate_program_ids=dhgate_program_ids,
                ).matched:
                    visible_ids.add(doc.id)
        return len(visible_ids)
    except Exception as exc:
        return f"verification_failed:{type(exc).__name__}:{exc}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Soft-hide DHgate Impact affiliate products from Firestore products."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Scan and report only; do not write.")
    mode.add_argument("--apply", action="store_true", help="Soft-hide matched DHgate products.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum products to scan.")
    parser.add_argument(
        "--skip-feed-program-id-discovery",
        action="store_true",
        help="Use only built-in DHgate Impact program IDs.",
    )
    parser.add_argument(
        "--verify-visible",
        action="store_true",
        help="After apply, scan visible products and report remaining visible DHgate matches.",
    )
    args = parser.parse_args()

    if db is None:
        raise RuntimeError("Firestore is not initialized. Check Firebase credentials.")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive when provided")

    apply = bool(args.apply)
    dhgate_program_ids = set(DHGATE_PROGRAM_IDS)
    if not args.skip_feed_program_id_discovery:
        dhgate_program_ids = discover_dhgate_program_ids()

    report = scan_and_hide(
        _query_products(args.limit).stream(),
        apply=apply,
        batch_factory=db.batch,
        dhgate_program_ids=dhgate_program_ids,
    )
    report["dryRunNoWrites"] = not apply
    report["dhgateProgramIds"] = sorted(dhgate_program_ids)
    report["matchRule"] = (
        "match DHgate in store/program/source/import/price metadata or URLs, "
        "or Impact doc/program id in discovered DHgate Impact program IDs"
    )

    if apply and args.verify_visible:
        report["remainingVisibleDhgateProducts"] = _visible_dhgate_count(dhgate_program_ids)

    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
