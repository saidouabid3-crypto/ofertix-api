import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from core.firebase import db
from repositories.marketplace_repository import is_public_marketplace_item
from services.push_notification_service import push_notification_service

try:
    from google.cloud.firestore_v1.transaction import transactional as _fs_transactional
    _HAS_TRANSACTIONAL = True
except ImportError:  # pragma: no cover
    _fs_transactional = None
    _HAS_TRANSACTIONAL = False

try:
    from google.cloud.firestore_v1 import ArrayUnion
except ImportError:  # pragma: no cover
    ArrayUnion = None

logger = logging.getLogger("ofertix.messages")


# ---------------------------------------------------------------------------
# Pair-hash utilities — deterministic, collision-safe, order-independent
# ---------------------------------------------------------------------------

def _compute_pair_hash(uid_a: str, uid_b: str) -> str:
    """SHA-256 of a length-disambiguated sorted-pair JSON.

    Using json.dumps(sorted_pair) produces an unambiguous payload:
    ["user_a","user_b"] is different from ["user","_auser_b"] because JSON
    always quotes both values and the array structure is length-prefixed by
    the JSON encoder. No raw underscore concatenation is used.
    """
    pair = sorted([uid_a, uid_b])
    payload = json.dumps(pair, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _canonical_conv_id(uid_a: str, uid_b: str) -> str:
    """Canonical v1 conversation ID.  Never includes raw UID text in the ID."""
    return f'conv_v1_{_compute_pair_hash(uid_a, uid_b)}'


def _old_canonical_conv_id(uid_a: str, uid_b: str) -> str:
    """Pre-16F-D underscore-based format — used only for backward-compat dedup."""
    a, b = sorted([uid_a, uid_b])
    return f'conv_{a}_{b}'


# ---------------------------------------------------------------------------
# Firestore transaction helper (module-level for correct decorator semantics)
# ---------------------------------------------------------------------------

def _create_or_get_conv_nontransactional(conv_ref, new_data: dict, sender_id: str):
    """Simple read-then-set fallback used when no Firebase connection exists."""
    snap = conv_ref.get()
    if snap.exists:
        d = snap.to_dict() or {}
        if sender_id not in (d.get('participants') or []):
            raise PermissionError('Forbidden conversation')
        return d, False
    conv_ref.set(new_data)
    return new_data, True


if _HAS_TRANSACTIONAL and _fs_transactional is not None:
    @_fs_transactional
    def _txn_create_or_get_conv(transaction, conv_ref, new_data: dict, sender_id: str):
        """Atomically create conversation if absent, or verify and return existing.

        Returns (conversation_dict, was_created).
        """
        snap = conv_ref.get(transaction=transaction)
        if snap.exists:
            d = snap.to_dict() or {}
            if sender_id not in (d.get('participants') or []):
                raise PermissionError('Forbidden conversation')
            return d, False
        transaction.set(conv_ref, new_data)
        return new_data, True
else:  # pragma: no cover
    _txn_create_or_get_conv = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Message sequence
# ---------------------------------------------------------------------------

def _message_sequence() -> int:
    """Microsecond-precision monotonic sequence assigned by the backend.

    Collision probability within the same conversation at identical microseconds
    is negligible in practice.  The value is used as a deletion-visibility
    boundary: messages with sequence > deleted_through_sequence are visible.
    """
    return time.time_ns() // 1_000  # nanoseconds → microseconds


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class MessageRepository:
    CONVERSATIONS = 'conversations'
    MESSAGES = 'chat_messages'
    USERS = 'users'
    MARKETPLACE_ITEMS = 'marketplace_items'

    def __init__(self):
        if db is not None:
            self.conversations = db.collection(self.CONVERSATIONS)
            self.messages = db.collection(self.MESSAGES)
            self.users = db.collection(self.USERS)
            self.marketplace_items = db.collection(self.MARKETPLACE_ITEMS)
        else:
            self.conversations = None
            self.messages = None
            self.users = None
            self.marketplace_items = None

    # ------------------------------------------------------------------
    # Canonical ID helpers (instance wrappers for testability)
    # ------------------------------------------------------------------

    def _conversation_id(self, sender_id: str, receiver_id: str) -> str:
        """Return the canonical v1 conversation ID for a pair."""
        return _canonical_conv_id(sender_id, receiver_id)

    def _old_conversation_id(self, sender_id: str, receiver_id: str) -> str:
        """Return the pre-16F-D underscore-based canonical ID (dedup only)."""
        return _old_canonical_conv_id(sender_id, receiver_id)

    # ------------------------------------------------------------------
    # Conversation creation
    # ------------------------------------------------------------------

    def start_conversation(self, payload, current_user: dict) -> dict:
        """Start or resume the canonical conversation between two users.

        Reel / profile / direct contexts attach to the initial message only.
        The conversation document is a plain person-to-person thread.
        Creation is atomic via Firestore transaction.
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
        pair_hash = _compute_pair_hash(sender_id, receiver_id)
        now = datetime.now(timezone.utc).isoformat()

        new_conversation = {
            'id': conversation_id,
            'participants': sorted([sender_id, receiver_id]),
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
            'pair_hash': pair_hash,
            'pair_key_version': 1,
            'created_at': now,
            'updated_at': now,
            'next_sequence': 0,
        }

        conv_ref = self.conversations.document(conversation_id)
        conv_data, created = self._atomic_create_or_get(conv_ref, new_conversation, sender_id)

        # Follow merge redirect if conversation was migrated
        if conv_data.get('status') == 'merged' and conv_data.get('merged_into'):
            conversation_id = str(conv_data['merged_into'])
            conv_data = self.require_conversation(conversation_id, {'uid': sender_id})

        # Context goes on the message, not the conversation
        context_type = 'reel' if str(payload.reel_id or '').strip() else 'direct'
        self.add_message(
            conversation_id=conversation_id,
            sender_id=sender_id,
            sender_name=sender_profile['name'],
            text=payload.text,
            context_type=context_type if context_type == 'reel' else '',
            context_id=str(payload.reel_id or ''),
            context_title=str(payload.reel_title or ''),
            context_thumbnail_url=str(payload.reel_thumbnail_url or ''),
        )

        return self.get_conversation(conversation_id, current_user={'uid': sender_id}) or conv_data

    def start_marketplace_conversation(
        self,
        listing_id: str,
        initial_message: str,
        current_user: dict,
    ) -> dict:
        """Start or resume the canonical pair conversation from a marketplace listing.

        Listing context is stored on the initial message only — not on the
        conversation document — so subsequent messages are plain person-to-person.
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
        pair_hash = _compute_pair_hash(buyer_id, seller_id)
        now = datetime.now(timezone.utc).isoformat()

        new_conversation = {
            'id': conversation_id,
            'participants': sorted([buyer_id, seller_id]),
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
            # First listing context on conversation doc for legacy Flutter clients
            'listing_id': listing_id,
            'listing_title': listing_title,
            'listing_image': str(listing_image),
            'listing_price': listing_price,
            'listing_currency': listing_currency,
            'listing_city': str(listing.get('city') or ''),
            'seller_id': seller_id,
            'buyer_id': buyer_id,
            'status': 'active',
            'pair_hash': pair_hash,
            'pair_key_version': 1,
            'created_at': now,
            'updated_at': now,
            'next_sequence': 0,
        }

        conv_ref = self.conversations.document(conversation_id)
        conv_data, created = self._atomic_create_or_get(conv_ref, new_conversation, buyer_id)

        # Follow merge redirect if already migrated
        if conv_data.get('status') == 'merged' and conv_data.get('merged_into'):
            conversation_id = str(conv_data['merged_into'])
            conv_data = self.require_conversation(conversation_id, {'uid': buyer_id})

        clean_initial = str(initial_message or '').strip()
        if clean_initial and created:
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

        # Use the canonical ID resolved by get_conversation() (follows merged_into).
        # conversation_id may be a legacy ID that has been migrated; actual_id is the
        # canonical document that messages must be written to.
        actual_id = conversation.get('id') or conversation_id

        participants = conversation.get('participants') or []
        if sender_id not in participants:
            return None
        if conversation.get('status') not in ('', 'active'):
            raise PermissionError('Conversation is not active')

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
        # Monotonic microsecond sequence for deletion-boundary visibility
        sequence = _message_sequence()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': actual_id,
            'sender_id': sender_id,
            'sender_name': sender_name or 'User',
            'text': text,
            'type': 'text',
            'sequence': sequence,
            'context_type': resolved_type,
            'context_id': resolved_id,
            'context_title': resolved_title,
            'context_thumbnail_url': resolved_thumbnail,
            'context_price': resolved_price,
            'context_currency': resolved_currency,
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

        conv_update: dict = {
            'last_message': message['text'],
            'last_sender_id': sender_id,
            'last_message_at': now,
            'unread_counts': unread,
            'updated_at': now,
            'last_sequence': sequence,
        }

        # New incoming message restores archived status for every receiver.
        # Uses the same dotted-path pattern as archive_for_me(); Firebase UIDs
        # are alphanumeric so the path is safe from field-path ambiguity.
        if ArrayUnion is not None:
            try:
                from google.cloud.firestore_v1 import ArrayRemove as _ArrayRemove
                receiver_uids = [uid for uid in participants if uid != sender_id]
                for recv_uid in receiver_uids:
                    conv_update[f'participant_states.{recv_uid}.archived'] = False
                if receiver_uids:
                    conv_update['archivedFor'] = _ArrayRemove(receiver_uids)
            except ImportError:
                pass

        self.conversations.document(actual_id).set(conv_update, merge=True)

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
        sequence = _message_sequence()
        message_id = f'msg_{uuid4().hex[:14]}'
        message = {
            'id': message_id,
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'sender_name': sender_name or 'User',
            'text': text,
            'type': message_type,
            'sequence': sequence,
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
                'last_sequence': sequence,
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
            push_notification_service.notify_new_message_sync(
                receiver_id=receiver_id,
                sender_name=sender_name,
                listing_title=str(conversation.get('listing_title') or ''),
                conversation_id=conversation_id,
                is_offer=is_offer,
                conversation_type=conv_type,
            )
        except Exception as exc:
            logger.warning(
                '[16F-E] notify receiver=%s conversation=%s error=%s',
                receiver_id, conversation_id, type(exc).__name__,
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
        # pair_key → (conversation_dict, canonical_rank)
        # canonical_rank: 2=v1_hash, 1=old_underscore, 0=legacy_per_listing
        pair_best: dict[str, tuple[dict, int]] = {}

        for doc in docs:
            data = doc.to_dict() or {}
            conversation_id = data.get('id') or doc.id

            if conversation_id in seen_ids:
                continue
            seen_ids.add(conversation_id)

            participants = data.get('participants') or []
            if len(set(participants)) < 2 or user_id not in participants:
                continue

            if data.get('status') == 'merged':
                continue

            # Check per-user participant state (new model)
            p_state = (data.get('participant_states') or {}).get(user_id) or {}
            if p_state.get('archived') or p_state.get('deleted_through_sequence') is not None:
                # Only hide if deleted and no newer messages exist
                del_seq = p_state.get('deleted_through_sequence')
                last_seq = int(data.get('last_sequence') or 0)
                if del_seq is not None and last_seq <= del_seq:
                    continue
            # Also check legacy arrays for backward compat
            if user_id in (data.get('deletedFor') or []):
                del_at = (data.get('deletedAt') or {}).get(user_id)
                last_seq = int(data.get('last_sequence') or 0)
                # If we have sequence-based state, trust it; else use legacy
                if not p_state.get('deleted_through_sequence'):
                    continue
            if user_id in (data.get('archivedFor') or []):
                if not p_state.get('deleted_through_sequence'):
                    continue

            data['id'] = conversation_id
            other_id = next((p for p in participants if p != user_id), '')
            if not other_id:
                continue

            pair_key = '_'.join(sorted([user_id, other_id]))
            v1_canonical_id = _canonical_conv_id(user_id, other_id)
            old_canonical_id = _old_canonical_conv_id(user_id, other_id)

            if conversation_id == v1_canonical_id:
                rank = 2
            elif conversation_id == old_canonical_id:
                rank = 1
            else:
                rank = 0

            if pair_key not in pair_best:
                pair_best[pair_key] = (data, rank)
            else:
                existing_data, existing_rank = pair_best[pair_key]
                if rank > existing_rank:
                    pair_best[pair_key] = (data, rank)
                elif rank == existing_rank and rank == 0:
                    # Both legacy — prefer more recently active
                    if str(data.get('last_message_at') or '') > str(existing_data.get('last_message_at') or ''):
                        pair_best[pair_key] = (data, rank)

        items = [self._normalize_conversation(v) for v, _ in pair_best.values()]
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

        actual_id = conversation.get('id') or conversation_id
        user_id = current_user['uid']

        # Resolve deletion boundary for this participant
        p_state = (conversation.get('participant_states') or {}).get(user_id) or {}
        deleted_through = p_state.get('deleted_through_sequence')
        # Fall back to legacy timestamp-based deletion marker if sequence not set
        if deleted_through is None:
            legacy_deleted_at = (conversation.get('deletedAt') or {}).get(user_id)
            if legacy_deleted_at and user_id in (conversation.get('deletedFor') or []):
                # Convert ISO timestamp to microseconds for comparison
                try:
                    dt = datetime.fromisoformat(legacy_deleted_at.replace('Z', '+00:00'))
                    deleted_through = int(dt.timestamp() * 1_000_000)
                except (ValueError, AttributeError):
                    deleted_through = None

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

            # Apply deletion boundary: hide messages at or before the boundary
            if deleted_through is not None:
                msg_sequence = int(data.get('sequence') or 0)
                if msg_sequence > 0 and msg_sequence <= deleted_through:
                    continue
                # For legacy messages without sequence, fall back to timestamp comparison
                elif msg_sequence == 0:
                    try:
                        msg_at = data.get('created_at', '')
                        legacy_at_us = int(
                            datetime.fromisoformat(
                                str(msg_at).replace('Z', '+00:00')
                            ).timestamp() * 1_000_000
                        ) if msg_at else 0
                        if legacy_at_us <= deleted_through:
                            continue
                    except (ValueError, AttributeError):
                        pass

            items.append(self._normalize_message(data))

        items.sort(key=lambda x: (int(x.get('sequence') or 0), str(x.get('created_at') or '')))
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
        last_seq = int(conversation.get('last_sequence') or 0)

        update = {
            'unread_counts': unread,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        if last_seq:
            update[f'participant_states.{user_id}.last_read_sequence'] = last_seq

        self.conversations.document(actual_id).set(update, merge=True)

        conversation['unread_counts'] = unread
        return conversation

    def archive_for_me(self, conversation_id: str, user_id: str) -> None:
        self._check_participant(conversation_id, user_id)
        now = datetime.now(timezone.utc).isoformat()
        self.conversations.document(conversation_id).set(
            {
                f'participant_states.{user_id}.archived': True,
                f'participant_states.{user_id}.archived_at': now,
                f'participant_states.{user_id}.uid': user_id,
                # Keep legacy array for older clients during transition
                'archivedFor': ArrayUnion([user_id]) if ArrayUnion else [user_id],
                'updated_at': now,
            },
            merge=True,
        )

    def delete_for_me(self, conversation_id: str, user_id: str) -> None:
        """Delete this conversation for user_id only.

        Saves deleted_through_sequence = last_sequence so that all existing
        messages become invisible.  New messages from the other participant
        will have higher sequences and will reappear.
        """
        snap = self._check_participant(conversation_id, user_id)
        data = snap.to_dict() or {} if snap else {}
        now = datetime.now(timezone.utc).isoformat()
        # Use last_sequence as the deletion boundary
        deleted_through = int(data.get('last_sequence') or _message_sequence())

        self.conversations.document(conversation_id).set(
            {
                f'participant_states.{user_id}.deleted_through_sequence': deleted_through,
                f'participant_states.{user_id}.deleted_at': now,
                f'participant_states.{user_id}.uid': user_id,
                # Keep legacy array for backward compat
                'deletedFor': ArrayUnion([user_id]) if ArrayUnion else [user_id],
                f'deletedAt.{user_id}': now,
                'updated_at': now,
            },
            merge=True,
        )

    def _check_participant(self, conversation_id: str, user_id: str):
        snap = self.conversations.document(conversation_id).get()
        if not snap.exists:
            raise LookupError('Conversation not found')
        data = snap.to_dict() or {}
        if user_id not in (data.get('participants') or []):
            raise PermissionError('Forbidden conversation')
        return snap

    # ------------------------------------------------------------------
    # Atomic conversation creation helper
    # ------------------------------------------------------------------

    def _atomic_create_or_get(self, conv_ref, new_data: dict, sender_id: str) -> tuple[dict, bool]:
        """Create conversation atomically or return existing.

        Uses Firestore transaction when available to prevent duplicate threads
        under concurrent requests.  Falls back to simple read-then-set when
        the transaction infrastructure is not available (test environments).
        """
        if _txn_create_or_get_conv is not None and db is not None:
            try:
                txn = db.transaction()
                return _txn_create_or_get_conv(txn, conv_ref, new_data, sender_id)
            except Exception as exc:
                if isinstance(exc, (PermissionError, LookupError)):
                    raise
                logger.warning('[16F-E] transaction_fallback reason=%s', type(exc).__name__)
        # Fallback (test environment or transaction failure)
        return _create_or_get_conv_nontransactional(conv_ref, new_data, sender_id)

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
        data['sequence'] = int(data.get('sequence') or 0)
        data['context_type'] = str(data.get('context_type') or '')
        data['context_id'] = str(data.get('context_id') or '')
        data['context_title'] = str(data.get('context_title') or '')
        data['context_thumbnail_url'] = str(data.get('context_thumbnail_url') or '')
        raw_ctx_price = data.get('context_price')
        data['context_price'] = float(raw_ctx_price) if raw_ctx_price is not None else None
        data['context_currency'] = str(data.get('context_currency') or '')
        data['reel_id'] = str(data.get('reel_id') or '')
        data['reel_title'] = str(data.get('reel_title') or '')
        data['reel_thumbnail_url'] = str(data.get('reel_thumbnail_url') or '')
        raw_amount = data.get('offer_amount')
        data['offer_amount'] = float(raw_amount) if raw_amount is not None else None
        data['offer_currency'] = str(data.get('offer_currency') or '')
        data['is_read'] = bool(data.get('is_read') or False)
        return data


message_repository = MessageRepository()
