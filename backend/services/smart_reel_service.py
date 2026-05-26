from repositories.smart_reel_repository import smart_reel_repository
from services.cloudinary_service import CloudinaryService
from services.deal_score_service import DealScoreService
from services.fake_discount_service import FakeDiscountService


class SmartReelService:
    def create_reel(self, payload):
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
            'creator_id': payload.creator_id or 'mobile_user',
            'creator_name': payload.creator_name or 'Ofertix User',
            'creator_avatar_url': payload.creator_avatar_url or '',
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
            'status': 'approved',
            'provider': 'cloudinary',
        }
        return smart_reel_repository.create(data)

    def update_reel(self, reel_id: str, payload, actor_id: str = 'mobile_user'):
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

    def delete_reel(self, reel_id: str, actor_id: str = 'mobile_user'):
        return smart_reel_repository.delete(reel_id, actor_id=actor_id)

    def send_message(self, reel_id: str, payload):
        return smart_reel_repository.create_message(
            reel_id=reel_id,
            sender_id=payload.sender_id,
            sender_name=payload.sender_name,
            text=payload.text,
        )


    def get_feed(self, limit: int = 10, cursor: str | None = None, viewer_id: str | None = None):
        items, next_cursor, has_more = smart_reel_repository.list_feed(limit=limit, cursor=cursor, viewer_id=viewer_id)
        return {'items': items, 'next_cursor': next_cursor, 'has_more': has_more}

    def track_view(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'views')

    def like(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'likes')

    def click(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'clicks')

    def save(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'saves')

    def report(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, 'reports')

    def add_comment(self, reel_id: str, text: str, user_id: str = 'mobile_user', user_name: str = 'Ofertix User'):
        return smart_reel_repository.add_comment(reel_id=reel_id, text=text, user_id=user_id, user_name=user_name)

    def get_comments(self, reel_id: str, limit: int = 50):
        return {'items': smart_reel_repository.list_comments(reel_id=reel_id, limit=limit)}

    def follow_creator(self, creator_id: str, follower_id: str = 'mobile_user'):
        return smart_reel_repository.toggle_follow(creator_id=creator_id, follower_id=follower_id)


smart_reel_service = SmartReelService()
