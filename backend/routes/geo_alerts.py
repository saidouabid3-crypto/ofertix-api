from fastapi import APIRouter, Query

from schemas.geo_alert_schema import GeoStoreDealCreate, GeoStoreDealOut, NearbyDealResponse
from services.geo_alert_service import geo_alert_service

router = APIRouter(prefix='/geo-alerts', tags=['Geo Fencing Alerts'])


@router.post('/store-deals', response_model=GeoStoreDealOut)
async def create_store_deal(payload: GeoStoreDealCreate):
    return geo_alert_service.create_store_deal(payload)


@router.get('/nearby', response_model=NearbyDealResponse)
async def nearby_deals(
    latitude: float = Query(...),
    longitude: float = Query(...),
    watchlist: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
):
    return geo_alert_service.nearby(latitude=latitude, longitude=longitude, watchlist=watchlist, limit=limit)
