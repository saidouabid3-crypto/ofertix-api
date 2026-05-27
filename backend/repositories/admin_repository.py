from __future__ import annotations

from typing import Any, Dict, List

from core.firebase import db
from utils.country_intelligence import enrich_country_fields


def _safe_stream_count(collection: str, limit: int = 2000) -> int:
    try:
        return sum(1 for _ in db.collection(collection).limit(limit).stream())
    except Exception:
        return 0


def _safe_sum(collection: str, field: str, limit: int = 2000) -> float:
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


class AdminRepository:
    def dashboard(self) -> Dict[str, Any]:
        total_users = _safe_stream_count('users')
        total_products = _safe_stream_count('products')
        total_reels = _safe_stream_count('smart_reels')
        total_marketplace = _safe_stream_count('marketplace_items')
        open_reports = _safe_stream_count('item_reports') + _safe_stream_count('smart_reel_reports')

        total_clicks = int(
            _safe_sum('products', 'clicks')
            + _safe_sum('smart_reels', 'clicks')
            + _safe_sum('affiliate_clicks', 'count')
        )
        total_orders = int(_safe_stream_count('orders') + _safe_stream_count('cashback_transactions'))
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
        try:
            docs = (
                db.collection('products')
                .order_by('clicks', direction='DESCENDING')
                .limit(limit)
                .stream()
            )
            items = []
            for doc in docs:
                data = enrich_country_fields(doc.to_dict() or {})
                items.append({
                    'id': doc.id,
                    'name': data.get('name') or data.get('title') or 'Product',
                    'store': data.get('store') or data.get('source') or '',
                    'clicks': int(data.get('clicks') or 0),
                    'revenue': float(data.get('revenue') or data.get('commission') or 0),
                    'countryCode': data.get('countryCode') or 'global',
                })
            return items
        except Exception:
            return []

    def connector_status(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            docs = db.collection('api_connectors').limit(limit).stream()
            items = []
            for doc in docs:
                data = doc.to_dict() or {}
                items.append({
                    'source': data.get('source') or data.get('name') or doc.id,
                    'countryCode': data.get('countryCode') or data.get('country') or 'global',
                    'enabled': bool(data.get('enabled', False)),
                    'lastSyncAt': str(data.get('lastSyncAt') or '') or None,
                    'lastStatus': data.get('lastStatus') or data.get('status') or 'not_configured',
                    'lastError': data.get('lastError') or '',
                })
            return items
        except Exception:
            return []
