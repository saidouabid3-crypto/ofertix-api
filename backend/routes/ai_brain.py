from fastapi import APIRouter, Depends, Query

from core.auth import require_user
from schemas.ai_brain_schema import DealBrainHistoryResponse, DealBrainRequest, DealBrainResponse
from services.ai_brain_service import ai_brain_service

router = APIRouter(prefix='/ai/brain', tags=['AI Deal Brain'])


@router.post('/analyze', response_model=DealBrainResponse)
async def analyze(payload: DealBrainRequest, current_user: dict = Depends(require_user)):
    return await ai_brain_service.analyze(payload=payload, current_user=current_user)


@router.get('/history', response_model=DealBrainHistoryResponse)
async def history(limit: int = Query(default=30, ge=1, le=50), current_user: dict = Depends(require_user)):
    return ai_brain_service.history(current_user=current_user, limit=limit)
