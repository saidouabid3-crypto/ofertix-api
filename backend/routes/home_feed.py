from fastapi import APIRouter, Query
from services.home_feed_service import build_home_feed

router = APIRouter(prefix='/home-feed', tags=['home-feed'])


@router.get('')
def home_feed(country: str = 'es', limit: int = Query(40, ge=10, le=100)):
    return build_home_feed(country=country, limit=limit)
