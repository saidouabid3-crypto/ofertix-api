from fastapi import APIRouter

from schemas.ai_brain_schema import DealBrainRequest, DealBrainResponse
from services.ai_brain_service import ai_brain_service

router = APIRouter(prefix='/ai/brain', tags=['AI Deal Brain'])


@router.post('/analyze', response_model=DealBrainResponse)
async def analyze(payload: DealBrainRequest):
    return ai_brain_service.analyze(payload)
