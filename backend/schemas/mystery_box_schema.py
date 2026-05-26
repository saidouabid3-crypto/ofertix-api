from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MysteryBoxOut(BaseModel):
    id: str
    title: str
    subtitle: str = ''
    reveal_hint: str = ''
    unlock_type: str = 'shake'
    day_key: str
    status: str = 'active'
    is_opened: bool = False
    can_open: bool = True
    opened_at: Optional[datetime] = None
    streak: int = 0
    created_at: datetime
    updated_at: datetime


class MysteryBoxOpenRequest(BaseModel):
    unlock_method: str = Field(default='shake', pattern='^(shake|riddle|manual)$')
    riddle_answer: str = Field(default='', max_length=160)
    client_nonce: str = Field(default='', max_length=120)


class MysteryRewardOut(BaseModel):
    id: str
    box_id: str
    user_id: str
    reward_type: str
    title: str
    description: str = ''
    value_label: str = ''
    coupon_code: str = ''
    deal_url: str = ''
    product_id: Optional[str] = None
    coins: int = 0
    cashback_boost: float = 0
    share_text: str = ''
    opened_at: datetime
    expires_at: Optional[str] = None


class MysteryBoxClaimRequest(BaseModel):
    reward_id: str = Field(..., min_length=2, max_length=160)


class MysteryClaimOut(BaseModel):
    ok: bool
    claimed: bool
    reward_id: str
    message: str


class MysteryBoxHistoryResponse(BaseModel):
    items: List[MysteryRewardOut]
