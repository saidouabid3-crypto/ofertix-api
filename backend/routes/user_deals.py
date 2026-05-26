from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_user
from schemas.user_deal_schema import UserDealCreate, UserDealListResponse, UserDealOut
from services.user_deal_service import user_deal_service

router = APIRouter(prefix='/user-deals', tags=['User Generated Deals'])


@router.get('', response_model=UserDealListResponse)
async def list_user_deals(
    country: str | None = Query(default=None),
    city: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    return user_deal_service.list(country=country, city=city, status=status, limit=limit)


@router.post('', response_model=UserDealOut)
async def create_user_deal(payload: UserDealCreate, current_user: dict = Depends(require_user)):
    name = current_user.get('name') or current_user.get('email', '').split('@')[0] or 'Ofertix User'
    secured = payload.model_copy(update={'creator_id': current_user['uid'], 'creator_name': name})
    return user_deal_service.create(secured)


@router.post('/{deal_id}/moderate', response_model=UserDealOut)
async def moderate_user_deal(
    deal_id: str,
    status: str = Query(..., pattern='^(pending|approved|rejected)$'),
    current_user: dict = Depends(require_user),
):
    # Admin roles can be added later through custom Firebase claims. Token is required now.
    item = user_deal_service.moderate(deal_id=deal_id, status=status)
    if not item:
        raise HTTPException(status_code=404, detail='User deal not found')
    return item
