from datetime import datetime
from typing import Optional

from core.firebase import db
from repositories.marketplace_repository import is_public_marketplace_item


class ProfileRepository:
    USERS_COLLECTION = 'users'
    REELS_COLLECTION = 'smart_reels'
    MARKETPLACE_COLLECTION = 'marketplace_items'
    FOLLOWS_COLLECTION = 'user_follows'

    def __init__(self):
        self.users = db.collection(self.USERS_COLLECTION) if db is not None else None
        self.reels = db.collection(self.REELS_COLLECTION) if db is not None else None
        self.marketplace = (
            db.collection(self.MARKETPLACE_COLLECTION) if db is not None else None
        )
        self.follows = db.collection(self.FOLLOWS_COLLECTION) if db is not None else None

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

    def get_sell_items(self, seller_id: str, limit: int = 30) -> list[dict]:
        seller_id = (seller_id or '').strip()
        if not seller_id:
            return []

        limit = max(1, min(limit, 50))
        docs = list(
            self.marketplace
            .where('sellerId', '==', seller_id)
            .limit(limit * 2)
            .stream()
        )

        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            if not is_public_marketplace_item(data):
                continue
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_sell_item(data))
            if len(items) >= limit:
                break

        items.sort(key=lambda x: str(x.get('createdAt') or x.get('created_at') or ''), reverse=True)
        return items

    def update_profile(self, uid: str, data: dict) -> Optional[dict]:
        uid = (uid or '').strip()
        if not uid:
            return None

        allowed_fields = {
            'display_name', 'username', 'username_lower',
            'photo_url', 'avatar_url', 'bio', 'country', 'city', 'currency', 'is_creator',
        }
        clean = {k: v for k, v in data.items() if k in allowed_fields and v is not None}
        if not clean:
            return self.get_profile(uid)

        clean['updated_at'] = datetime.utcnow().isoformat()
        self.users.document(uid).set(clean, merge=True)

        snap = self.users.document(uid).get()
        updated = snap.to_dict() or {} if snap.exists else {}
        updated['uid'] = uid
        return self._normalize_profile(updated)

    def sync_creator_counters(self, uid: str) -> Optional[dict]:
        profile = self.get_profile(uid)
        if not profile:
            return None

        reels = self.get_creator_reels(uid, limit=50)
        total_likes = sum(int(item.get('likes', 0)) for item in reels)
        sell_items_count = self.count_sell_items(uid)

        self.users.document(uid).set(
            {
                'reels_count': len(reels),
                'sell_items_count': sell_items_count,
                'total_likes': total_likes,
                'updated_at': datetime.utcnow().isoformat(),
            },
            merge=True,
        )

        profile['reels_count'] = len(reels)
        profile['sell_items_count'] = sell_items_count
        profile['total_likes'] = total_likes
        return profile

    def count_sell_items(self, uid: str) -> int:
        uid = (uid or '').strip()
        if not uid:
            return 0
        count = 0
        docs = list(self.marketplace.where('sellerId', '==', uid).limit(100).stream())
        for doc in docs:
            data = doc.to_dict() or {}
            if not is_public_marketplace_item(data):
                continue
            count += 1
        return count

    def follow_profile(self, target_uid: str, follower_uid: str) -> dict:
        target_uid = (target_uid or '').strip()
        follower_uid = (follower_uid or '').strip()
        if not target_uid or not follower_uid or target_uid == follower_uid:
            return {'ok': False, 'is_following': False}

        follow_id = f'{follower_uid}_{target_uid}'
        follow_ref = self.follows.document(follow_id)
        if follow_ref.get().exists:
            return {'ok': True, 'is_following': True}

        follow_ref.set({
            'id': follow_id,
            'creator_id': target_uid,
            'target_uid': target_uid,
            'follower_id': follower_uid,
            'created_at': datetime.utcnow().isoformat(),
        })
        self._increment_counter(target_uid, 'followers_count', 1)
        self._increment_counter(follower_uid, 'following_count', 1)
        return {'ok': True, 'is_following': True}

    def unfollow_profile(self, target_uid: str, follower_uid: str) -> dict:
        target_uid = (target_uid or '').strip()
        follower_uid = (follower_uid or '').strip()
        if not target_uid or not follower_uid or target_uid == follower_uid:
            return {'ok': False, 'is_following': False}

        follow_id = f'{follower_uid}_{target_uid}'
        follow_ref = self.follows.document(follow_id)
        if follow_ref.get().exists:
            follow_ref.delete()
            self._increment_counter(target_uid, 'followers_count', -1)
            self._increment_counter(follower_uid, 'following_count', -1)
        return {'ok': True, 'is_following': False}

    def _increment_counter(self, uid: str, field: str, amount: int) -> None:
        if not uid:
            return
        snap = self.users.document(uid).get()
        current = int((snap.to_dict() or {}).get(field, 0) or 0) if snap.exists else 0
        self.users.document(uid).set(
            {field: max(0, current + amount), 'updated_at': datetime.utcnow().isoformat()},
            merge=True,
        )

    def _normalize_profile(self, data: dict) -> dict:
        username = str(data.get('username') or '')
        photo_url = str(
            data.get('photo_url')
            or data.get('photoUrl')
            or data.get('avatar_url')
            or ''
        )
        return {
            'uid': str(data.get('uid') or ''),
            'display_name': str(
                data.get('display_name')
                or data.get('displayName')
                or data.get('name')
                or ''
            ),
            'username': username,
            'username_lower': str(
                data.get('username_lower')
                or data.get('usernameLower')
                or username.lower()
            ),
            'photo_url': photo_url,
            'avatar_url': str(data.get('avatar_url') or photo_url),
            'bio': str(data.get('bio') or ''),
            'country': str(data.get('country') or 'global'),
            'city': str(data.get('city') or ''),
            'currency': str(data.get('currency') or 'EUR'),
            'is_creator': bool(
                data.get('is_creator') or data.get('isCreator') or False
            ),
            'is_verified': bool(
                data.get('is_verified')
                or data.get('isVerified')
                or data.get('verified')
                or False
            ),
            'seller_verified': bool(
                data.get('seller_verified')
                or data.get('sellerVerified')
                or False
            ),
            'followers_count': int(data.get('followers_count', 0) or 0),
            'following_count': int(data.get('following_count', 0) or 0),
            'reels_count': int(data.get('reels_count', 0) or 0),
            'sell_items_count': int(data.get('sell_items_count', 0) or 0),
            'total_likes': int(data.get('total_likes', 0) or 0),
            'rating_average': float(
                data.get('rating_average') or data.get('ratingAverage') or 0
            ),
            'rating_count': int(data.get('rating_count', 0) or 0),
            'created_at': data.get('created_at') or data.get('createdAt'),
            'updated_at': data.get('updated_at') or data.get('updatedAt'),
        }

    def _normalize_sell_item(self, item: dict) -> dict:
        item['sellerId'] = str(item.get('sellerId') or item.get('seller_id') or '')
        item['sellerName'] = str(item.get('sellerName') or item.get('seller_name') or '')
        item['sellerUsername'] = str(item.get('sellerUsername') or item.get('seller_username') or '')
        item['sellerAvatarUrl'] = str(
            item.get('sellerAvatarUrl') or item.get('seller_avatar_url') or item.get('sellerPhotoUrl') or ''
        )
        item['sellerVerified'] = bool(item.get('sellerVerified') or item.get('seller_verified') or False)
        return item

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
