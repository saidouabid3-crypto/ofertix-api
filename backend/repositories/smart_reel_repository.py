from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class SmartReelRepository:
    COLLECTION = 'smart_reels'
    COMMENTS_COLLECTION = 'smart_reel_comments'
    FOLLOWS_COLLECTION = 'user_follows'
    MESSAGES_COLLECTION = 'smart_reel_messages'
    LIKES_COLLECTION = 'reel_likes'
    SAVES_COLLECTION = 'reel_saves'
    REPORTS_COLLECTION = 'reel_reports'

    def __init__(self):
        def _coll(name: str):
            return db.collection(name) if db is not None else None  # type: ignore[union-attr]

        self.collection = _coll(self.COLLECTION)
        self.comments_collection = _coll(self.COMMENTS_COLLECTION)
        self.follows_collection = _coll(self.FOLLOWS_COLLECTION)
        self.messages_collection = _coll(self.MESSAGES_COLLECTION)
        self.likes_collection = _coll(self.LIKES_COLLECTION)
        self.saves_collection = _coll(self.SAVES_COLLECTION)
        self.reports_collection = _coll(self.REPORTS_COLLECTION)

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

    def update(self, reel_id: str, data: dict, actor_id: str = 'mobile_user') -> Optional[dict]:
        doc_ref = self.collection.document(reel_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None

        existing = doc.to_dict() or {}
        if not self._can_manage(existing, actor_id):
            return None

        clean_data = {}
        allowed_fields = {
            'title',
            'description',
            'store',
            'current_price',
            'old_price',
            'currency',
            'affiliate_url',
            'product_id',
            'discount_percent',
            'deal_score',
            'ai_verdict',
            'fake_discount_risk',
        }

        for key, value in data.items():
            if key in allowed_fields:
                clean_data[key] = value

        if not clean_data:
            existing = doc.to_dict() or {}
            existing['id'] = existing.get('id') or reel_id
            return self._normalize_reel(existing)

        clean_data['updated_at'] = datetime.utcnow().isoformat()
        doc_ref.update(clean_data)

        updated = doc_ref.get().to_dict() or {}
        updated['id'] = updated.get('id') or reel_id
        return self._normalize_reel(updated)

    def delete(self, reel_id: str, actor_id: str = 'mobile_user') -> bool:
        doc_ref = self.collection.document(reel_id)
        doc = doc_ref.get()
        if not doc.exists:
            return False

        existing = doc.to_dict() or {}
        if not self._can_manage(existing, actor_id):
            return False

        # Soft delete keeps audit/history safe while feed filtering removes the reel immediately.
        # Media retention can be handled by a dedicated cleanup job without blocking user deletion.
        doc_ref.update({
            'status': 'deleted',
            'deleted_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
        })
        return True


    def create_message(self, reel_id: str, sender_id: str = 'mobile_user', sender_name: str = 'User', text: str = '') -> Optional[dict]:
        reel_ref = self.collection.document(reel_id)
        reel_doc = reel_ref.get()
        if not reel_doc.exists:
            return None

        reel = reel_doc.to_dict() or {}
        now = datetime.utcnow().isoformat()
        message_id = f'msg_{uuid4().hex[:12]}'
        message = {
            'id': message_id,
            'reel_id': reel_id,
            'creator_id': str(reel.get('creator_id') or 'mobile_user'),
            'sender_id': sender_id or 'mobile_user',
            'sender_name': sender_name or 'User',
            'text': text.strip(),
            'created_at': now,
            'status': 'unread',
        }
        self.messages_collection.document(message_id).set(message)
        return message

    def _can_manage(self, reel: dict, actor_id: str = 'mobile_user') -> bool:
        actor_id = (actor_id or 'mobile_user').strip()
        creator_id = str(reel.get('creator_id') or 'mobile_user').strip()

        # Safe for current mobile development flow. In production this should be backed by Firebase token verification.
        if actor_id == 'mobile_user' and creator_id == 'mobile_user':
            return True

        return bool(actor_id and creator_id and actor_id == creator_id)

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

    def add_comment(
        self,
        reel_id: str,
        text: str,
        user_id: str = 'mobile_user',
        user_name: str = 'Creator',
        user_avatar_url: str = '',
        username: str = '',
    ) -> Optional[dict]:
        reel_ref = self.collection.document(reel_id)
        reel_doc = reel_ref.get()
        if not reel_doc.exists:
            return None
        now = datetime.utcnow().isoformat()
        comment_id = f'comment_{uuid4().hex[:12]}'
        comment = {
            'id': comment_id,
            'reel_id': reel_id,
            'user_id': user_id or 'mobile_user',
            'user_name': user_name or 'Creator',
            'user_avatar_url': user_avatar_url or '',
            'username': username or '',
            'text': text.strip(),
            'created_at': now,
        }
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

    def report_once(self, reel_id: str, viewer_id: str) -> dict:
        """Create one report per authenticated user per reel. Idempotent.
        Returns {already_reported, reports}."""
        viewer_id = (viewer_id or '').strip()
        if not viewer_id or viewer_id == 'mobile_user':
            return {'already_reported': False, 'reports': 0}

        reel_doc = self.collection.document(reel_id).get()
        if not reel_doc.exists:
            return {'already_reported': False, 'reports': 0}

        report_id = f'{viewer_id}_{reel_id}'
        report_ref = self.reports_collection.document(report_id)
        now = datetime.utcnow().isoformat()

        if report_ref.get().exists:
            reel_data = reel_doc.to_dict() or {}
            return {
                'already_reported': True,
                'reports': int(reel_data.get('reports', 0)),
            }

        report_ref.set({
            'reel_id': reel_id,
            'viewer_id': viewer_id,
            'created_at': now,
        })
        reel_data = reel_doc.to_dict() or {}
        new_reports = int(reel_data.get('reports', 0)) + 1
        self.collection.document(reel_id).update({
            'reports': new_reports,
            'updated_at': now,
        })
        return {'already_reported': False, 'reports': new_reports}

    def toggle_like(self, reel_id: str, viewer_id: str) -> dict:
        """Toggle like for authenticated viewer. Returns {is_liked, likes}."""
        viewer_id = (viewer_id or '').strip()
        if not viewer_id or viewer_id == 'mobile_user':
            return {'is_liked': False, 'likes': 0}

        reel_doc = self.collection.document(reel_id).get()
        if not reel_doc.exists:
            return {'is_liked': False, 'likes': 0}

        like_id = f'{viewer_id}_{reel_id}'
        like_ref = self.likes_collection.document(like_id)
        like_doc = like_ref.get()
        reel_data = reel_doc.to_dict() or {}
        current_likes = max(0, int(reel_data.get('likes', 0)))
        now = datetime.utcnow().isoformat()

        if like_doc.exists:
            like_ref.delete()
            new_likes = max(0, current_likes - 1)
            self.collection.document(reel_id).update({'likes': new_likes, 'updated_at': now})
            return {'is_liked': False, 'likes': new_likes}
        else:
            like_ref.set({'reel_id': reel_id, 'viewer_id': viewer_id, 'created_at': now})
            new_likes = current_likes + 1
            self.collection.document(reel_id).update({'likes': new_likes, 'updated_at': now})
            return {'is_liked': True, 'likes': new_likes}

    def toggle_save(self, reel_id: str, viewer_id: str) -> dict:
        """Toggle save for authenticated viewer. Returns {is_saved, saves}."""
        viewer_id = (viewer_id or '').strip()
        if not viewer_id or viewer_id == 'mobile_user':
            return {'is_saved': False, 'saves': 0}

        reel_doc = self.collection.document(reel_id).get()
        if not reel_doc.exists:
            return {'is_saved': False, 'saves': 0}

        save_id = f'{viewer_id}_{reel_id}'
        save_ref = self.saves_collection.document(save_id)
        save_doc = save_ref.get()
        reel_data = reel_doc.to_dict() or {}
        current_saves = max(0, int(reel_data.get('saves', 0)))
        now = datetime.utcnow().isoformat()

        if save_doc.exists:
            save_ref.delete()
            new_saves = max(0, current_saves - 1)
            self.collection.document(reel_id).update({'saves': new_saves, 'updated_at': now})
            return {'is_saved': False, 'saves': new_saves}
        else:
            save_ref.set({'reel_id': reel_id, 'viewer_id': viewer_id, 'created_at': now})
            new_saves = current_saves + 1
            self.collection.document(reel_id).update({'saves': new_saves, 'updated_at': now})
            return {'is_saved': True, 'saves': new_saves}

    def _attach_social_state(self, reel: dict, viewer_id: Optional[str] = None) -> dict:
        creator_id = str(reel.get('creator_id') or 'mobile_user')
        reel_id = str(reel.get('id') or '')
        viewer_id = (viewer_id or '').strip()

        reel['is_liked'] = False
        reel['is_saved'] = False
        reel['is_following'] = False

        if viewer_id and viewer_id != 'mobile_user' and reel_id:
            like_id = f'{viewer_id}_{reel_id}'
            reel['is_liked'] = self.likes_collection.document(like_id).get().exists

            save_id = f'{viewer_id}_{reel_id}'
            reel['is_saved'] = self.saves_collection.document(save_id).get().exists

        if viewer_id and viewer_id != 'mobile_user' and creator_id and viewer_id != creator_id:
            follow_id = f'{viewer_id}_{creator_id}'
            reel['is_following'] = self.follows_collection.document(follow_id).get().exists

        return reel

    def _normalize_reel(self, reel: dict) -> dict:
        reel['product_id'] = reel.get('product_id') or None
        reel['description'] = reel.get('description') or ''
        reel['creator_id'] = str(reel.get('creator_id') or 'mobile_user')
        reel['creator_name'] = str(reel.get('creator_name') or 'Creator')
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
