from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GeoStoreDealCreate(BaseModel):
    product_id: str = Field(..., min_length=2, max_length=120)
    product_title: str = Field(..., min_length=2, max_length=180)
    store: str = Field(..., min_length=2, max_length=120)
    price: float = Field(..., gt=0)
    currency: str = Field(default='EUR', min_length=3, max_length=3)
    latitude: float
    longitude: float
    radius_meters: int = Field(default=250, ge=50, le=5000)
    country: str = Field(default='ES', min_length=2, max_length=4)
    city: str = Field(default='', max_length=100)
    expires_at: Optional[str] = None


class GeoStoreDealOut(BaseModel):
    id: str
    product_id: str
    product_title: str
    store: str
    price: float
    currency: str = 'EUR'
    latitude: float
    longitude: float
    radius_meters: int = 250
    country: str = 'ES'
    city: str = ''
    expires_at: Optional[str] = None
    status: str = 'active'
    created_at: datetime
    updated_at: datetime


class NearbyDealOut(BaseModel):
    id: str
    product_id: str
    product_title: str
    store: str
    price: float
    currency: str
    distance_meters: int
    message: str


class NearbyDealResponse(BaseModel):
    items: List[NearbyDealOut]
