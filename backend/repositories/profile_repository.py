from datetime import datetime
from typing import Optional

from core.firebase import db


class ProfileRepository:
    USERS_COLLECTION = 'users'
    REELS_COLLECTION = 'smart_reels'

    def __init__(self):
        self.users = db.collection(self.USERS_COLLECTION)
        self.reels = db.collection(self.REELS_COLLECTION)

    def get_profile(self, uid: str) -> Optional[dict]:
        uid = (uid or '').strip()
        if not uid:
            return None

        snap = self.users.document(uid).get()
        if not snap.exists:
            return None

        data = snap.to_dict() or {}
        data['uid'] = data.get('uid') or uid
        return self._normalize_profile(data)

    def get_creator_reels(self, creator_id: str, limit: int = 30) -> list[dict]:
        creator_id = (creator_id or '').strip()
        if not creator_id:
            return []

        limit = max(1, min(limit, 50))
        docs = list(
            self.reels
            .where('creator_id', '==', creator_id)
            .where('status', '==', 'approved')
            .limit(limit)
            .stream()
        )

        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_reel(data))

        items.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        return items

    def sync_creator_counters(self, uid: str) -> Optional[dict]:
        profile = self.get_profile(uid)
        if not profile:
            return None

        reels = self.get_creator_reels(uid, limit=50)
        total_likes = sum(int(item.get('likes', 0)) for item in reels)

        self.users.document(uid).set(
            {
                'reels_count': len(reels),
                'total_likes': total_likes,
                'updated_at': datetime.utcnow().isoformat(),
            },
            merge=True,
        )

        profile['reels_count'] = len(reels)
        profile['total_likes'] = total_likes
        return profile

    def _normalize_profile(self, data: dict) -> dict:
        data['email'] = str(data.get('email') or '')
        data['display_name'] = str(data.get('display_name') or data.get('displayName') or 'Ofertix User')
        data['username'] = str(data.get('username') or '')
        data['username_lower'] = str(data.get('username_lower') or data.get('usernameLower') or data['username'].lower())
        data['photo_url'] = str(data.get('photo_url') or data.get('photoUrl') or '')
        data['bio'] = str(data.get('bio') or '')
        data['country'] = str(data.get('country') or 'global')
        data['currency'] = str(data.get('currency') or 'EUR')
        data['is_creator'] = bool(data.get('is_creator') or data.get('isCreator') or False)
        for field in ['followers_count', 'following_count', 'reels_count', 'total_likes']:
            data[field] = int(data.get(field, 0) or 0)
        return data

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
            reel[field] = int(reel.get(field, 0) or 0)
        reel['hot_score'] = int(reel.get('hot_score', 50) or 50)
        reel['temperature'] = int(reel.get('temperature', reel['hot_score']) or reel['hot_score'])
        reel['deal_score'] = int(reel.get('deal_score', 50) or 50)
        reel['discount_percent'] = int(reel.get('discount_percent', 0) or 0)
        reel['status'] = str(reel.get('status') or 'approved')
        reel['provider'] = str(reel.get('provider') or 'cloudinary')
        reel['ai_verdict'] = str(reel.get('ai_verdict') or 'Oferta normal')
        reel['fake_discount_risk'] = str(reel.get('fake_discount_risk') or 'unknown')
        return reel


profile_repository = ProfileRepository()
