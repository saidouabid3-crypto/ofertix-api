from repositories.user_deal_repository import user_deal_repository


class UserDealService:
    def create(self, payload):
        return user_deal_repository.create(payload.model_dump())

    def list(self, country: str | None = None, city: str | None = None, status: str | None = None, limit: int = 50):
        return {'items': user_deal_repository.list(country=country, city=city, status=status, limit=limit)}

    def moderate(self, deal_id: str, status: str):
        return user_deal_repository.moderate(deal_id=deal_id, status=status)


user_deal_service = UserDealService()
