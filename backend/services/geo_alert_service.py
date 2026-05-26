from repositories.geo_alert_repository import geo_alert_repository


class GeoAlertService:
    def create_store_deal(self, payload):
        return geo_alert_repository.create_store_deal(payload.model_dump())

    def nearby(self, latitude: float, longitude: float, watchlist: str | None = None, limit: int = 20):
        watchlist_ids = []
        if watchlist:
            watchlist_ids = [x.strip() for x in watchlist.split(',') if x.strip()]
        return {'items': geo_alert_repository.nearby(latitude=latitude, longitude=longitude, watchlist=watchlist_ids, limit=limit)}


geo_alert_service = GeoAlertService()
