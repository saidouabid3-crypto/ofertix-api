from fastapi import APIRouter, Query

from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.product_standard import available_for_country, standardize_product

router = APIRouter()


@router.get('/products')
def get_products(
    country: str = 'es',
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1, le=100),
    category: str | None = None,
    store: str | None = None,
):
    """Cost-safe product endpoint with Ofertix Product Standard v1.

    It returns clean products with images[], rating/reviews/sold, deal scores,
    price accuracy, AI verdict fields and country/currency data.
    """
    market = normalize_market(country)
    read_limit = min(max(limit * 5, 120), 500)
    offset_to_skip = (page - 1) * limit
    try:
        docs = db.collection('products').where('visibleToUsers', '==', True).limit(read_limit).stream()
    except Exception:
        docs = db.collection('products').limit(read_limit).stream()

    wanted_category = (category or '').strip().lower()
    wanted_store = (store or '').strip().lower()
    prepared = []
    seen = set()

    for doc in docs:
        raw = doc.to_dict() or {}
        item = standardize_product(raw, document_id=doc.id, fallback_country=market)
        status = str(item.get('status', 'active')).lower()
        if status not in {'active', 'approved', 'published'}:
            continue
        if not available_for_country(item, market):
            continue
        if wanted_category and wanted_category not in str(item.get('categoryGroup') or item.get('category') or '').lower():
            continue
        if wanted_store and wanted_store not in str(item.get('store') or item.get('source') or '').lower():
            continue
        if not item.get('image') or float(item.get('newPrice') or 0) <= 0:
            continue
        fp = item.get('fingerprint') or item.get('id')
        if fp in seen:
            continue
        seen.add(fp)
        prepared.append(item)

    prepared.sort(
        key=lambda p: (
            float(p.get('dealScore') or 0) * 0.40 +
            float(p.get('trustScore') or 0) * 0.30 +
            float(p.get('qualityScore') or 0) * 0.20 -
            float(p.get('riskScore') or 0) * 0.10,
            int(p.get('reviewCount') or 0),
        ),
        reverse=True,
    )
    page_items = prepared[offset_to_skip:offset_to_skip + limit]
    return {
        'country': market,
        'currency': SUPPORTED_MARKETS[market]['currency'],
        'page': page,
        'limit': limit,
        'count': len(page_items),
        'totalPrepared': len(prepared),
        'hasMore': offset_to_skip + limit < len(prepared),
        'standardVersion': 'ofertix-product-standard-v1',
        'products': page_items,
    }
