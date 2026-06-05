from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class UserDealCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=140)
    description: str = Field(default='', max_length=400)
    store: str = Field(..., min_length=2, max_length=100)
    current_price: float = Field(..., gt=0)
    old_price: Optional[float] = Field(default=None, gt=0)
    currency: str = Field(default='EUR', min_length=3, max_length=3)
    country: str = Field(default='ES', min_length=2, max_length=4)
    city: str = Field(default='', max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    media_url: str = Field(default='', max_length=700)
    creator_id: str = Field(default='mobile_user', max_length=120)
    creator_name: str = Field(default='User', max_length=100)

    @field_validator('title', 'store', 'currency', 'country')
    @classmethod
    def clean_text(cls, value: str):
        return value.strip()


class UserDealOut(BaseModel):
    id: str
    title: str
    description: str = ''
    store: str
    current_price: float
    old_price: Optional[float] = None
    currency: str = 'EUR'
    discount_percent: int = 0
    country: str = 'ES'
    city: str = ''
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    media_url: str = ''
    creator_id: str = 'mobile_user'
    creator_name: str = 'User'
    status: str = 'pending'
    ai_status: str = 'not_checked'
    reward_points: int = 0
    hot_votes: int = 0
    cold_votes: int = 0
    hot_score: int = 50
    created_at: datetime
    updated_at: datetime


class UserDealListResponse(BaseModel):
    items: List[UserDealOut]
