from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class CouponCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    code: str = Field(..., min_length=2, max_length=80)
    store: str = Field(..., min_length=2, max_length=80)
    description: str = Field(default='', max_length=300)
    country: str = Field(default='ES', min_length=2, max_length=4)
    currency: str = Field(default='EUR', min_length=3, max_length=3)
    discount_label: str = Field(default='', max_length=80)
    expires_at: Optional[str] = None
    source_url: Optional[str] = None
    created_by: str = Field(default='mobile_user', max_length=120)

    @field_validator('title', 'code', 'store', 'country', 'currency')
    @classmethod
    def clean_text(cls, value: str):
        return value.strip()


class CouponOut(BaseModel):
    id: str
    title: str
    code: str
    store: str
    description: str = ''
    country: str = 'ES'
    currency: str = 'EUR'
    discount_label: str = ''
    expires_at: Optional[str] = None
    source_url: Optional[str] = None
    created_by: str = 'mobile_user'
    status: str = 'active'
    verified_works: int = 0
    verified_failed: int = 0
    trust_score: int = 50
    hot_votes: int = 0
    cold_votes: int = 0
    hot_score: int = 50
    created_at: datetime
    updated_at: datetime


class CouponListResponse(BaseModel):
    items: List[CouponOut]


class CouponVerifyCreate(BaseModel):
    user_id: str = Field(default='mobile_user', max_length=120)
    works: bool
