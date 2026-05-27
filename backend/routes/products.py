from fastapi import APIRouter, Query
from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.market_filter import item_available_for_country, normalize_item_market_fields

router = APIRouter()


@router.get('/products')
def get_products(
    country: str = 'es',
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1, le=50),
    category: str | None = None,
    store: str | None = None,
):
    market = normalize_market(country)
    # Keep Firestore reads bounded. This is not a full search engine, but it prevents unlimited collection reads.
    read_limit = min(max(limit * 4, 80), 240)
    offset_to_skip = (page - 1) * limit
    try:
        query = db.collection('products').where('visibleToUsers', '==', True).limit(read_limit)
        docs = query.stream()
    except Exception:
        docs = db.collection('products').limit(read_limit).stream()
    results = []
    skipped = 0
    wanted_category = (category or '').strip().lower()
    wanted_store = (store or '').strip().lower()
    for doc in docs:
        item = doc.to_dict() or {}
        item['id'] = doc.id
        status = str(item.get('status', 'active')).lower()
        if status not in {'active', 'approved', 'published'}:
            continue
        item = normalize_item_market_fields(item, fallback_country=market)
        if not item_available_for_country(item, market):
            continue
        if wanted_category and wanted_category not in str(item.get('category') or item.get('categoryId') or '').lower():
            continue
        if wanted_store and wanted_store not in str(item.get('store') or item.get('source') or '').lower():
            continue
        if skipped < offset_to_skip:
            skipped += 1
            continue
        results.append(item)
        if len(results) >= limit:
            break
    return {'country': market, 'currency': SUPPORTED_MARKETS[market]['currency'], 'page': page, 'limit': limit, 'count': len(results), 'hasMore': len(results) == limit, 'products': results}
