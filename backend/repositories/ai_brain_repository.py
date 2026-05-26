from datetime import datetime
from uuid import uuid4

from core.firebase import db


class AIBrainRepository:
    COLLECTION = 'ai_deal_analyses'

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)

    def save(self, user_id: str, payload: dict, result: dict) -> dict:
        now = datetime.utcnow().isoformat()
        item_id = f'aibrain_{uuid4().hex[:14]}'
        item = {
            'id': item_id,
            'user_id': user_id,
            'query': payload.get('query', ''),
            'product_id': payload.get('product_id'),
            'reel_id': payload.get('reel_id'),
            'mystery_reward_id': payload.get('mystery_reward_id'),
            **result,
            'created_at': now,
            'updated_at': now,
        }
        self.collection.document(item_id).set(item)
        return item

    def history(self, user_id: str, limit: int = 30) -> list[dict]:
        docs = list(self.collection.where('user_id', '==', user_id).limit(max(1, min(limit, 50))).stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(data)
        items.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return items


ai_brain_repository = AIBrainRepository()
