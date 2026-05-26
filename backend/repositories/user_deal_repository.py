from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class UserDealRepository:
    COLLECTION = 'user_generated_deals'

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)

    def create(self, data: dict) -> dict:
        now = datetime.utcnow().isoformat()
        deal_id = f'udeal_{uuid4().hex[:12]}'
        current = float(data.get('current_price') or 0)
        old = data.get('old_price')
        discount = 0
        if old and float(old) > current:
            discount = int(((float(old) - current) / float(old)) * 100)
        reward_points = 10
        if data.get('media_url'):
            reward_points += 5
        if discount >= 20:
            reward_points += 5
        deal = {
            'id': deal_id,
            **data,
            'discount_percent': discount,
            'status': 'pending',
            'ai_status': 'not_checked',
            'reward_points': reward_points,
            'hot_votes': 0,
            'cold_votes': 0,
            'hot_score': 50,
            'created_at': now,
            'updated_at': now,
        }
        self.collection.document(deal_id).set(deal)
        return deal

    def list(self, country: Optional[str] = None, city: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 100))
        query = self.collection.limit(200)
        docs = list(query.stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            if country and str(data.get('country', '')).upper() != country.upper():
                continue
            if city and city.lower() not in str(data.get('city', '')).lower():
                continue
            if status and str(data.get('status', '')) != status:
                continue
            items.append(self._normalize(data))
        items.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return items[:limit]

    def moderate(self, deal_id: str, status: str) -> Optional[dict]:
        ref = self.collection.document(deal_id)
        snap = ref.get()
        if not snap.exists:
            return None
        ref.set({'status': status, 'updated_at': datetime.utcnow().isoformat()}, merge=True)
        data = snap.to_dict() or {}
        data['id'] = data.get('id') or deal_id
        data['status'] = status
        return self._normalize(data)

    def _normalize(self, data: dict) -> dict:
        data['description'] = data.get('description') or ''
        data['city'] = data.get('city') or ''
        data['media_url'] = data.get('media_url') or ''
        data['discount_percent'] = int(data.get('discount_percent', 0))
        data['reward_points'] = int(data.get('reward_points', 0))
        data['hot_votes'] = int(data.get('hot_votes', 0))
        data['cold_votes'] = int(data.get('cold_votes', 0))
        data['hot_score'] = int(data.get('hot_score', 50))
        return data


user_deal_repository = UserDealRepository()
