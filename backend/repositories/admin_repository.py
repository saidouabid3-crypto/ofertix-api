from __future__ import annotations

from typing import Any, Dict, List

from core.firebase import db
from utils.country_intelligence import GLOBAL_CODES, enrich_country_fields, normalize_country


COUNTRY_ALIASES = {
    'amazon es': 'es', 'amazon.es': 'es', 'amazones': 'es', 'es amazon': 'es',
    'amazon france': 'fr', 'amazon fr': 'fr', 'amazon.fr': 'fr',
    'amazon de': 'de', 'amazon.de': 'de',
    'amazon it': 'it', 'amazon.it': 'it',
    'amazon uk': 'uk', 'amazon.co.uk': 'uk',
    'amazon us': 'us', 'amazon.com': 'us',
    'amazon ca': 'ca', 'amazon.ca': 'ca',
    'jumia ma': 'ma', 'jumia morocco': 'ma', 'jumia maroc': 'ma',
    'jumia dz': 'dz', 'jumia algeria': 'dz', 'jumia eg': 'eg',
    'noon ae': 'ae', 'noon uae': 'ae', 'noon sa': 'sa', 'noon egypt': 'eg',
    'carrefour es': 'es', 'mediamarkt es': 'es', 'pccomponentes': 'es',
    'walmart ca': 'ca', 'bestbuy ca': 'ca', 'walmart us': 'us', 'bestbuy us': 'us',
    'mercado libre mx': 'mx', 'mercadolibre mx': 'mx',
}


def _safe_aggregate_count(collection: str, fallback_limit: int = 2000) -> int:
    try:
        query = db.collection(collection).count()
        result = query.get()
        if result and result[0]:
            # Firestore aggregation result API differs by version.
            value = getattr(result[0], 'value', None)
            if isinstance(value, int):
                return value
            data = result[0][0].value if isinstance(result[0], list) else None
            if isinstance(data, int):
                return data
    except Exception:
        pass

    try:
        return sum(1 for _ in db.collection(collection).limit(fallback_limit).stream())
    except Exception:
        return 0


def _safe_sum(collection: str, field: str, limit: int = 500) -> float:
    total = 0.0
    try:
        for doc in db.collection(collection).limit(limit).stream():
            data = doc.to_dict() or {}
            value = data.get(field, 0) or 0
            if isinstance(value, (int, float)):
                total += float(value)
    except Exception:
        return 0.0
    return total


def _infer_country_from_source(data: Dict[str, Any]) -> str:
    explicit = normalize_country(
        data.get('countryCode')
        or data.get('country_code')
        or data.get('storeCountry')
        or data.get('country')
        or ''
    )
    if explicit and explicit not in GLOBAL_CODES:
        return explicit

    haystack = ' '.join(
        str(data.get(key, '') or '').lower()
        for key in ['source', 'store', 'provider', 'affiliateUrl', 'url', 'productUrl', 'marketplace']
    )

    for marker, country in COUNTRY_ALIASES.items():
        if marker in haystack:
            return country

    return 'global'


def _clean_top_product(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any] | None:
    enriched = enrich_country_fields(data)
    country = _infer_country_from_source(enriched)
    if country in GLOBAL_CODES:
        return None

    price = _to_float(
        enriched.get('price')
        or enriched.get('currentPrice')
        or enriched.get('current_price')
        or enriched.get('salePrice')
        or 0
    )

    title = enriched.get('name') or enriched.get('title') or enriched.get('productName') or 'Product'
    store = enriched.get('store') or enriched.get('source') or enriched.get('provider') or ''
    clicks = int(enriched.get('clicks') or enriched.get('clickCount') or 0)
    revenue = _to_float(enriched.get('revenue') or enriched.get('commission') or enriched.get('estimatedRevenue') or 0)

    if not str(title).strip():
        return None

    return {
        'id': doc_id,
        'name': str(title).strip(),
        'store': str(store).strip(),
        'clicks': clicks,
        'revenue': revenue,
        'countryCode': country,
        'price': price,
    }


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value or '0').replace(',', '.'))
    except Exception:
        return 0.0


class AdminRepository:
    def dashboard(self) -> Dict[str, Any]:
        total_users = _safe_aggregate_count('users')
        total_products = _safe_aggregate_count('products')
        total_reels = _safe_aggregate_count('smart_reels')
        total_marketplace = _safe_aggregate_count('marketplace_items')
        open_reports = _safe_aggregate_count('item_reports') + _safe_aggregate_count('smart_reel_reports')

        total_clicks = int(
            _safe_sum('products', 'clicks')
            + _safe_sum('smart_reels', 'clicks')
            + _safe_sum('affiliate_clicks', 'count')
        )
        total_orders = int(_safe_aggregate_count('orders') + _safe_aggregate_count('cashback_transactions'))
        revenue = float(
            _safe_sum('orders', 'commission')
            + _safe_sum('cashback_transactions', 'revenue')
            + _safe_sum('ad_events', 'estimatedRevenue')
        )

        return {
            'live': True,
            'totalUsers': total_users,
            'totalClicks': total_clicks,
            'totalOrders': total_orders,
            'revenue': round(revenue, 2),
            'totalProducts': total_products,
            'totalReels': total_reels,
            'totalMarketplaceItems': total_marketplace,
            'openReports': open_reports,
            'topSearches': self.top_searches(),
            'topProducts': self.top_products(),
            'connectors': self.connector_status(),
        }

    def top_searches(self, limit: int = 8) -> List[str]:
        try:
            docs = (
                db.collection('search_analytics')
                .order_by('count', direction='DESCENDING')
                .limit(limit)
                .stream()
            )
            items = []
            for doc in docs:
                data = doc.to_dict() or {}
                query = data.get('query') or data.get('term') or doc.id
                if query:
                    items.append(str(query))
            return items
        except Exception:
            return []

    def top_products(self, limit: int = 6) -> List[Dict[str, Any]]:
        # Pull a small window, then show only market-ready products.
        # This prevents GLOBAL/unclean imported products from making admin look unfinished.
        try:
            try:
                docs = (
                    db.collection('products')
                    .order_by('clicks', direction='DESCENDING')
                    .limit(limit * 4)
                    .stream()
                )
            except Exception:
                docs = db.collection('products').limit(limit * 4).stream()

            items: List[Dict[str, Any]] = []
            for doc in docs:
                cleaned = _clean_top_product(doc.id, doc.to_dict() or {})
                if cleaned is not None:
                    items.append(cleaned)
                if len(items) >= limit:
                    break
            return items
        except Exception:
            return []

    def connector_status(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            docs = db.collection('api_connectors').limit(limit).stream()
            items = []
            for doc in docs:
                data = doc.to_dict() or {}
                country = normalize_country(data.get('countryCode') or data.get('country') or 'global')
                items.append({
                    'source': data.get('source') or data.get('name') or doc.id,
                    'countryCode': country,
                    'enabled': bool(data.get('enabled', False)),
                    'lastSyncAt': str(data.get('lastSyncAt') or '') or None,
                    'lastStatus': data.get('lastStatus') or data.get('status') or 'not_configured',
                    'lastError': data.get('lastError') or '',
                })
            return items
        except Exception:
            return []
