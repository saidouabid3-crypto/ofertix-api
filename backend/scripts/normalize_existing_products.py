from __future__ import annotations

import argparse
from core.firebase import db
from utils.product_standard import normalize_product


def main():
    parser = argparse.ArgumentParser(description='Normalize existing Ofertix products with Product Standard v1.')
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print('Normalize existing products started')
    print('Limit:', args.limit)
    print('Dry run:', args.dry_run)
    updated = 0
    skipped = 0
    for doc in db.collection('products').limit(args.limit).stream():
        data = doc.to_dict() or {}
        normalized = normalize_product(data)
        if args.dry_run:
            updated += 1
            continue
        doc.reference.set(normalized, merge=True)
        updated += 1
    print('Normalize existing products finished')
    print('Updated:', updated)
    print('Skipped:', skipped)


if __name__ == '__main__':
    main()
