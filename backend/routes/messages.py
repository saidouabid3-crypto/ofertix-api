from fastapi import APIRouter, HTTPException, Query

from schemas.message_schema import ConversationCreate, ConversationListResponse, ConversationOut, MessageCreate, MessageListResponse, MessageOut
from services.message_service import message_service

router = APIRouter(prefix='/messages', tags=['Messages'])


@router.post('/conversations', response_model=ConversationOut)
async def open_conversation(payload: ConversationCreate):
    if payload.buyer_id == payload.creator_id:
        raise HTTPException(status_code=400, detail='buyer_id and creator_id cannot be the same')
    return message_service.open_conversation(buyer_id=payload.buyer_id, creator_id=payload.creator_id, reel_id=payload.reel_id, reel_title=payload.reel_title)


@router.get('/conversations', response_model=ConversationListResponse)
async def list_user_conversations(user_id: str = Query(..., min_length=2), limit: int = Query(default=50, ge=1, le=100)):
    return message_service.list_user_conversations(user_id=user_id, limit=limit)


@router.get('/conversations/{conversation_id}', response_model=MessageListResponse)
async def list_messages(conversation_id: str, limit: int = Query(default=80, ge=1, le=100)):
    return message_service.list_messages(conversation_id=conversation_id, limit=limit)


@router.post('/send', response_model=MessageOut)
async def send_message(payload: MessageCreate):
    message = message_service.send_message(conversation_id=payload.conversation_id, sender_id=payload.sender_id, receiver_id=payload.receiver_id, text=payload.text)
    if not message:
        raise HTTPException(status_code=404, detail='Conversation not found or invalid message')
    return message
