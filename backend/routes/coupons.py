from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_user
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
async def create_coupon(payload: CouponCreate, current_user: dict = Depends(require_user)):
    secured = payload.model_copy(update={'created_by': current_user['uid']})
    return coupon_service.create(secured)


@router.post('/{coupon_id}/verify', response_model=CouponOut)
async def verify_coupon(coupon_id: str, payload: CouponVerifyCreate, current_user: dict = Depends(require_user)):
    secured = payload.model_copy(update={'user_id': current_user['uid']})
    coupon = coupon_service.verify(coupon_id=coupon_id, works=secured.works)
    if not coupon:
        raise HTTPException(status_code=404, detail='Coupon not found')
    return coupon
