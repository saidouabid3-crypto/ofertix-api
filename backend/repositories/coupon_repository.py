from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class CouponRepository:
    COLLECTION = 'coupons'

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)

    def create(self, data: dict) -> dict:
        now = datetime.utcnow().isoformat()
        coupon_id = f'coupon_{uuid4().hex[:12]}'
        coupon = {
            'id': coupon_id,
            **data,
            'status': 'active',
            'verified_works': 0,
            'verified_failed': 0,
            'trust_score': 50,
            'hot_votes': 0,
            'cold_votes': 0,
            'hot_score': 50,
            'created_at': now,
            'updated_at': now,
        }
        self.collection.document(coupon_id).set(coupon)
        return coupon

    def list(self, country: Optional[str] = None, store: Optional[str] = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 100))
        query = self.collection.where('status', '==', 'active').limit(200)
        docs = list(query.stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            if country and str(data.get('country', '')).upper() != country.upper():
                continue
            if store and store.lower() not in str(data.get('store', '')).lower():
                continue
            items.append(self._normalize(data))
        items.sort(key=lambda x: (int(x.get('trust_score', 50)), int(x.get('hot_score', 50)), str(x.get('created_at', ''))), reverse=True)
        return items[:limit]

    def verify(self, coupon_id: str, works: bool) -> Optional[dict]:
        ref = self.collection.document(coupon_id)
        snap = ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        good = int(data.get('verified_works', 0)) + (1 if works else 0)
        bad = int(data.get('verified_failed', 0)) + (0 if works else 1)
        total = good + bad
        trust_score = 50 if total == 0 else max(0, min(100, round((good / total) * 100)))
        data.update({
            'verified_works': good,
            'verified_failed': bad,
            'trust_score': trust_score,
            'updated_at': datetime.utcnow().isoformat(),
        })
        ref.set(data, merge=True)
        data['id'] = data.get('id') or coupon_id
        return self._normalize(data)

    def _normalize(self, data: dict) -> dict:
        data['description'] = data.get('description') or ''
        data['discount_label'] = data.get('discount_label') or ''
        data['source_url'] = data.get('source_url') or None
        data['expires_at'] = data.get('expires_at') or None
        data['verified_works'] = int(data.get('verified_works', 0))
        data['verified_failed'] = int(data.get('verified_failed', 0))
        data['trust_score'] = int(data.get('trust_score', 50))
        data['hot_votes'] = int(data.get('hot_votes', 0))
        data['cold_votes'] = int(data.get('cold_votes', 0))
        data['hot_score'] = int(data.get('hot_score', 50))
        return data


coupon_repository = CouponRepository()
