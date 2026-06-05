from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class MessageRepository:
    CONVERSATIONS = 'conversations'
    MESSAGES = 'chat_messages'
    USERS = 'users'

    def __init__(self):
        self.conversations = db.collection(self.CONVERSATIONS)
        self.messages = db.collection(self.MESSAGES)
        self.users = db.collection(self.USERS)

    def start_conversation(self, payload, current_user: dict) -> dict:
        sender_id = current_user['uid']
        receiver_id = payload.receiver_id.strip()

        if not sender_id or not receiver_id or sender_id == receiver_id:
            raise ValueError('Invalid participants')

        sender_profile = self._get_user_snapshot(sender_id, fallback=current_user)
        conversation_id = self._conversation_id(sender_id, receiver_id, payload.reel_id)
        now = datetime.utcnow().isoformat()

        conv_ref = self.conversations.document(conversation_id)
        snap = conv_ref.get()

        if not snap.exists:
            conversation = {
                'id': conversation_id,
                'participants': [sender_id, receiver_id],
                'participant_names': {
                    sender_id: sender_profile['name'],
                    receiver_id: payload.receiver_name or 'User',
                },
                'participant_photos': {
                    sender_id: sender_profile['photo_url'],
                    receiver_id: payload.receiver_photo_url or '',
                },
                'last_message': '',
                'last_sender_id': '',
                'last_message_at': now,
                'unread_counts': {sender_id: 0, receiver_id: 0},
                'reel_id': payload.reel_id or '',
                'reel_title': payload.reel_title or '',
                'reel_thumbnail_url': payload.reel_thumbnail_url or '',
                'creator_id': receiver_id,
                'created_at': now,
                'updated_at': now,
            }
            conv_ref.set(conversation)
        else:
            conversation = snap.to_dict() or {}
            conversation['id'] = conversation.get('id') or conversation_id
            if sender_id not in (conversation.get('participants') or []):
                raise PermissionError('Forbidden conversation')

        self.add_message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            sender_name=sender_profile['name'],
            text=payload.text,
            reel_id=payload.reel_id,
            reel_title=payload.reel_title,
            reel_thumbnail_url=payload.reel_thumbnail_url,
        )

        return self.get_conversation(conversation_id, current_user={'uid': sender_id}) or conversation

    def add_message(
        self,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        reel_id: str = '',
        reel_title: str = '',
        reel_thumbnail_url: str = '',
    ) -> Optional[dict]:
        conversation = self.get_conversation(conversation_id, current_user={'uid': sender_id})
        if not conversation:
            return None

        participants = conversation.get('participants') or []
        if sender_id not in participants:
            return None

        now = datetime.utcnow().isoformat()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'sender_name': sender_name or 'User',
            'text': text.strip(),
            'type': 'text',
            'reel_id': reel_id or conversation.get('reel_id') or '',
            'reel_title': reel_title or conversation.get('reel_title') or '',
            'reel_thumbnail_url': reel_thumbnail_url or conversation.get('reel_thumbnail_url') or '',
            'is_read': False,
            'created_at': now,
        }

        self.messages.document(message_id).set(message)

        unread = dict(conversation.get('unread_counts') or {})
        for uid in participants:
            unread[uid] = int(unread.get(uid, 0) or 0)
            if uid != sender_id:
                unread[uid] += 1

        self.conversations.document(conversation_id).set(
            {
                'last_message': message['text'],
                'last_sender_id': sender_id,
                'last_message_at': now,
                'unread_counts': unread,
                'updated_at': now,
            },
            merge=True,
        )

        return self._normalize_message(message)

    def get_inbox(self, current_user: dict, limit: int = 50) -> list[dict]:
        user_id = current_user['uid']
        limit = max(1, min(limit, 100))

        docs = list(
            self.conversations
            .where('participants', 'array_contains', user_id)
            .limit(120)
            .stream()
        )

        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_conversation(data))

        items.sort(key=lambda x: str(x.get('last_message_at') or ''), reverse=True)
        return items[:limit]

    def get_conversation(self, conversation_id: str, current_user: dict) -> Optional[dict]:
        user_id = current_user['uid']
        snap = self.conversations.document(conversation_id).get()
        if not snap.exists:
            return None

        data = snap.to_dict() or {}
        data['id'] = data.get('id') or conversation_id

        if user_id not in (data.get('participants') or []):
            return None

        return self._normalize_conversation(data)

    def list_messages(self, conversation_id: str, current_user: dict, limit: int = 80) -> list[dict]:
        conversation = self.get_conversation(conversation_id, current_user=current_user)
        if not conversation:
            return []

        limit = max(1, min(limit, 120))
        docs = list(
            self.messages
            .where('conversation_id', '==', conversation_id)
            .limit(limit)
            .stream()
        )

        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_message(data))

        items.sort(key=lambda x: str(x.get('created_at') or ''))
        return items

    def mark_read(self, conversation_id: str, current_user: dict) -> Optional[dict]:
        user_id = current_user['uid']
        conversation = self.get_conversation(conversation_id, current_user=current_user)
        if not conversation:
            return None

        unread = dict(conversation.get('unread_counts') or {})
        unread[user_id] = 0

        self.conversations.document(conversation_id).set(
            {'unread_counts': unread, 'updated_at': datetime.utcnow().isoformat()},
            merge=True,
        )

        conversation['unread_counts'] = unread
        return conversation

    def _conversation_id(self, sender_id: str, receiver_id: str, reel_id: str = '') -> str:
        a, b = sorted([sender_id, receiver_id])
        suffix = (reel_id or 'general').strip() or 'general'
        safe = ''.join(ch if ch.isalnum() or ch in ['_', '-'] else '_' for ch in suffix)
        return f'conv_{a}_{b}_{safe}'[:180]

    def _get_user_snapshot(self, uid: str, fallback: dict | None = None) -> dict:
        fallback = fallback or {}
        snap = self.users.document(uid).get()
        data = snap.to_dict() or {} if snap.exists else {}

        name = (
            data.get('display_name')
            or data.get('displayName')
            or fallback.get('name')
            or fallback.get('email', '').split('@')[0]
            or 'User'
        )

        photo = data.get('photo_url') or data.get('photoUrl') or fallback.get('picture') or ''

        return {'name': str(name), 'photo_url': str(photo)}

    def _normalize_conversation(self, data: dict) -> dict:
        data['participants'] = list(data.get('participants') or [])
        data['participant_names'] = dict(data.get('participant_names') or {})
        data['participant_photos'] = dict(data.get('participant_photos') or {})
        data['last_message'] = str(data.get('last_message') or '')
        data['last_sender_id'] = str(data.get('last_sender_id') or '')
        data['unread_counts'] = {str(k): int(v or 0) for k, v in dict(data.get('unread_counts') or {}).items()}
        data['reel_id'] = str(data.get('reel_id') or '')
        data['reel_title'] = str(data.get('reel_title') or '')
        data['reel_thumbnail_url'] = str(data.get('reel_thumbnail_url') or '')
        data['creator_id'] = str(data.get('creator_id') or '')
        return data

    def _normalize_message(self, data: dict) -> dict:
        data['conversation_id'] = str(data.get('conversation_id') or '')
        data['sender_id'] = str(data.get('sender_id') or '')
        data['sender_name'] = str(data.get('sender_name') or 'User')
        data['text'] = str(data.get('text') or '')
        data['type'] = str(data.get('type') or 'text')
        data['reel_id'] = str(data.get('reel_id') or '')
        data['reel_title'] = str(data.get('reel_title') or '')
        data['reel_thumbnail_url'] = str(data.get('reel_thumbnail_url') or '')
        data['is_read'] = bool(data.get('is_read') or False)
        return data


message_repository = MessageRepository()
