from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_active_user, require_user
from schemas.message_schema import (
    ConversationListResponse,
    ConversationOut,
    MessageListResponse,
    MessageOut,
    SendMessageRequest,
    StartConversationRequest,
)
from services.message_service import message_service

router = APIRouter(prefix='/messages', tags=['Messages'])


@router.post('/start', response_model=ConversationOut)
async def start_conversation(
    payload: StartConversationRequest,
    current_user: dict = Depends(require_active_user),
):
    try:
        item = message_service.start_conversation(payload, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not item:
        raise HTTPException(status_code=400, detail='Could not start conversation')

    return item


@router.get('/inbox', response_model=ConversationListResponse)
async def get_inbox(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(require_user),
):
    return message_service.get_inbox(current_user=current_user, limit=limit)


@router.get('/conversations/{conversation_id}', response_model=MessageListResponse)
async def get_conversation(
    conversation_id: str,
    limit: int = Query(default=80, ge=1, le=120),
    current_user: dict = Depends(require_user),
):
    return message_service.get_conversation_messages(
        conversation_id=conversation_id,
        current_user=current_user,
        limit=limit,
    )


@router.post('/conversations/{conversation_id}/send', response_model=MessageOut)
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    current_user: dict = Depends(require_active_user),
):
    item = message_service.send_message(
        conversation_id=conversation_id,
        payload=payload,
        current_user=current_user,
    )

    if not item:
        raise HTTPException(status_code=404, detail='Conversation not found or forbidden')

    return item


@router.post('/conversations/{conversation_id}/read', response_model=ConversationOut)
async def mark_read(
    conversation_id: str,
    current_user: dict = Depends(require_user),
):
    item = message_service.mark_read(conversation_id=conversation_id, current_user=current_user)

    if not item:
        raise HTTPException(status_code=404, detail='Conversation not found or forbidden')

    return item
