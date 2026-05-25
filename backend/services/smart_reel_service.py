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

        deal_score = DealScoreService.calculate_score(
            current_price=current_price,
            old_price=old_price,
        )

        fake_risk = FakeDiscountService.detect_risk(
            current_price=current_price,
            old_price=old_price,
        )

        data = {
            "product_id": payload.product_id,
            "title": payload.title,
            "description": payload.description or "",
            "store": payload.store,
            "current_price": current_price,
            "old_price": old_price,
            "currency": payload.currency,
            "discount_percent": discount_percent,
            "thumbnail_url": thumbnail,
            "video_mp4_url": optimized_video,
            "video_hls_url": hls_url,
            "affiliate_url": str(payload.affiliate_url) if payload.affiliate_url else "",
            "deal_score": deal_score,
            "ai_verdict": DealScoreService.ai_verdict(deal_score),
            "fake_discount_risk": fake_risk,
            "status": "approved",
            "provider": "cloudinary",
        }

        return smart_reel_repository.create(data)

    def get_feed(self, limit: int = 10, cursor: str | None = None):
        limit = max(1, min(limit, 20))
        items, next_cursor, has_more = smart_reel_repository.list_feed(
            limit=limit,
            cursor=cursor,
        )

        ranked = sorted(
            items,
            key=lambda r: (
                r.get("deal_score", 0),
                r.get("clicks", 0),
                r.get("likes", 0),
                r.get("views", 0),
            ),
            reverse=True,
        )

        return {
            "items": ranked,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def track_view(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, "views")

    def like(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, "likes")

    def click(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, "clicks")

    def save(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, "saves")

    def report(self, reel_id: str):
        return smart_reel_repository.increment(reel_id, "reports")


smart_reel_service = SmartReelService()