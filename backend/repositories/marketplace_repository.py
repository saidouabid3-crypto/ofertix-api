from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.firebase import db
from utils.country_intelligence import enrich_country_fields, item_matches_country, normalize_country

COLLECTION = 'marketplace_items'
REPORTS_COLLECTION = 'item_reports'
FAVORITES_COLLECTION = 'item_favorites'
PUBLIC_MARKETPLACE_STATUSES = {'active', 'approved', 'published'}
BLOCKED_MARKETPLACE_STATUSES = {
    'archived',
    'blocked',
    'deleted',
    'hidden',
    'pending',
    'rejected',
    'review',
    'under_review',
}


def _with_id(doc) -> Dict[str, Any]:
    data = enrich_country_fields(doc.to_dict() or {})
    data['id'] = doc.id
    return data


def is_public_marketplace_item(item: Dict[str, Any]) -> bool:
    status = str(item.get('status') or '').strip().lower()
    if status not in PUBLIC_MARKETPLACE_STATUSES:
        return False
    if status in BLOCKED_MARKETPLACE_STATUSES:
        return False
    for field in ('isActive', 'isVisible', 'visible', 'visibleToUsers', 'publicVisible'):
        if item.get(field) is False:
            return False
    moderation_status = str(
        item.get('moderationStatus') or item.get('moderation_status') or ''
    ).strip().lower()
    if moderation_status in BLOCKED_MARKETPLACE_STATUSES:
        return False
    seller_status = str(
        item.get('sellerStatus') or item.get('seller_status') or ''
    ).strip().lower()
    if seller_status in {'banned', 'blocked', 'deleted', 'suspended'}:
        return False
    if any(
        item.get(field) is True
        for field in ('sellerBanned', 'isSellerBanned', 'sellerBlocked')
    ):
        return False
    return True


class MarketplaceRepository:
    def list_items(
        self,
        limit: int = 30,
        country: str = 'es',
        city: Optional[str] = None,
        category: Optional[str] = None,
        only_active: bool = True,
    ) -> List[Dict[str, Any]]:
        requested_country = normalize_country(country)
        query = db.collection(COLLECTION)
        if only_active:
            query = query.where('isActive', '==', True)
        if city:
            query = query.where('city', '==', city)
        if category:
            query = query.where('category', '==', category)
        query = query.limit(max(1, min(limit * 4, 300)))

        items = []
        for doc in query.stream():
            item = _with_id(doc)
            if not is_public_marketplace_item(item):
                continue
            if not item_matches_country(item, requested_country):
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def create_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        data = enrich_country_fields({
            **payload,
            'isActive': payload.get('isActive', True),
            'isFeatured': payload.get('isFeatured', False),
            'isSponsored': payload.get('isSponsored', False),
            'views': int(payload.get('views', 0) or 0),
            'favorites': int(payload.get('favorites', 0) or 0),
            'createdAt': payload.get('createdAt') or now,
            'updatedAt': now,
        })
        ref = db.collection(COLLECTION).document()
        ref.set(data)
        data['id'] = ref.id
        return data

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        doc = db.collection(COLLECTION).document(item_id).get()
        if not doc.exists:
            return None
        return _with_id(doc)

    def get_public_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        item = self.get_item(item_id)
        if not item or not is_public_marketplace_item(item):
            return None
        return item

    def update_item(self, item_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ref = db.collection(COLLECTION).document(item_id)
        if not ref.get().exists:
            return None
        payload['updatedAt'] = datetime.now(timezone.utc)
        ref.update(payload)
        return self.get_item(item_id)

    def delete_item(self, item_id: str) -> bool:
        ref = db.collection(COLLECTION).document(item_id)
        if not ref.get().exists:
            return False
        ref.update({'isActive': False, 'status': 'deleted', 'deletedAt': datetime.now(timezone.utc)})
        return True

    def favorite_item(self, item_id: str, user_id: str) -> Dict[str, Any]:
        fav_id = f'{item_id}_{user_id}'
        db.collection(FAVORITES_COLLECTION).document(fav_id).set({
            'itemId': item_id,
            'userId': user_id,
            'createdAt': datetime.now(timezone.utc),
        }, merge=True)
        db.collection(COLLECTION).document(item_id).update({'favorites': firestore_increment(1)})
        return {'ok': True, 'itemId': item_id, 'userId': user_id}

    def report_item(self, item_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        ref = db.collection(REPORTS_COLLECTION).document()
        ref.set({
            'itemId': item_id,
            'userId': user_id,
            'reason': reason,
            'status': 'open',
            'createdAt': datetime.now(timezone.utc),
        })
        return {'ok': True, 'reportId': ref.id}


def firestore_increment(value: int):
    from google.cloud.firestore_v1 import Increment
    return Increment(value)
