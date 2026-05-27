from __future__ import annotations

import argparse
from typing import Any, Dict

from core.firebase import db
from utils.country_intelligence import GLOBAL_CODES, normalize_country

COUNTRY_MARKERS = {
    'amazon es': 'es', 'amazon.es': 'es', 'mediamarkt': 'es', 'pccomponentes': 'es', 'carrefour es': 'es',
    'amazon fr': 'fr', 'amazon.fr': 'fr', 'cdiscount': 'fr', 'fnac': 'fr',
    'amazon de': 'de', 'amazon.de': 'de',
    'amazon it': 'it', 'amazon.it': 'it',
    'amazon uk': 'uk', 'amazon.co.uk': 'uk',
    'amazon us': 'us', 'amazon.com': 'us', 'walmart us': 'us', 'bestbuy us': 'us',
    'amazon ca': 'ca', 'amazon.ca': 'ca', 'walmart ca': 'ca', 'bestbuy ca': 'ca',
    'jumia ma': 'ma', 'jumia maroc': 'ma', 'jumia morocco': 'ma',
    'jumia dz': 'dz', 'jumia algeria': 'dz',
    'jumia eg': 'eg', 'amazon eg': 'eg', 'noon eg': 'eg',
    'noon sa': 'sa', 'amazon sa': 'sa',
    'noon ae': 'ae', 'amazon ae': 'ae',
    'mercado libre mx': 'mx', 'mercadolibre mx': 'mx', 'amazon mx': 'mx',
}


def infer_country(data: Dict[str, Any]) -> str:
    explicit = normalize_country(
        data.get('countryCode') or data.get('country_code') or data.get('storeCountry') or data.get('country') or ''
    )
    if explicit and explicit not in GLOBAL_CODES:
        return explicit

    haystack = ' '.join(
        str(data.get(key, '') or '').lower()
        for key in ['source', 'store', 'provider', 'affiliateUrl', 'url', 'productUrl', 'marketplace']
    )
    for marker, country in COUNTRY_MARKERS.items():
        if marker in haystack:
            return country
    return 'global'


def main() -> None:
    parser = argparse.ArgumentParser(description='Clean Ofertix product market fields.')
    parser.add_argument('--limit', type=int, default=500, help='Max products to scan.')
    parser.add_argument('--apply', action='store_true', help='Write changes. Without this, dry-run only.')
    args = parser.parse_args()

    scanned = 0
    updated = 0
    hidden = 0

    for doc in db.collection('products').limit(args.limit).stream():
        scanned += 1
        data = doc.to_dict() or {}
        country = infer_country(data)

        update: Dict[str, Any] = {}
        if country not in GLOBAL_CODES:
            update['countryCode'] = country
            update['country'] = country
            update['availableCountries'] = data.get('availableCountries') or [country]
            update.setdefault('shipsTo', data.get('shipsTo') or [])
        else:
            # Do not show unclear products in production feeds until source/country is fixed.
            update['status'] = data.get('status') or 'needs_market_review'
            update['adminIssue'] = 'missing_country_source'
            hidden += 1

        if update:
            updated += 1
            print(f"{doc.id}: {update}")
            if args.apply:
                doc.reference.set(update, merge=True)

    mode = 'APPLIED' if args.apply else 'DRY RUN'
    print(f"{mode}: scanned={scanned} updated={updated} needs_review={hidden}")


if __name__ == '__main__':
    main()
