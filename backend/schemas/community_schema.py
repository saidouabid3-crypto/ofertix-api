from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class VoteCreate(BaseModel):
    target_type: str = Field(..., pattern='^(product|reel|coupon|user_deal)$')
    target_id: str = Field(..., min_length=2, max_length=160)
    user_id: str = Field(..., min_length=2, max_length=120)
    vote: str = Field(..., pattern='^(hot|cold)$')

    @field_validator('target_id', 'user_id')
    @classmethod
    def clean_text(cls, value: str):
        return value.strip()


class VoteOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    user_id: str
    vote: str
    created_at: datetime
    updated_at: datetime


class VoteSummaryOut(BaseModel):
    target_type: str
    target_id: str
    hot_votes: int = 0
    cold_votes: int = 0
    hot_score: int = 50
    temperature: int = 50
    user_vote: Optional[str] = None


class VoteListResponse(BaseModel):
    items: List[VoteOut]
