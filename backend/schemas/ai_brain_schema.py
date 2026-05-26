from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DealBrainRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=900)
    country: str = Field(default='ES', max_length=4)
    language: str = Field(default='es', max_length=8)
    currency: str = Field(default='EUR', max_length=3)
    product_id: Optional[str] = None
    reel_id: Optional[str] = None
    mystery_reward_id: Optional[str] = None
    title: Optional[str] = None
    store: Optional[str] = None
    current_price: Optional[float] = None
    old_price: Optional[float] = None
    category: Optional[str] = None
    specs: Optional[str] = Field(default=None, max_length=1200)


class DealBrainResponse(BaseModel):
    id: str = ''
    intent: str
    verdict: str
    score: int = Field(default=50, ge=0, le=100)
    confidence: int = Field(default=70, ge=0, le=100)
    summary: str
    risk_level: str
    fake_discount_risk: str = 'unknown'
    price_signal: str = 'unknown'
    best_action: str = 'compare'
    savings_estimate: float = 0
    fair_price_estimate: Optional[float] = None
    suggestions: List[str]
    alternatives: List[str] = Field(default_factory=list)
    specs_explained: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    model_used: str = 'rules_plus_groq_optional'
    created_at: Optional[datetime] = None


class DealBrainHistoryResponse(BaseModel):
    items: List[DealBrainResponse]
