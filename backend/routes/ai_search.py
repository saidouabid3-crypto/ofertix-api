from fastapi import APIRouter

from schemas.ai_schema import AISearchRequest, AISearchResponse
from services.ai_service import ai_service

router = APIRouter(
    prefix="/api/ai",
    tags=["AI"],
)


@router.post("/search", response_model=AISearchResponse)
async def ai_search(payload: AISearchRequest):
    history = [
        {
            "role": item.role,
            "content": item.content,
        }
        for item in payload.history
    ]

    return await ai_service.analyze_query(
        query=payload.query,
        country_code=payload.countryCode,
        currency=payload.currency,
        language=payload.language,
        latitude=payload.latitude,
        longitude=payload.longitude,
        history=history,
    )