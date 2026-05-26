from fastapi import APIRouter, Depends, Query

from core.auth import optional_user, require_user
from schemas.community_schema import VoteCreate, VoteOut, VoteSummaryOut
from services.community_service import community_service

router = APIRouter(prefix='/community', tags=['Community Hot or Cold'])


@router.post('/vote', response_model=VoteOut)
async def vote(payload: VoteCreate, current_user: dict = Depends(require_user)):
    secured = payload.model_copy(update={'user_id': current_user['uid']})
    return community_service.vote(secured)


@router.get('/summary', response_model=VoteSummaryOut)
async def summary(
    target_type: str = Query(...),
    target_id: str = Query(...),
    current_user: dict | None = Depends(optional_user),
):
    user_id = current_user['uid'] if current_user else None
    return community_service.summary(target_type=target_type, target_id=target_id, user_id=user_id)
