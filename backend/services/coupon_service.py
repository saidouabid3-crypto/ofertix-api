from repositories.coupon_repository import coupon_repository


class CouponService:
    def create(self, payload):
        return coupon_repository.create(payload.model_dump())

    def list(self, country: str | None = None, store: str | None = None, limit: int = 50):
        return {'items': coupon_repository.list(country=country, store=store, limit=limit)}

    def verify(self, coupon_id: str, works: bool):
        return coupon_repository.verify(coupon_id=coupon_id, works=works)


coupon_service = CouponService()
