from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import Optional, List
from datetime import datetime


class SmartReelCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: Optional[str] = Field(default="", max_length=300)
    store: str = Field(..., min_length=2, max_length=80)

    current_price: float = Field(..., gt=0)
    old_price: Optional[float] = Field(default=None, gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)

    video_url: HttpUrl
    affiliate_url: Optional[HttpUrl] = None
    product_id: Optional[str] = Field(default=None, max_length=80)

    @field_validator("title", "store")
    @classmethod
    def reject_swagger_defaults(cls, value: str):
        if value.strip().lower() in {"string", "test", "demo"}:
            raise ValueError("Invalid default value. Please provide real data.")
        return value.strip()

    @field_validator("old_price")
    @classmethod
    def old_price_must_be_valid(cls, value, info):
        current_price = info.data.get("current_price")
        if value is not None and current_price is not None and value < current_price:
            raise ValueError("old_price must be greater than or equal to current_price")
        return value


class SmartReelOut(BaseModel):
    id: str
    product_id: Optional[str] = None

    title: str
    description: Optional[str] = ""
    store: str

    current_price: float
    old_price: Optional[float] = None
    currency: str = "EUR"
    discount_percent: int = 0

    thumbnail_url: str
    video_mp4_url: str
    video_hls_url: Optional[str] = None
    affiliate_url: Optional[str] = ""

    deal_score: int = Field(default=50, ge=0, le=100)
    ai_verdict: str = "Oferta normal"
    fake_discount_risk: str = "unknown"

    status: str = "approved"
    provider: str = "cloudinary"

    views: int = 0
    likes: int = 0
    clicks: int = 0
    saves: int = 0
    reports: int = 0

    created_at: datetime


class SmartReelFeedResponse(BaseModel):
    items: List[SmartReelOut]
    next_cursor: Optional[str] = None
    has_more: bool = False