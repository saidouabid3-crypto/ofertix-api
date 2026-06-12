from repositories.geo_alert_repository import geo_alert_repository


class GeoAlertService:
    def create_store_deal(self, payload, current_user: dict, status: str = 'pending'):
        user_id = str(current_user.get('uid') or '').strip()
        if not user_id:
            raise ValueError('Authenticated user is required')
        return geo_alert_repository.create_store_deal(
            payload.model_dump(),
            creator_id=user_id,
            status='active' if status == 'active' else 'pending',
        )

    def nearby(self, latitude: float, longitude: float, watchlist: str | None = None, limit: int = 20):
        watchlist_ids = []
        if watchlist:
            watchlist_ids = [x.strip() for x in watchlist.split(',') if x.strip()]
        return {'items': geo_alert_repository.nearby(latitude=latitude, longitude=longitude, watchlist=watchlist_ids, limit=limit)}


geo_alert_service = GeoAlertService()
