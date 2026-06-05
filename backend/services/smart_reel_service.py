from core.firebase import db
from repositories.smart_reel_repository import smart_reel_repository
from services.cloudinary_service import CloudinaryService
from services.deal_score_service import DealScoreService
from services.fake_discount_service import FakeDiscountService


MODERATION_STATUSES = {'pending', 'approved', 'rejected'}


class SmartReelService:
    def _resolve_user_profile(self, current_user: dict | None) -> dict:
        if not current_user:
            return {
                'uid': 'mobile_user',
                'name': 'Creator',
                'photo_url': '',
                'username': '',
            }

        uid = current_user.get('uid') or ''
        name = current_user.get('name') or current_user.get('email', '').split('@')[0] or 'Creator'
        photo_url = current_user.get('picture') or ''
        username = ''

        if uid:
            snap = db.collection('users').document(uid).get()
            if snap.exists:
                data = snap.to_dict() or {}
                name = data.get('display_name') or data.get('displayName') or name
                photo_url = data.get('photo_url') or data.get('photoUrl') or photo_url
                username = data.get('username') or data.get('username_lower') or ''

        return {
            'uid': uid or 'mobile_user',
            'name': str(name or 'Creator'),
            'photo_url': str(photo_url or ''),
            'username': str(username or ''),
        }

    def create_reel(self, payload, current_user: dict | None = None):
        user_profile = self._resolve_user_profile(current_user)

        current_price = payload.current_price
        old_price = payload.old_price
        discount_percent = 0
        if old_price and old_price > current_price:
            discount_percent = int(((old_price - current_price) / old_price) * 100)

        raw_video_url = str(payload.video_url)
        optimized_video = CloudinaryService.optimize_video_url(raw_video_url)
        thumbnail = CloudinaryService.generate_thumbnail_url(raw_video_url)
        hls_url = CloudinaryService.generate_hls_url(raw_video_url)
        deal_score = DealScoreService.calculate_score(current_price=current_price, old_price=old_price)
        fake_risk = FakeDiscountService.detect_risk(current_price=current_price, old_price=old_price)

        data = {
            'product_id': payload.product_id,
            'title': payload.title,
            'description': payload.description or '',
            'store': payload.store,
            'creator_id': user_profile['uid'],
            'creator_name': user_profile['name'],
            'creator_avatar_url': user_profile['photo_url'],
            'current_price': current_price,
            'old_price': old_price,
            'currency': payload.currency,
            'discount_percent': discount_percent,
            'thumbnail_url': thumbnail,
            'video_mp4_url': optimized_video,
            'video_hls_url': hls_url,
            'affiliate_url': str(payload.affiliate_url) if payload.affiliate_url else '',
            'deal_score': deal_score,
            'ai_verdict': DealScoreService.ai_verdict(deal_score),
            'fake_discount_risk': fake_risk,
            # Uploads remain auto-approved until Batch 10 adds the moderation UI.
            # Feed code already filters for approved reels; pending/rejected are
            # reserved for the next moderation pass.
            'status': 'approved',
            'provider': 'cloudinary',
        }
        return smart_reel_repository.create(data)

    def update_reel(self, reel_id: str, payload, current_user: dict):
        actor_id = current_user['uid']
        existing = smart_reel_repository.get_by_id(reel_id)
        if not existing:
            return None

        data = {}
        payload_data = payload.model_dump(exclude_unset=True)

        text_fields = ['title', 'description', 'store', 'currency', 'product_id']
        for field in text_fields:
            if field in payload_data:
                value = payload_data.get(field)
                if isinstance(value, str):
                    value = value.strip()
                data[field] = value

        if 'affiliate_url' in payload_data:
            value = payload_data.get('affiliate_url')
            data['affiliate_url'] = str(value) if value else ''

        current_price = payload_data.get('current_price', existing.get('current_price'))
        old_price = payload_data.get('old_price', existing.get('old_price'))

        if 'current_price' in payload_data:
            data['current_price'] = current_price

        if 'old_price' in payload_data:
            data['old_price'] = old_price

        if 'current_price' in payload_data or 'old_price' in payload_data:
            discount_percent = 0
            if old_price and old_price > current_price:
                discount_percent = int(((old_price - current_price) / old_price) * 100)

            data['discount_percent'] = discount_percent
            data['deal_score'] = DealScoreService.calculate_score(
                current_price=current_price,
                old_price=old_price,
            )
            data['ai_verdict'] = DealScoreService.ai_verdict(data['deal_score'])
            data['fake_discount_risk'] = FakeDiscountService.detect_risk(
                current_price=current_price,
                old_price=old_price,
            )

        if not data:
            return existing

        return smart_reel_repository.update(reel_id, data, actor_id=actor_id)

    def delete_reel(self, reel_id: str, current_user: dict):
        return smart_reel_repository.delete(reel_id, actor_id=current_user['uid'])

    def send_message(self, reel_id: str, payload, current_user: dict):
        user_profile = self._resolve_user_profile(current_user)
        return smart_reel_repository.create_message(
            reel_id=reel_id,
            sender_id=user_profile['uid'],
            sender_name=user_profile['name'],
            text=payload.text,
        )

    def get_feed(self, limit: int = 10, cursor: str | None = None, viewer_id: str | None = None):
        items, next_cursor, has_more = smart_reel_repository.list_feed(limit=limit, cursor=cursor, viewer_id=viewer_id)
        return {'items': items, 'next_cursor': next_cursor, 'has_more': has_more}

    def track_view(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'views')

    def like(self, reel_id: str, viewer_id: str | None = None) -> dict:
        """Toggle like. Returns {is_liked, likes}. Requires viewer_id for per-user dedup."""
        if viewer_id:
            return smart_reel_repository.toggle_like(reel_id, viewer_id)
        # Anonymous like — plain increment (no per-user dedup).
        result = smart_reel_repository.increment(reel_id, 'likes')
        if not result:
            return {'is_liked': False, 'likes': 0}
        return {'is_liked': False, 'likes': result.get('likes', 0)}

    def click(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'clicks')

    def save(self, reel_id: str, viewer_id: str | None = None) -> dict:
        """Toggle save. Returns {is_saved, saves}. Requires viewer_id for per-user dedup."""
        if viewer_id:
            return smart_reel_repository.toggle_save(reel_id, viewer_id)
        result = smart_reel_repository.increment(reel_id, 'saves')
        if not result:
            return {'is_saved': False, 'saves': 0}
        return {'is_saved': False, 'saves': result.get('saves', 0)}

    def report(self, reel_id: str, viewer_id: str | None = None) -> dict:
        """Report a reel. Requires viewer_id (from verified token). Dedupes per user."""
        if viewer_id:
            return smart_reel_repository.report_once(reel_id, viewer_id)
        # Fallback — should not reach here once routes enforce require_user.
        result = smart_reel_repository.increment(reel_id, 'reports')
        if not result:
            return {'reports': 0}
        return {'reports': result.get('reports', 0)}

    def add_comment(self, reel_id: str, text: str, current_user: dict):
        user_profile = self._resolve_user_profile(current_user)
        return smart_reel_repository.add_comment(
            reel_id=reel_id,
            text=text,
            user_id=user_profile['uid'],
            user_name=user_profile['name'],
            user_avatar_url=user_profile['photo_url'],
            username=user_profile['username'],
        )

    def get_comments(self, reel_id: str, limit: int = 50):
        return {'items': smart_reel_repository.list_comments(reel_id=reel_id, limit=limit)}

    def follow_creator(self, creator_id: str, current_user: dict):
        return smart_reel_repository.toggle_follow(creator_id=creator_id, follower_id=current_user['uid'])


smart_reel_service = SmartReelService()
