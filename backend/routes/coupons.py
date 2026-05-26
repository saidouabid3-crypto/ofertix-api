from fastapi import APIRouter, HTTPException, Query

from schemas.coupon_schema import CouponCreate, CouponListResponse, CouponOut, CouponVerifyCreate
from services.coupon_service import coupon_service

router = APIRouter(prefix='/coupons', tags=['Coupons'])


@router.get('', response_model=CouponListResponse)
async def list_coupons(
    country: str | None = Query(default=None),
    store: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    return coupon_service.list(country=country, store=store, limit=limit)


@router.post('', response_model=CouponOut)
async def create_coupon(payload: CouponCreate):
    return coupon_service.create(payload)


@router.post('/{coupon_id}/verify', response_model=CouponOut)
async def verify_coupon(coupon_id: str, payload: CouponVerifyCreate):
    coupon = coupon_service.verify(coupon_id=coupon_id, works=payload.works)
    if not coupon:
        raise HTTPException(status_code=404, detail='Coupon not found')
    return coupon
