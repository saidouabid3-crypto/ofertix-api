from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel, Field


class StartConversationRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1, max_length=120)
    receiver_name: str = Field(default='User', max_length=100)
    receiver_photo_url: str = Field(default='', max_length=700)
    text: str = Field(..., min_length=1, max_length=1000)
    reel_id: str = Field(default='', max_length=120)
    reel_title: str = Field(default='', max_length=160)
    reel_thumbnail_url: str = Field(default='', max_length=700)


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)


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
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    text: str
    type: str = 'text'
    reel_id: str = ''
    reel_title: str = ''
    reel_thumbnail_url: str = ''
    is_read: bool = False
    created_at: datetime


class ConversationListResponse(BaseModel):
    items: List[ConversationOut]


class MessageListResponse(BaseModel):
    items: List[MessageOut]
