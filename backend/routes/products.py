from fastapi import APIRouter, Query
from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.market_filter import item_available_for_country, normalize_item_market_fields
from utils.product_standard import normalize_product

router = APIRouter()


def _usable(item, market: str) -> bool:
    status = str(item.get('status', 'active')).lower()
    if status not in {'active', 'approved', 'published'}:
        return False
    if item.get('visibleToUsers') is False:
        return False
    if not item.get('image') and not item.get('mainImage'):
        return False
    if float(item.get('newPrice') or item.get('price') or 0) <= 0:
        return False
    if not item_available_for_country(item, market):
        return False
    if str(item.get('categoryGroup') or item.get('category')).lower() == 'kitchen':
        hay = f"{item.get('name','')} {item.get('description','')}".lower()
        negatives = ['shoe', 'sneaker', 'ring', 'jewelry', 'earring', 'necklace', 'watch', 'phone', 'dress', 'pants', 'bag']
        if any(n in hay for n in negatives):
            return False
    return True


@router.get('/products')
def get_products(
    country: str = 'es',
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1, le=200),
    category: str | None = None,
    store: str | None = None,
):
    market = normalize_market(country)
    read_limit = min(max(limit * 6, 240), 1000)
    offset_to_skip = (page - 1) * limit
    try:
        docs = db.collection('products').where('visibleToUsers', '==', True).limit(read_limit).stream()
    except Exception:
        docs = db.collection('products').limit(read_limit).stream()

    results = []
    skipped = 0
    seen = set()
    wanted_category = (category or '').strip().lower()
    wanted_store = (store or '').strip().lower()

    for doc in docs:
        raw = doc.to_dict() or {}
        raw['id'] = doc.id
        item = normalize_product(normalize_item_market_fields(raw, fallback_country=market), fallback_country=market)
        if not _usable(item, market):
            continue
        if wanted_category and wanted_category not in str(item.get('categoryGroup') or item.get('category') or '').lower():
            continue
        if wanted_store and wanted_store not in str(item.get('store') or item.get('source') or '').lower():
            continue
        fp = item.get('fingerprint') or f"{item.get('store')}|{item.get('name')}|{item.get('newPrice')}"
        if fp in seen:
            continue
        seen.add(fp)
        if skipped < offset_to_skip:
            skipped += 1
            continue
        results.append(item)
        if len(results) >= limit:
            break

    return {
        'country': market,
        'currency': SUPPORTED_MARKETS[market]['currency'],
        'page': page,
        'limit': limit,
        'count': len(results),
        'hasMore': len(results) == limit,
        'products': results,
    }
