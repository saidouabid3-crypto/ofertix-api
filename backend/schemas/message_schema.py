from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class StartConversationRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1, max_length=120)
    receiver_name: str = Field(default='User', max_length=100)
    receiver_photo_url: str = Field(default='', max_length=700)
    text: str = Field(..., min_length=1, max_length=1000)
    reel_id: str = Field(default='', max_length=120)
    reel_title: str = Field(default='', max_length=160)
    reel_thumbnail_url: str = Field(default='', max_length=700)


class StartMarketplaceConversationRequest(BaseModel):
    listing_id: str = Field(..., min_length=1, max_length=120)
    initial_message: str = Field(default='', max_length=1000)


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


class SendOfferRequest(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = Field(default='', min_length=0, max_length=12)
    message: str = Field(default='', max_length=1000)


class ConversationOut(BaseModel):
    id: str
    participants: List[str]
    participant_names: Dict[str, str] = Field(default_factory=dict)
    participant_photos: Dict[str, str] = Field(default_factory=dict)
    last_message: str = ''
    last_sender_id: str = ''
    last_message_at: datetime
    unread_counts: Dict[str, int] = Field(default_factory=dict)
    reel_id: str = ''
    reel_title: str = ''
    reel_thumbnail_url: str = ''
    creator_id: str = ''
    listing_id: str = ''
    listing_title: str = ''
    listing_image: str = ''
    listing_price: float = 0
    listing_currency: str = ''
    listing_city: str = ''
    seller_id: str = ''
    buyer_id: str = ''
    status: str = 'active'
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    text: str
    type: str = 'text'
    # Unified per-message source context (listing, reel, direct, or empty)
    context_type: str = ''
    context_id: str = ''
    context_title: str = ''
    context_thumbnail_url: str = ''
    context_price: Optional[float] = None
    context_currency: str = ''
    # Legacy reel fields — kept for backward compat with older clients
    reel_id: str = ''
    reel_title: str = ''
    reel_thumbnail_url: str = ''
    offer_amount: Optional[float] = None
    offer_currency: str = ''
    is_read: bool = False
    created_at: datetime


class ConversationListResponse(BaseModel):
    items: List[ConversationOut]


class MessageListResponse(BaseModel):
    conversation: Optional[ConversationOut] = None
    items: List[MessageOut]
