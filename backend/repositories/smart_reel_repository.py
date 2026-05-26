from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class SmartReelRepository:
    COLLECTION = 'smart_reels'
    COMMENTS_COLLECTION = 'smart_reel_comments'
    FOLLOWS_COLLECTION = 'user_follows'

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)
        self.comments_collection = db.collection(self.COMMENTS_COLLECTION)
        self.follows_collection = db.collection(self.FOLLOWS_COLLECTION)

    def create(self, data: dict) -> dict:
        now = datetime.utcnow().isoformat()
        reel_id = f'reel_{uuid4().hex[:12]}'
        reel = {
            'id': reel_id,
            **data,
            'views': 0,
            'likes': 0,
            'clicks': 0,
            'comments': 0,
            'saves': 0,
            'reports': 0,
            'hot_votes': 0,
            'cold_votes': 0,
            'hot_score': 50,
            'temperature': 50,
            'created_at': now,
            'updated_at': now,
        }
        self.collection.document(reel_id).set(reel)
        return self._normalize_reel(reel)

    def list_feed(self, limit: int = 10, cursor: Optional[str] = None, viewer_id: Optional[str] = None) -> tuple[list[dict], Optional[str], bool]:
        limit = max(1, min(limit, 20))
        query = self.collection.where('status', '==', 'approved').limit(120)
        docs = list(query.stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            data = self._normalize_reel(data)
            data = self._attach_social_state(data, viewer_id=viewer_id)
            items.append(data)
        items.sort(key=lambda r: (int(r.get('hot_score', 50)), int(r.get('deal_score', 0)), str(r.get('created_at') or '')), reverse=True)
        if cursor:
            cursor_index = next((i for i, item in enumerate(items) if item.get('id') == cursor), -1)
            if cursor_index >= 0:
                items = items[cursor_index + 1:]
        docs_to_return = items[:limit]
        has_more = len(items) > limit
        next_cursor = docs_to_return[-1]['id'] if has_more and docs_to_return else None
        return docs_to_return, next_cursor, has_more

    def get_by_id(self, reel_id: str) -> Optional[dict]:
        doc = self.collection.document(reel_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data['id'] = data.get('id') or doc.id
        return self._normalize_reel(data)

    def increment(self, reel_id: str, field: str) -> Optional[dict]:
        allowed_fields = {'views', 'likes', 'clicks', 'comments', 'saves', 'reports'}
        if field not in allowed_fields:
            return None
        doc_ref = self.collection.document(reel_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        current_value = int(data.get(field, 0))
        new_value = max(0, current_value + 1)
        doc_ref.update({field: new_value, 'updated_at': datetime.utcnow().isoformat()})
        data[field] = new_value
        data['id'] = data.get('id') or reel_id
        return self._normalize_reel(data)

    def add_comment(self, reel_id: str, text: str, user_id: str = 'mobile_user', user_name: str = 'Ofertix User') -> Optional[dict]:
        reel_ref = self.collection.document(reel_id)
        reel_doc = reel_ref.get()
        if not reel_doc.exists:
            return None
        now = datetime.utcnow().isoformat()
        comment_id = f'comment_{uuid4().hex[:12]}'
        comment = {'id': comment_id, 'reel_id': reel_id, 'user_id': user_id or 'mobile_user', 'user_name': user_name or 'Ofertix User', 'text': text.strip(), 'created_at': now}
        self.comments_collection.document(comment_id).set(comment)
        reel_data = reel_doc.to_dict() or {}
        reel_ref.update({'comments': int(reel_data.get('comments', 0)) + 1, 'updated_at': now})
        return comment

    def list_comments(self, reel_id: str, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 100))
        docs = list(self.comments_collection.where('reel_id', '==', reel_id).limit(limit).stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(data)
        items.sort(key=lambda c: str(c.get('created_at') or ''), reverse=True)
        return items

    def toggle_follow(self, creator_id: str, follower_id: str = 'mobile_user') -> dict:
        creator_id = creator_id.strip()
        follower_id = follower_id.strip() or 'mobile_user'
        if not creator_id or creator_id == follower_id:
            return {'ok': False, 'is_following': False}
        follow_id = f'{follower_id}_{creator_id}'
        follow_ref = self.follows_collection.document(follow_id)
        follow_doc = follow_ref.get()
        if follow_doc.exists:
            follow_ref.delete()
            self._increment_user_counter(creator_id, 'followers_count', -1)
            self._increment_user_counter(follower_id, 'following_count', -1)
            return {'ok': True, 'is_following': False}
        follow_ref.set({'id': follow_id, 'creator_id': creator_id, 'follower_id': follower_id, 'created_at': datetime.utcnow().isoformat()})
        self._increment_user_counter(creator_id, 'followers_count', 1)
        self._increment_user_counter(follower_id, 'following_count', 1)
        return {'ok': True, 'is_following': True}

    def _increment_user_counter(self, uid: str, field: str, amount: int) -> None:
        if not uid or uid == 'mobile_user':
            return
        user_ref = db.collection('users').document(uid)
        snap = user_ref.get()
        current = int((snap.to_dict() or {}).get(field, 0)) if snap.exists else 0
        user_ref.set({field: max(0, current + amount), 'updated_at': datetime.utcnow().isoformat()}, merge=True)

    def _attach_social_state(self, reel: dict, viewer_id: Optional[str] = None) -> dict:
        creator_id = str(reel.get('creator_id') or 'mobile_user')
        viewer_id = (viewer_id or '').strip()
        reel['is_liked'] = False
        reel['is_saved'] = False
        reel['is_following'] = False
        if viewer_id and creator_id and viewer_id != creator_id:
            follow_id = f'{viewer_id}_{creator_id}'
            reel['is_following'] = self.follows_collection.document(follow_id).get().exists
        return reel

    def _normalize_reel(self, reel: dict) -> dict:
        reel['product_id'] = reel.get('product_id') or None
        reel['description'] = reel.get('description') or ''
        reel['creator_id'] = str(reel.get('creator_id') or 'mobile_user')
        reel['creator_name'] = str(reel.get('creator_name') or 'Ofertix User')
        reel['creator_avatar_url'] = str(reel.get('creator_avatar_url') or '')
        reel['thumbnail_url'] = str(reel.get('thumbnail_url') or '')
        reel['video_mp4_url'] = str(reel.get('video_mp4_url') or '')
        reel['video_hls_url'] = reel.get('video_hls_url')
        reel['affiliate_url'] = str(reel.get('affiliate_url') or '')
        for field in ['views', 'likes', 'clicks', 'comments', 'saves', 'reports', 'hot_votes', 'cold_votes']:
            reel[field] = int(reel.get(field, 0))
        reel['hot_score'] = int(reel.get('hot_score', 50))
        reel['temperature'] = int(reel.get('temperature', reel['hot_score']))
        reel['deal_score'] = int(reel.get('deal_score', 50))
        reel['discount_percent'] = int(reel.get('discount_percent', 0))
        reel['status'] = str(reel.get('status') or 'approved')
        reel['provider'] = str(reel.get('provider') or 'cloudinary')
        reel['ai_verdict'] = str(reel.get('ai_verdict') or 'Oferta normal')
        reel['fake_discount_risk'] = str(reel.get('fake_discount_risk') or 'unknown')
        return reel


smart_reel_repository = SmartReelRepository()
