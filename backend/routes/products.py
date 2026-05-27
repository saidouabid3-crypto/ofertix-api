from fastapi import APIRouter, Query
from core.firebase import db
from utils.country_intelligence import enrich_country_fields, item_matches_country, normalize_country

router = APIRouter()


@router.get('/products')
def get_products(
    country: str = Query(default='es'),
    limit: int = Query(50, ge=1, le=100),
    category: str | None = None,
    q: str | None = None,
):
    requested_country = normalize_country(country)
    docs = db.collection('products').limit(800).get()

    results = []
    query_text = (q or '').strip().lower()
    category_text = (category or '').strip().lower()

    for doc in docs:
        item = enrich_country_fields(doc.to_dict() or {})
        item['id'] = doc.id

        status = str(item.get('status') or item.get('state') or 'active').lower()
        if status not in {'active', 'approved', 'published'}:
            continue

        if not item_matches_country(item, requested_country):
            continue

        if category_text and str(item.get('category') or '').lower() != category_text:
            continue

        if query_text:
            haystack = ' '.join([
                str(item.get('name') or item.get('title') or ''),
                str(item.get('description') or ''),
                str(item.get('store') or ''),
                str(item.get('category') or ''),
            ]).lower()
            if query_text not in haystack:
                continue

        results.append(item)
        if len(results) >= limit:
            break

    return {
        'country': requested_country,
        'count': len(results),
        'products': results,
    }
