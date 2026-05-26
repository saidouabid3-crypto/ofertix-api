from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from uuid import uuid4

from core.firebase import db


class GeoAlertRepository:
    COLLECTION = 'geo_store_deals'

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)

    def create_store_deal(self, data: dict) -> dict:
        now = datetime.utcnow().isoformat()
        item_id = f'geo_{uuid4().hex[:12]}'
        item = {
            'id': item_id,
            **data,
            'status': 'active',
            'created_at': now,
            'updated_at': now,
        }
        self.collection.document(item_id).set(item)
        return item

    def nearby(self, latitude: float, longitude: float, watchlist: list[str], limit: int = 20) -> list[dict]:
        limit = max(1, min(limit, 50))
        docs = list(self.collection.where('status', '==', 'active').limit(300).stream())
        items = []
        watchset = {str(x) for x in watchlist if str(x).strip()}
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            if watchset and str(data.get('product_id')) not in watchset:
                # Keep matching strict to protect battery/notifications.
                continue
            dist = self._distance_m(latitude, longitude, float(data.get('latitude')), float(data.get('longitude')))
            radius = int(data.get('radius_meters', 250))
            if dist <= radius:
                items.append({
                    'id': data['id'],
                    'product_id': str(data.get('product_id') or ''),
                    'product_title': str(data.get('product_title') or 'Oferta cercana'),
                    'store': str(data.get('store') or ''),
                    'price': float(data.get('price') or 0),
                    'currency': str(data.get('currency') or 'EUR'),
                    'distance_meters': int(dist),
                    'message': f"Oferta cerca: {data.get('product_title')} en {data.get('store')}",
                })
        items.sort(key=lambda x: x['distance_meters'])
        return items[:limit]

    @staticmethod
    def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        r = 6371000
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        return r * c


geo_alert_repository = GeoAlertRepository()
