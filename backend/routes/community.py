from fastapi import APIRouter, Query

from schemas.community_schema import VoteCreate, VoteOut, VoteSummaryOut
from services.community_service import community_service

router = APIRouter(prefix='/community', tags=['Community Hot or Cold'])


@router.post('/vote', response_model=VoteOut)
async def vote(payload: VoteCreate):
    return community_service.vote(payload)


@router.get('/summary', response_model=VoteSummaryOut)
async def summary(
    target_type: str = Query(...),
    target_id: str = Query(...),
    user_id: str | None = Query(default=None),
):
    return community_service.summary(target_type=target_type, target_id=target_id, user_id=user_id)
