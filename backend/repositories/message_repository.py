from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class MessageRepository:
    CONVERSATIONS_COLLECTION = 'conversations'
    MESSAGES_COLLECTION = 'messages'

    def __init__(self):
        self.conversations = db.collection(self.CONVERSATIONS_COLLECTION)
        self.messages = db.collection(self.MESSAGES_COLLECTION)

    def open_conversation(self, buyer_id: str, creator_id: str, reel_id: str = 'profile_contact', reel_title: str = 'Contacto desde Ofertix') -> dict:
        buyer_id = buyer_id.strip()
        creator_id = creator_id.strip()
        reel_id = reel_id.strip() or 'profile_contact'
        reel_title = reel_title.strip() or 'Contacto desde Ofertix'
        conversation_id = f'{buyer_id}_{creator_id}_{reel_id}'
        ref = self.conversations.document(conversation_id)
        snap = ref.get()
        now = datetime.utcnow().isoformat()
        if snap.exists:
            data = snap.to_dict() or {}
            data['id'] = data.get('id') or conversation_id
            return self._normalize_conversation(data)
        data = {
            'id': conversation_id,
            'buyer_id': buyer_id,
            'creator_id': creator_id,
            'reel_id': reel_id,
            'reel_title': reel_title,
            'participants': [buyer_id, creator_id],
            'last_message': '',
            'last_message_at': None,
            'created_at': now,
            'updated_at': now,
        }
        ref.set(data)
        return data

    def send_message(self, conversation_id: str, sender_id: str, receiver_id: str, text: str) -> Optional[dict]:
        conversation_id = conversation_id.strip()
        sender_id = sender_id.strip()
        receiver_id = receiver_id.strip()
        text = text.strip()
        if not conversation_id or not sender_id or not receiver_id or not text:
            return None
        conv_ref = self.conversations.document(conversation_id)
        if not conv_ref.get().exists:
            return None
        now = datetime.utcnow().isoformat()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'receiver_id': receiver_id,
            'text': text,
            'type': 'text',
            'read': False,
            'created_at': now,
        }
        self.messages.document(message_id).set(message)
        conv_ref.set({'last_message': text, 'last_message_at': now, 'updated_at': now}, merge=True)
        return message

    def list_messages(self, conversation_id: str, limit: int = 80) -> list[dict]:
        limit = max(1, min(limit, 100))
        docs = list(self.messages.where('conversation_id', '==', conversation_id).limit(limit).stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_message(data))
        items.sort(key=lambda m: str(m.get('created_at') or ''), reverse=True)
        return items

    def list_user_conversations(self, user_id: str, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 100))
        docs = list(self.conversations.where('participants', 'array_contains', user_id).limit(limit).stream())
        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_conversation(data))
        items.sort(key=lambda c: str(c.get('updated_at') or ''), reverse=True)
        return items

    def _normalize_conversation(self, data: dict) -> dict:
        data['last_message'] = data.get('last_message') or ''
        data['participants'] = data.get('participants') or []
        if data.get('last_message_at') == '':
            data['last_message_at'] = None
        return data

    def _normalize_message(self, data: dict) -> dict:
        data['type'] = data.get('type') or 'text'
        data['read'] = bool(data.get('read', False))
        return data


message_repository = MessageRepository()
