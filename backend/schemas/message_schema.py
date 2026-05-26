from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ConversationCreate(BaseModel):
    buyer_id: str = Field(..., min_length=2, max_length=120)
    creator_id: str = Field(..., min_length=2, max_length=120)
    reel_id: str = Field(default='profile_contact', max_length=120)
    reel_title: str = Field(default='Contacto desde Ofertix', max_length=180)

    @field_validator('buyer_id', 'creator_id', 'reel_id', 'reel_title')
    @classmethod
    def clean_text(cls, value: str):
        return value.strip()


class ConversationOut(BaseModel):
    id: str
    buyer_id: str
    creator_id: str
    reel_id: str
    reel_title: str
    participants: List[str]
    last_message: str = ''
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    conversation_id: str = Field(..., min_length=2, max_length=180)
    sender_id: str = Field(..., min_length=2, max_length=120)
    receiver_id: str = Field(..., min_length=2, max_length=120)
    text: str = Field(..., min_length=1, max_length=1000)

    @field_validator('text')
    @classmethod
    def clean_message(cls, value: str):
        return value.strip()


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    receiver_id: str
    text: str
    type: str = 'text'
    read: bool = False
    created_at: datetime


class MessageListResponse(BaseModel):
    items: List[MessageOut]


class ConversationListResponse(BaseModel):
    items: List[ConversationOut]
