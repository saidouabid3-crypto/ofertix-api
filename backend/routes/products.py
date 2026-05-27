from fastapi import APIRouter, Query
from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.market_filter import item_available_for_country, normalize_item_market_fields

router = APIRouter()

@router.get('/products')
def get_products(country: str = 'es', limit: int = Query(50, ge=1, le=100)):
    market = normalize_market(country)
    docs = db.collection('products').limit(700).get()
    results = []
    for doc in docs:
        item = doc.to_dict() or {}
        item['id'] = doc.id
        item = normalize_item_market_fields(item, fallback_country=market)
        if str(item.get('status', 'active')).lower() not in {'active', 'approved', 'published'}:
            continue
        if item_available_for_country(item, market):
            results.append(item)
        if len(results) >= limit:
            break
    return {'country': market, 'currency': SUPPORTED_MARKETS[market]['currency'], 'count': len(results), 'products': results}
