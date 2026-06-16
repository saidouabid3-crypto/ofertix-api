from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateReviewRequest(BaseModel):
    listing_id: str = Field(..., min_length=1, max_length=120)
    conversation_id: str = Field(default='', max_length=180)
    reviewee_id: str = Field(..., min_length=1, max_length=120)
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(default='', max_length=500)


class ReviewOut(BaseModel):
    id: str
    listing_id: str
    conversation_id: str = ''
    reviewer_id: str
    reviewer_name: str = ''
    reviewee_id: str
    rating: int
    comment: str = ''
    status: str = 'active'
    created_at: datetime
    updated_at: Optional[datetime] = None


class ReviewListResponse(BaseModel):
    items: list[ReviewOut]
    average: float = 0
    count: int = 0
