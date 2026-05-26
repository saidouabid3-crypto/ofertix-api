from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_user
from schemas.mystery_box_schema import (
    MysteryBoxClaimRequest,
    MysteryBoxHistoryResponse,
    MysteryBoxOpenRequest,
    MysteryBoxOut,
    MysteryClaimOut,
    MysteryRewardOut,
)
from services.mystery_box_service import mystery_box_service

router = APIRouter(prefix='/mystery-box', tags=['Mystery Box'])


@router.get('/today', response_model=MysteryBoxOut)
async def today(current_user: dict = Depends(require_user)):
    return mystery_box_service.today(current_user=current_user)


@router.post('/open', response_model=MysteryRewardOut)
async def open_box(payload: MysteryBoxOpenRequest, current_user: dict = Depends(require_user)):
    try:
        return mystery_box_service.open(payload=payload, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post('/claim', response_model=MysteryClaimOut)
async def claim(payload: MysteryBoxClaimRequest, current_user: dict = Depends(require_user)):
    item = mystery_box_service.claim(payload=payload, current_user=current_user)
    if not item:
        raise HTTPException(status_code=404, detail='Reward not found or forbidden')
    return item


@router.get('/history', response_model=MysteryBoxHistoryResponse)
async def history(limit: int = Query(default=30, ge=1, le=50), current_user: dict = Depends(require_user)):
    return mystery_box_service.history(current_user=current_user, limit=limit)
