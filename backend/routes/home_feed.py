from __future__ import annotations

from fastapi import APIRouter, Body, Query

from services.home_feed_service import HomeFeedService

router = APIRouter(tags=['home-feed'])
service = HomeFeedService()


@router.get('/home-feed')
def home_feed(
    country: str = Query('es'),
    userId: str | None = Query(None),
    seed: str | None = Query(None),
    limit: int = Query(24, ge=8, le=60),
):
    return service.build_home_feed(country=country, user_id=userId, seed=seed, limit=limit)


@router.get('/product-detail/{product_id}')
def product_detail(product_id: str, country: str = Query('es')):
    return service.build_product_detail(product_id, country=country)


@router.post('/events/product-view')
def product_view(payload: dict = Body(default={})):  # one write per product open from Flutter
    return service.track_event(
        event_type='product_view',
        product_id=str(payload.get('productId') or ''),
        user_id=payload.get('userId'),
        payload=payload,
    )


@router.post('/events/offer-click')
def offer_click(payload: dict = Body(default={})):  # affiliate click tracking
    return service.track_event(
        event_type='offer_click',
        product_id=str(payload.get('productId') or ''),
        user_id=payload.get('userId'),
        payload=payload,
    )


@router.post('/events/report-product')
def report_product(payload: dict = Body(default={})):
    return service.track_event(
        event_type='report_product',
        product_id=str(payload.get('productId') or ''),
        user_id=payload.get('userId'),
        payload=payload,
    )
