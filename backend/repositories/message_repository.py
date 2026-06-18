import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from core.firebase import db
from repositories.marketplace_repository import is_public_marketplace_item
from services.push_notification_service import push_notification_service

logger = logging.getLogger("ofertix.messages")


class MessageRepository:
    CONVERSATIONS = 'conversations'
    MESSAGES = 'chat_messages'
    USERS = 'users'
    MARKETPLACE_ITEMS = 'marketplace_items'

    def __init__(self):
        self.conversations = db.collection(self.CONVERSATIONS)
        self.messages = db.collection(self.MESSAGES)
        self.users = db.collection(self.USERS)
        self.marketplace_items = db.collection(self.MARKETPLACE_ITEMS)

    # ------------------------------------------------------------------
    # Conversation creation
    # ------------------------------------------------------------------

    def start_conversation(self, payload, current_user: dict) -> dict:
        """Start or resume the canonical conversation between two users.

        Reel / profile / direct contexts attach to the initial message only.
        The conversation document is a plain person-to-person thread.
        """
        sender_id = current_user['uid']
        receiver_id = payload.receiver_id.strip()

        if not sender_id or not receiver_id or sender_id == receiver_id:
            raise ValueError('Invalid participants')

        sender_profile = self._get_user_snapshot(sender_id, fallback=current_user)
        receiver_profile = self._get_user_snapshot(
            receiver_id,
            fallback={
                'name': payload.receiver_name or 'User',
                'picture': payload.receiver_photo_url or '',
            },
        )
        conversation_id = self._conversation_id(sender_id, receiver_id)
        now = datetime.now(timezone.utc).isoformat()

        conv_ref = self.conversations.document(conversation_id)
        snap = conv_ref.get()
        created = not snap.exists

        if created:
            conversation = {
                'id': conversation_id,
                'participants': [sender_id, receiver_id],
                'participant_names': {
                    sender_id: sender_profile['name'],
                    receiver_id: receiver_profile['name'],
                },
                'participant_photos': {
                    sender_id: sender_profile['photo_url'],
                    receiver_id: receiver_profile['photo_url'],
                },
                'last_message': '',
                'last_sender_id': '',
                'last_message_at': now,
                'unread_counts': {sender_id: 0, receiver_id: 0},
                'status': 'active',
                'created_at': now,
                'updated_at': now,
            }
            conv_ref.set(conversation)
        else:
            conversation = snap.to_dict() or {}
            conversation['id'] = conversation.get('id') or conversation_id
            participants = conversation.get('participants') or []
            if sender_id not in participants:
                raise PermissionError('Forbidden conversation')
            # Conversation exists but may have been merged — follow the link
            if conversation.get('status') == 'merged' and conversation.get('merged_into'):
                conversation_id = str(conversation['merged_into'])
                conversation = self.require_conversation(conversation_id, {'uid': sender_id})

        # Reel context goes on the message only — not on the conversation document
        context_type = 'reel' if (payload.reel_id or '').strip() else 'direct'
        self.add_message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            sender_name=sender_profile['name'],
            text=payload.text,
            context_type=context_type,
            context_id=str(payload.reel_id or ''),
            context_title=str(payload.reel_title or ''),
            context_thumbnail_url=str(payload.reel_thumbnail_url or ''),
        )

        return self.get_conversation(conversation_id, current_user={'uid': sender_id}) or conversation

    def start_marketplace_conversation(
        self,
        listing_id: str,
        initial_message: str,
        current_user: dict,
    ) -> dict:
        """Start or resume the canonical pair conversation from a marketplace listing.

        The listing context is stored on the initial message only. If the pair
        already has a canonical conversation, we reuse it and add the new message
        (with the listing context embedded) rather than creating a duplicate thread.
        """
        buyer_id = str(current_user.get('uid') or '').strip()
        listing_id = str(listing_id or '').strip()
        if not buyer_id or not listing_id:
            raise ValueError('Invalid marketplace conversation')

        listing_snap = self.marketplace_items.document(listing_id).get()
        if not listing_snap.exists:
            raise LookupError('Marketplace listing not found')
        listing = listing_snap.to_dict() or {}
        listing['id'] = listing_id
        if not is_public_marketplace_item(listing):
            raise PermissionError('Marketplace listing is not available')

        seller_id = next(
            (
                str(listing.get(field) or '').strip()
                for field in ('sellerId', 'userId', 'ownerId', 'creatorId')
                if str(listing.get(field) or '').strip()
            ),
            '',
        )
        if not seller_id:
            raise ValueError('Marketplace listing has no seller')
        if seller_id == buyer_id:
            raise PermissionError('You cannot contact yourself')

        buyer_profile = self._get_user_snapshot(buyer_id, fallback=current_user)
        seller_profile = self._get_user_snapshot(
            seller_id,
            fallback={
                'name': listing.get('sellerName') or '',
                'picture': listing.get('sellerAvatarUrl') or '',
            },
        )

        # Listing snapshot for the message context card
        images = listing.get('images') or []
        listing_image = (
            listing.get('coverImage')
            or listing.get('image')
            or (images[0] if isinstance(images, list) and images else '')
            or ''
        )
        listing_price = self._safe_float(listing.get('price'))
        listing_currency = str(
            listing.get('currencyCode') or listing.get('currency') or ''
        ).upper()
        listing_title = str(listing.get('title') or '')

        conversation_id = self._conversation_id(buyer_id, seller_id)
        now = datetime.now(timezone.utc).isoformat()
        conv_ref = self.conversations.document(conversation_id)
        snap = conv_ref.get()
        created = not snap.exists

        if created:
            # New canonical conversation: store the first listing context on the
            # conversation doc so offer button and listing header still work for
            # existing Flutter clients.
            conversation = {
                'id': conversation_id,
                'participants': [buyer_id, seller_id],
                'participant_names': {
                    buyer_id: buyer_profile['name'],
                    seller_id: seller_profile['name'],
                },
                'participant_photos': {
                    buyer_id: buyer_profile['photo_url'],
                    seller_id: seller_profile['photo_url'],
                },
                'last_message': '',
                'last_sender_id': '',
                'last_message_at': now,
                'unread_counts': {buyer_id: 0, seller_id: 0},
                'listing_id': listing_id,
                'listing_title': listing_title,
                'listing_image': str(listing_image),
                'listing_price': listing_price,
                'listing_currency': listing_currency,
                'listing_city': str(listing.get('city') or ''),
                'seller_id': seller_id,
                'buyer_id': buyer_id,
                'status': 'active',
                'created_at': now,
                'updated_at': now,
            }
            conv_ref.set(conversation)
        else:
            conversation = snap.to_dict() or {}
            conversation['id'] = conversation.get('id') or conversation_id
            participants = conversation.get('participants') or []
            if buyer_id not in participants:
                raise PermissionError('Forbidden conversation')
            # Follow merge link if conversation was migrated
            if conversation.get('status') == 'merged' and conversation.get('merged_into'):
                conversation_id = str(conversation['merged_into'])
                conversation = self.require_conversation(conversation_id, {'uid': buyer_id})

        clean_initial = str(initial_message or '').strip()
        if clean_initial:
            # Every initiation from a listing embeds listing context in the message
            self.add_message(
                conversation_id=conversation_id,
                sender_id=buyer_id,
                sender_name=buyer_profile['name'],
                text=clean_initial,
                context_type='marketplace_listing',
                context_id=listing_id,
                context_title=listing_title,
                context_thumbnail_url=str(listing_image),
                context_price=listing_price,
                context_currency=listing_currency,
            )

        return self.require_conversation(conversation_id, {'uid': buyer_id})

    # ------------------------------------------------------------------
    # Message creation
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        context_type: str = '',
        context_id: str = '',
        context_title: str = '',
        context_thumbnail_url: str = '',
        context_price: Optional[float] = None,
        context_currency: str = '',
        # Legacy reel fields accepted for backward compat — mapped to context
        reel_id: str = '',
        reel_title: str = '',
        reel_thumbnail_url: str = '',
    ) -> Optional[dict]:
        text = str(text or '').strip()
        if not text or len(text) > 1000:
            raise ValueError('Message must contain between 1 and 1000 characters')
        conversation = self.get_conversation(conversation_id, current_user={'uid': sender_id})
        if not conversation:
            return None

        participants = conversation.get('participants') or []
        if sender_id not in participants:
            return None
        if conversation.get('status') not in ('', 'active'):
            raise PermissionError('Conversation is not active')

        # Merge legacy reel fields into context if no explicit context supplied
        resolved_type = str(context_type or '').strip()
        resolved_id = str(context_id or '').strip()
        resolved_title = str(context_title or '').strip()
        resolved_thumbnail = str(context_thumbnail_url or '').strip()
        resolved_price = context_price
        resolved_currency = str(context_currency or '').strip()

        legacy_reel = str(reel_id or '').strip()
        if not resolved_type and legacy_reel:
            resolved_type = 'reel'
            resolved_id = legacy_reel
            resolved_title = str(reel_title or '').strip()
            resolved_thumbnail = str(reel_thumbnail_url or '').strip()

        now = datetime.now(timezone.utc).isoformat()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'sender_name': sender_name or 'User',
            'text': text,
            'type': 'text',
            # Unified context fields
            'context_type': resolved_type,
            'context_id': resolved_id,
            'context_title': resolved_title,
            'context_thumbnail_url': resolved_thumbnail,
            'context_price': resolved_price,
            'context_currency': resolved_currency,
            # Legacy reel fields kept so old clients continue working
            'reel_id': resolved_id if resolved_type == 'reel' else '',
            'reel_title': resolved_title if resolved_type == 'reel' else '',
            'reel_thumbnail_url': resolved_thumbnail if resolved_type == 'reel' else '',
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

        self._notify_message(
            conversation=conversation,
            sender_id=sender_id,
            sender_name=sender_name,
            is_offer=False,
        )

        return self._normalize_message(message)

    def add_offer(
        self,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        amount: float,
        currency: str,
        text: str = '',
    ) -> Optional[dict]:
        conversation = self.get_conversation(
            conversation_id,
            current_user={'uid': sender_id},
        )
        if not conversation:
            return None
        if not conversation.get('listing_id'):
            raise ValueError('Offers are only available for marketplace conversations')
        if sender_id != conversation.get('buyer_id'):
            raise PermissionError('Only the buyer can make an offer')
        if conversation.get('status') not in ('', 'active'):
            raise PermissionError('Conversation is not active')
        if amount <= 0:
            raise ValueError('Offer amount must be greater than zero')

        offer_currency = (
            str(conversation.get('listing_currency') or '').strip().upper()
            or str(currency or '').strip().upper()
        )
        clean_text = str(text or '').strip()
        if len(clean_text) > 1000:
            raise ValueError('Offer message is too long')
        display_text = clean_text or f'{amount:g} {offer_currency}'.strip()
        return self._add_typed_message(
            conversation=conversation,
            sender_id=sender_id,
            sender_name=sender_name,
            text=display_text,
            message_type='offer',
            offer_amount=float(amount),
            offer_currency=offer_currency,
        )

    def _add_typed_message(
        self,
        conversation: dict,
        sender_id: str,
        sender_name: str,
        text: str,
        message_type: str,
        offer_amount: float | None = None,
        offer_currency: str = '',
    ) -> dict:
        conversation_id = conversation['id']
        participants = conversation.get('participants') or []
        now = datetime.now(timezone.utc).isoformat()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'sender_name': sender_name or 'User',
            'text': text,
            'type': message_type,
            'offer_amount': offer_amount,
            'offer_currency': offer_currency,
            'context_type': '',
            'context_id': '',
            'context_title': '',
            'context_thumbnail_url': '',
            'context_price': None,
            'context_currency': '',
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
                'last_message': text,
                'last_sender_id': sender_id,
                'last_message_at': now,
                'unread_counts': unread,
                'updated_at': now,
            },
            merge=True,
        )

        self._notify_message(
            conversation=conversation,
            sender_id=sender_id,
            sender_name=sender_name,
            is_offer=message_type == 'offer',
        )

        return self._normalize_message(message)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def _notify_message(
        self,
        conversation: dict,
        sender_id: str,
        sender_name: str,
        is_offer: bool,
    ) -> None:
        conversation_id = conversation.get('id', '')
        participants = conversation.get('participants') or []
        receiver_id = next((uid for uid in participants if uid != sender_id), '')
        if not receiver_id:
            logger.info(
                '[16F-D] notify receiver=none conversation=%s status=skipped',
                conversation_id,
            )
            return

        reel_id = str(conversation.get('reel_id') or '')
        listing_id = str(conversation.get('listing_id') or '')
        if reel_id:
            conv_type = 'reel'
        elif listing_id:
            conv_type = 'marketplace'
        else:
            conv_type = 'direct'

        try:
            status = push_notification_service.notify_new_message_sync(
                receiver_id=receiver_id,
                sender_name=sender_name,
                listing_title=str(conversation.get('listing_title') or ''),
                conversation_id=conversation_id,
                is_offer=is_offer,
                conversation_type=conv_type,
            )
        except Exception as exc:
            logger.warning(
                '[16F-D] notify receiver=%s conversation=%s status=failed error=%s',
                receiver_id, conversation_id, type(exc).__name__,
            )
            return

        logger.info(
            '[16F-D] notify receiver=%s type=%s conversation=%s status=%s',
            receiver_id, conv_type, conversation_id, status,
        )

    # ------------------------------------------------------------------
    # Inbox — one canonical row per participant pair
    # ------------------------------------------------------------------

    def get_inbox(self, current_user: dict, limit: int = 30) -> list[dict]:
        user_id = current_user['uid']
        limit = max(1, min(limit, 50))

        query = self.conversations.where('participants', 'array_contains', user_id)
        try:
            docs = list(query.order_by('last_message_at', direction='DESCENDING').limit(limit * 4).stream())
        except Exception:
            docs = list(query.limit(limit * 6).stream())

        seen_ids: set[str] = set()
        # canonical_pair_key -> best conversation dict
        pair_best: dict[str, dict] = {}

        for doc in docs:
            data = doc.to_dict() or {}
            conversation_id = data.get('id') or doc.id

            if conversation_id in seen_ids:
                continue
            seen_ids.add(conversation_id)

            participants = data.get('participants') or []
            if len(set(participants)) < 2 or user_id not in participants:
                continue

            # Skip merged (migrated), deleted-for-me, archived-for-me
            if data.get('status') == 'merged':
                continue
            if user_id in (data.get('deletedFor') or []):
                continue
            if user_id in (data.get('archivedFor') or []):
                continue

            data['id'] = conversation_id
            other_id = next((p for p in participants if p != user_id), '')
            if not other_id:
                continue

            # Canonical pair key derived deterministically from sorted UIDs
            pair_key = '_'.join(sorted([user_id, other_id]))
            canonical_id = f'conv_{pair_key}'
            is_canonical = (conversation_id == canonical_id)

            if pair_key not in pair_best:
                pair_best[pair_key] = data
            else:
                existing = pair_best[pair_key]
                existing_canonical = (existing['id'] == canonical_id)
                if is_canonical and not existing_canonical:
                    # Always prefer the canonical conversation over legacy ones
                    pair_best[pair_key] = data
                elif not is_canonical and not existing_canonical:
                    # Both legacy — keep the more recently active
                    if str(data.get('last_message_at') or '') > str(existing.get('last_message_at') or ''):
                        pair_best[pair_key] = data
                # existing is already canonical — keep it

        items = [self._normalize_conversation(v) for v in pair_best.values()]
        items.sort(key=lambda x: str(x.get('last_message_at') or ''), reverse=True)
        return items[:limit]

    # ------------------------------------------------------------------
    # Conversation reads
    # ------------------------------------------------------------------

    def get_conversation(self, conversation_id: str, current_user: dict) -> Optional[dict]:
        user_id = current_user['uid']
        snap = self.conversations.document(conversation_id).get()
        if not snap.exists:
            return None

        data = snap.to_dict() or {}
        data['id'] = data.get('id') or conversation_id

        # Follow merge redirect transparently
        if data.get('status') == 'merged' and data.get('merged_into'):
            canonical_id = str(data['merged_into'])
            canonical_snap = self.conversations.document(canonical_id).get()
            if canonical_snap.exists:
                canonical = canonical_snap.to_dict() or {}
                canonical['id'] = canonical.get('id') or canonical_id
                if user_id not in (canonical.get('participants') or []):
                    return None
                return self._normalize_conversation(canonical)
            return None

        if user_id not in (data.get('participants') or []):
            return None

        return self._normalize_conversation(data)

    def require_conversation(self, conversation_id: str, current_user: dict) -> dict:
        user_id = current_user['uid']
        snap = self.conversations.document(conversation_id).get()
        if not snap.exists:
            raise LookupError('Conversation not found')
        data = snap.to_dict() or {}
        data['id'] = data.get('id') or conversation_id

        # Follow merge redirect so notification deep-links to old IDs still work
        if data.get('status') == 'merged' and data.get('merged_into'):
            canonical_id = str(data['merged_into'])
            canonical_snap = self.conversations.document(canonical_id).get()
            if not canonical_snap.exists:
                raise LookupError('Conversation not found')
            canonical = canonical_snap.to_dict() or {}
            canonical['id'] = canonical.get('id') or canonical_id
            if user_id not in (canonical.get('participants') or []):
                raise PermissionError('Forbidden conversation')
            return self._normalize_conversation(canonical)

        if user_id not in (data.get('participants') or []):
            raise PermissionError('Forbidden conversation')
        return self._normalize_conversation(data)

    def list_messages(self, conversation_id: str, current_user: dict, limit: int = 50) -> list[dict]:
        conversation = self.get_conversation(conversation_id, current_user=current_user)
        if not conversation:
            return []

        # If conversation was merged, redirect messages to canonical
        actual_id = conversation.get('id') or conversation_id

        limit = max(1, min(limit, 100))
        query = self.messages.where('conversation_id', '==', actual_id)
        try:
            docs = list(query.order_by('created_at', direction='DESCENDING').limit(limit).stream())
        except Exception:
            docs = list(query.limit(limit).stream())

        items = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = data.get('id') or doc.id
            items.append(self._normalize_message(data))

        items.sort(key=lambda x: str(x.get('created_at') or ''))
        return items

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def mark_read(self, conversation_id: str, current_user: dict) -> Optional[dict]:
        user_id = current_user['uid']
        conversation = self.get_conversation(conversation_id, current_user=current_user)
        if not conversation:
            return None

        actual_id = conversation.get('id') or conversation_id
        unread = dict(conversation.get('unread_counts') or {})
        unread[user_id] = 0

        self.conversations.document(actual_id).set(
            {'unread_counts': unread, 'updated_at': datetime.now(timezone.utc).isoformat()},
            merge=True,
        )

        conversation['unread_counts'] = unread
        return conversation

    def archive_for_me(self, conversation_id: str, user_id: str) -> None:
        self._check_participant(conversation_id, user_id)
        from google.cloud.firestore_v1 import ArrayUnion
        self.conversations.document(conversation_id).set(
            {'archivedFor': ArrayUnion([user_id]), 'updated_at': datetime.now(timezone.utc).isoformat()},
            merge=True,
        )

    def delete_for_me(self, conversation_id: str, user_id: str) -> None:
        self._check_participant(conversation_id, user_id)
        from google.cloud.firestore_v1 import ArrayUnion
        now = datetime.now(timezone.utc).isoformat()
        self.conversations.document(conversation_id).set(
            {
                'deletedFor': ArrayUnion([user_id]),
                f'deletedAt.{user_id}': now,
                'updated_at': now,
            },
            merge=True,
        )

    def _check_participant(self, conversation_id: str, user_id: str) -> None:
        snap = self.conversations.document(conversation_id).get()
        if not snap.exists:
            raise LookupError('Conversation not found')
        data = snap.to_dict() or {}
        if user_id not in (data.get('participants') or []):
            raise PermissionError('Forbidden conversation')

    # ------------------------------------------------------------------
    # Deterministic canonical pair key — no context suffix
    # ------------------------------------------------------------------

    def _conversation_id(self, sender_id: str, receiver_id: str) -> str:
        """Return the one canonical conversation ID for a user pair.

        Deterministic, order-independent, collision-safe.  All sources
        (listing, reel, profile, direct) resolve to the same document.
        """
        a, b = sorted([sender_id, receiver_id])
        return f'conv_{a}_{b}'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0

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
        data['listing_id'] = str(data.get('listing_id') or '')
        data['listing_title'] = str(data.get('listing_title') or '')
        data['listing_image'] = str(data.get('listing_image') or '')
        data['listing_price'] = float(data.get('listing_price') or 0)
        data['listing_currency'] = str(data.get('listing_currency') or '')
        data['listing_city'] = str(data.get('listing_city') or '')
        data['seller_id'] = str(data.get('seller_id') or '')
        data['buyer_id'] = str(data.get('buyer_id') or '')
        data['status'] = str(data.get('status') or 'active')
        return data

    def _normalize_message(self, data: dict) -> dict:
        data['conversation_id'] = str(data.get('conversation_id') or '')
        data['sender_id'] = str(data.get('sender_id') or '')
        data['sender_name'] = str(data.get('sender_name') or 'User')
        data['text'] = str(data.get('text') or '')
        data['type'] = str(data.get('type') or 'text')
        # Unified context fields
        data['context_type'] = str(data.get('context_type') or '')
        data['context_id'] = str(data.get('context_id') or '')
        data['context_title'] = str(data.get('context_title') or '')
        data['context_thumbnail_url'] = str(data.get('context_thumbnail_url') or '')
        raw_ctx_price = data.get('context_price')
        data['context_price'] = float(raw_ctx_price) if raw_ctx_price is not None else None
        data['context_currency'] = str(data.get('context_currency') or '')
        # Legacy reel fields kept for old clients
        data['reel_id'] = str(data.get('reel_id') or '')
        data['reel_title'] = str(data.get('reel_title') or '')
        data['reel_thumbnail_url'] = str(data.get('reel_thumbnail_url') or '')
        raw_amount = data.get('offer_amount')
        data['offer_amount'] = float(raw_amount) if raw_amount is not None else None
        data['offer_currency'] = str(data.get('offer_currency') or '')
        data['is_read'] = bool(data.get('is_read') or False)
        return data


message_repository = MessageRepository()
