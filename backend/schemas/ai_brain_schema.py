from typing import List, Optional

from pydantic import BaseModel, Field


class DealBrainRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=600)
    country: str = Field(default='ES', max_length=4)
    language: str = Field(default='es', max_length=8)
    currency: str = Field(default='EUR', max_length=3)
    product_id: Optional[str] = None
    current_price: Optional[float] = None
    old_price: Optional[float] = None
    store: Optional[str] = None


class DealBrainResponse(BaseModel):
    intent: str
    verdict: str
    confidence: int
    summary: str
    suggestions: List[str]
    risk_level: str
    lightweight: bool = True
