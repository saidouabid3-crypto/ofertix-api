from __future__ import annotations

import argparse
from core.firebase import db
from services.product_intelligence_service import ProductIntelligenceService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--only-review', action='store_true')
    args = parser.parse_args()
    service = ProductIntelligenceService(db)
    docs = db.collection('products').limit(args.limit).stream()
    checked = active = review = 0
    for doc in docs:
        data = doc.to_dict() or {}
        if args.only_review:
            status = str(data.get('status') or '').lower()
            country = str(data.get('countryCode') or data.get('country') or '').lower()
            category = str(data.get('category') or data.get('categoryId') or '').lower()
            if status == 'active' and country not in {'','global','unknown'} and category not in {'','unknown','other','general'}:
                continue
        classified = service.classify(data, strict=True)
        update = {k: classified.get(k) for k in ['store','storeDomain','countryCode','country','availableCountries','marketConfidence','marketInferenceReason','category','categoryId','subcategory','subcategoryId','categoryConfidence','categoryInferenceReason','qualityScore','qualityIssues','status','adminIssue','visibleToUsers'] if classified.get(k) is not None}
        checked += 1
        if classified.get('status') == 'active': active += 1
        else: review += 1
        print(f"{doc.id}: status={classified.get('status')} market={classified.get('countryCode')} category={classified.get('category')} score={classified.get('qualityScore')} issues={classified.get('qualityIssues')}")
        if args.apply:
            doc.reference.update(update)
    print('\nSUMMARY')
    print(f'checked={checked}')
    print(f'active={active}')
    print(f'review={review}')
    print(f'applied={args.apply}')

if __name__ == '__main__':
    main()
