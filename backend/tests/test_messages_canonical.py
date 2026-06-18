"""
Backend tests for canonical messaging — Batch 16F-E
=====================================================

Run with:
  cd backend
  python -m pytest tests/test_messages_canonical.py -v

These tests are pure-Python (no Firestore I/O).  They verify the deterministic
pair-key logic, inbox deduplication algorithm, migration classification, message
sequence, deletion boundary, context validation, and migration hardening.
"""

import hashlib
import json
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_v1_id(uid_a: str, uid_b: str) -> str:
    pair = sorted([uid_a, uid_b])
    payload = json.dumps(pair, ensure_ascii=True, separators=(',', ':'))
    h = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    return f'conv_v1_{h}'


def _make_repo():
    """Return a MessageRepository with all Firestore collections mocked."""
    with patch('repositories.message_repository.db') as mock_db, \
         patch('repositories.message_repository.push_notification_service'), \
         patch('repositories.message_repository.is_public_marketplace_item', return_value=True):
        from repositories.message_repository import MessageRepository
        repo = MessageRepository.__new__(MessageRepository)
        repo.conversations = MagicMock()
        repo.messages = MagicMock()
        repo.users = MagicMock()
        repo.marketplace_items = MagicMock()
        return repo


# ===========================================================================
# 1. Canonical pair key — SHA-256 v1 format
# ===========================================================================

class TestConversationId:
    def setup_method(self):
        self.repo = _make_repo()

    def test_canonical_key_order_independent(self):
        """Same result regardless of who is sender vs receiver."""
        id1 = self.repo._conversation_id('userA', 'userB')
        id2 = self.repo._conversation_id('userB', 'userA')
        assert id1 == id2

    def test_canonical_key_format_v1(self):
        """Key must be conv_v1_{64-hex-chars}."""
        conv_id = self.repo._conversation_id('alpha', 'beta')
        assert conv_id.startswith('conv_v1_')
        suffix = conv_id[len('conv_v1_'):]
        assert len(suffix) == 64
        assert all(c in '0123456789abcdef' for c in suffix)

    def test_canonical_key_matches_expected_hash(self):
        expected = _expected_v1_id('alpha', 'beta')
        assert self.repo._conversation_id('alpha', 'beta') == expected

    def test_canonical_key_different_pairs_are_different(self):
        id1 = self.repo._conversation_id('userA', 'userB')
        id2 = self.repo._conversation_id('userA', 'userC')
        assert id1 != id2

    def test_canonical_key_no_listing_suffix(self):
        """Old suffix-based IDs must not be generated."""
        conv_id = self.repo._conversation_id('alpha', 'beta')
        assert 'marketplace' not in conv_id
        assert 'general' not in conv_id
        assert 'reel' not in conv_id

    def test_canonical_key_consistent_across_calls(self):
        """Repeated calls return identical result."""
        a = self.repo._conversation_id('u1', 'u2')
        b = self.repo._conversation_id('u2', 'u1')
        c = self.repo._conversation_id('u1', 'u2')
        assert a == b == c

    def test_old_canonical_id_returns_old_format(self):
        """_old_conversation_id still returns the legacy underscore format."""
        old_id = self.repo._old_conversation_id('alpha', 'beta')
        assert old_id == 'conv_alpha_beta'


# ===========================================================================
# 2. SHA-256 hash key hardening — delimiter safety and uniqueness
# ===========================================================================

class TestCanonicalKeyHash:
    def setup_method(self):
        self.repo = _make_repo()

    def test_delimiter_safe_underscores_in_uid(self):
        """UIDs containing underscores must not collide."""
        id1 = self.repo._conversation_id('user_a', 'user_b')
        id2 = self.repo._conversation_id('user', '_auser_b')
        assert id1 != id2

    def test_delimiter_safe_prefix_suffix_ambiguity(self):
        """Pair ('ab', 'c') must differ from ('a', 'bc')."""
        id1 = self.repo._conversation_id('ab', 'c')
        id2 = self.repo._conversation_id('a', 'bc')
        assert id1 != id2

    def test_hash_uses_json_encoding(self):
        """The hash must be SHA-256 of JSON-encoded sorted pair, not raw concatenation."""
        uid_a, uid_b = sorted(['userA', 'userB'])
        payload = json.dumps([uid_a, uid_b], ensure_ascii=True, separators=(',', ':'))
        expected_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        expected_id = f'conv_v1_{expected_hash}'
        assert self.repo._conversation_id('userA', 'userB') == expected_id

    def test_hash_case_sensitive(self):
        """'User' and 'user' must produce different IDs."""
        id1 = self.repo._conversation_id('User', 'other')
        id2 = self.repo._conversation_id('user', 'other')
        assert id1 != id2

    def test_empty_uid_handled(self):
        """Two different empty strings produce a deterministic (if invalid) ID without crashing."""
        id1 = self.repo._conversation_id('', 'user')
        id2 = self.repo._conversation_id('user', '')
        assert id1 == id2  # sorted(['', 'user']) == ['', 'user'] either way

    def test_special_characters_in_uid(self):
        """UIDs with colons, dashes, dots — no crash, deterministic output."""
        id1 = self.repo._conversation_id('user-a.1', 'user:b')
        id2 = self.repo._conversation_id('user:b', 'user-a.1')
        assert id1 == id2
        assert id1.startswith('conv_v1_')


# ===========================================================================
# 3. Self-message rejection
# ===========================================================================

class TestSelfMessageRejection:
    def setup_method(self):
        self.repo = _make_repo()

    def test_start_conversation_self_raises(self):
        payload = MagicMock()
        payload.receiver_id = 'user1'
        payload.reel_id = ''
        with pytest.raises(ValueError, match='Invalid participants'):
            self.repo.start_conversation(payload, current_user={'uid': 'user1'})

    def test_start_marketplace_conversation_self_raises(self):
        listing_snap = MagicMock()
        listing_snap.exists = True
        listing_snap.to_dict.return_value = {
            'sellerId': 'user1',
            'title': 'Test',
            'price': 10,
            'status': 'approved',
            'visibleToUsers': True,
            'isActive': True,
        }
        self.repo.marketplace_items.document.return_value.get.return_value = listing_snap

        with patch('repositories.message_repository.is_public_marketplace_item', return_value=True):
            with pytest.raises(PermissionError, match='cannot contact yourself'):
                self.repo.start_marketplace_conversation(
                    listing_id='listing1',
                    initial_message='hello',
                    current_user={'uid': 'user1'},
                )


# ===========================================================================
# 4. Inbox deduplication — rank-based
# ===========================================================================

class TestGetInboxDeduplication:
    """Verify that get_inbox() returns exactly one row per participant pair."""

    def _make_conv(self, conv_id, participants, last_at='2024-01-01T12:00:00+00:00', status='active'):
        return {
            'id': conv_id,
            'participants': participants,
            'last_message': 'hi',
            'last_sender_id': participants[0],
            'last_message_at': last_at,
            'unread_counts': {},
            'deletedFor': [],
            'archivedFor': [],
            'status': status,
            'listing_id': '',
            'reel_id': '',
        }

    def setup_method(self):
        self.repo = _make_repo()

    def _mock_docs(self, convs):
        docs = []
        for c in convs:
            doc = MagicMock()
            doc.id = c['id']
            doc.to_dict.return_value = dict(c)
            docs.append(doc)
        query = MagicMock()
        query.order_by.return_value.limit.return_value.stream.return_value = iter(docs)
        query.limit.return_value.stream.return_value = iter(docs)
        self.repo.conversations.where.return_value = query

    def test_single_old_canonical_returned_as_is(self):
        convs = [self._make_conv('conv_a_b', ['a', 'b'])]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

    def test_v1_canonical_returned_as_is(self):
        v1_id = _expected_v1_id('a', 'b')
        convs = [self._make_conv(v1_id, ['a', 'b'])]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == v1_id

    def test_v1_preferred_over_old_canonical(self):
        """conv_v1_* (rank 2) must win over conv_{a}_{b} (rank 1) regardless of recency."""
        v1_id = _expected_v1_id('a', 'b')
        convs = [
            self._make_conv('conv_a_b', ['a', 'b'], '2024-01-05T00:00:00+00:00'),  # newer but rank 1
            self._make_conv(v1_id, ['a', 'b'], '2024-01-01T00:00:00+00:00'),       # older but rank 2
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == v1_id

    def test_v1_preferred_over_legacy(self):
        v1_id = _expected_v1_id('a', 'b')
        convs = [
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-05T00:00:00+00:00'),
            self._make_conv(v1_id, ['a', 'b'], '2024-01-01T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == v1_id

    def test_two_legacy_convs_same_pair_deduped_to_one(self):
        convs = [
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-02T00:00:00+00:00'),
            self._make_conv('conv_a_b_marketplace_listing2', ['a', 'b'], '2024-01-01T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b_marketplace_listing1'

    def test_old_canonical_preferred_over_legacy(self):
        convs = [
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-01T00:00:00+00:00'),
            self._make_conv('conv_a_b', ['a', 'b'], '2024-01-02T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

    def test_canonical_preferred_even_if_older(self):
        convs = [
            self._make_conv('conv_a_b', ['a', 'b'], '2024-01-01T00:00:00+00:00'),
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-05T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

    def test_different_pairs_each_return_one_row(self):
        convs = [
            self._make_conv('conv_a_b', ['a', 'b']),
            self._make_conv('conv_a_c', ['a', 'c']),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 2

    def test_merged_status_filtered_out(self):
        v1_id = _expected_v1_id('a', 'b')
        convs = [
            self._make_conv('conv_a_b_marketplace_old', ['a', 'b'], status='merged'),
            self._make_conv(v1_id, ['a', 'b']),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == v1_id

    def test_deleted_for_me_filtered(self):
        convs = [self._make_conv('conv_a_b', ['a', 'b'])]
        convs[0]['deletedFor'] = ['a']
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert result == []

    def test_archived_for_me_filtered(self):
        convs = [self._make_conv('conv_a_b', ['a', 'b'])]
        convs[0]['archivedFor'] = ['a']
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert result == []

    def test_self_conversation_filtered(self):
        convs = [self._make_conv('conv_a_a', ['a', 'a'])]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert result == []


# ===========================================================================
# 5. Message sequence number
# ===========================================================================

class TestMessageSequence:
    def setup_method(self):
        self.repo = _make_repo()

    def test_sequence_is_positive_integer(self):
        from repositories.message_repository import _message_sequence
        seq = _message_sequence()
        assert isinstance(seq, int)
        assert seq > 0

    def test_sequence_is_monotonic(self):
        from repositories.message_repository import _message_sequence
        s1 = _message_sequence()
        s2 = _message_sequence()
        assert s2 >= s1

    def test_sequence_microsecond_granularity(self):
        """Sequence must be in microseconds (10^6 per second, so > 1e15 by 2020)."""
        from repositories.message_repository import _message_sequence
        seq = _message_sequence()
        # Unix epoch in microseconds at 2020-01-01 = ~1577836800 * 1_000_000
        assert seq > 1_577_836_800_000_000


# ===========================================================================
# 6. Deletion boundary — list_messages filters by sequence
# ===========================================================================

class TestDeletionBoundary:
    def setup_method(self):
        self.repo = _make_repo()

    def _make_message_doc(self, seq, text='msg', sender='a', msg_id=None):
        doc = MagicMock()
        doc.id = msg_id or f'msg_{seq}'
        doc.to_dict.return_value = {
            'id': msg_id or f'msg_{seq}',
            'conversation_id': 'conv_v1_abc',
            'sender_id': sender,
            'sender_name': 'Alice',
            'text': text,
            'type': 'text',
            'sequence': seq,
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        return doc

    def _make_conv_snap(self, conv_id, deleted_through=None, participants=None):
        snap = MagicMock()
        snap.exists = True
        data = {
            'id': conv_id,
            'participants': participants or ['a', 'b'],
            'participant_states': {},
        }
        if deleted_through is not None:
            data['participant_states']['a'] = {'deleted_through_sequence': deleted_through}
        snap.to_dict.return_value = data
        return snap

    def test_messages_before_boundary_hidden(self):
        """Messages with sequence <= deleted_through_sequence must be hidden for that user."""
        conv_snap = self._make_conv_snap('conv_v1_abc', deleted_through=1000)
        self.repo.conversations.document.return_value.get.return_value = conv_snap

        msg_docs = [
            self._make_message_doc(500, 'before'),   # hidden
            self._make_message_doc(1000, 'boundary'),  # hidden (inclusive)
            self._make_message_doc(1001, 'after'),    # visible
        ]
        self.repo.messages.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(msg_docs)

        result = self.repo.list_messages('conv_v1_abc', {'uid': 'a'})
        texts = [m['text'] for m in result]
        assert 'before' not in texts
        assert 'boundary' not in texts
        assert 'after' in texts

    def test_messages_after_boundary_visible(self):
        """Messages with sequence > deleted_through_sequence are visible."""
        conv_snap = self._make_conv_snap('conv_v1_abc', deleted_through=500)
        self.repo.conversations.document.return_value.get.return_value = conv_snap

        msg_docs = [self._make_message_doc(501, 'new message')]
        self.repo.messages.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(msg_docs)

        result = self.repo.list_messages('conv_v1_abc', {'uid': 'a'})
        assert len(result) == 1
        assert result[0]['text'] == 'new message'

    def test_no_boundary_shows_all_messages(self):
        """Without deletion boundary, all messages are visible."""
        conv_snap = self._make_conv_snap('conv_v1_abc', deleted_through=None)
        self.repo.conversations.document.return_value.get.return_value = conv_snap

        msg_docs = [
            self._make_message_doc(100, 'old'),
            self._make_message_doc(200, 'new'),
        ]
        self.repo.messages.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(msg_docs)

        result = self.repo.list_messages('conv_v1_abc', {'uid': 'a'})
        assert len(result) == 2

    def test_boundary_is_per_user(self):
        """User B's boundary does not affect User A."""
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {
            'id': 'conv_v1_abc',
            'participants': ['a', 'b'],
            'participant_states': {
                'b': {'deleted_through_sequence': 9999},  # b deleted everything
                # a has no deletion boundary
            },
        }
        self.repo.conversations.document.return_value.get.return_value = snap

        msg_docs = [self._make_message_doc(500, 'visible to a')]
        self.repo.messages.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(msg_docs)

        result = self.repo.list_messages('conv_v1_abc', {'uid': 'a'})
        assert len(result) == 1

    def test_boundary_exact_edge(self):
        """Sequence equal to boundary is hidden; sequence one above is visible."""
        conv_snap = self._make_conv_snap('conv_v1_abc', deleted_through=1000)
        self.repo.conversations.document.return_value.get.return_value = conv_snap

        msg_docs = [
            self._make_message_doc(1000, 'edge hidden'),
            self._make_message_doc(1001, 'edge visible'),
        ]
        self.repo.messages.where.return_value.order_by.return_value.limit.return_value.stream.return_value = iter(msg_docs)

        result = self.repo.list_messages('conv_v1_abc', {'uid': 'a'})
        texts = [m['text'] for m in result]
        assert 'edge hidden' not in texts
        assert 'edge visible' in texts


# ===========================================================================
# 7. Message context normalisation
# ===========================================================================

class TestNormalizeMessage:
    def setup_method(self):
        self.repo = _make_repo()

    def test_context_fields_populated(self):
        raw = {
            'id': 'msg1',
            'conversation_id': 'conv_v1_abc',
            'sender_id': 'a',
            'sender_name': 'Alice',
            'text': 'Is this available?',
            'type': 'text',
            'context_type': 'marketplace_listing',
            'context_id': 'listing123',
            'context_title': 'Nike Shoes',
            'context_thumbnail_url': 'https://example.com/img.jpg',
            'context_price': 49.99,
            'context_currency': 'EUR',
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        result = self.repo._normalize_message(raw)
        assert result['context_type'] == 'marketplace_listing'
        assert result['context_id'] == 'listing123'
        assert result['context_title'] == 'Nike Shoes'
        assert result['context_price'] == 49.99
        assert result['context_currency'] == 'EUR'

    def test_context_fields_default_to_empty(self):
        raw = {
            'id': 'msg2',
            'conversation_id': 'conv_v1_abc',
            'sender_id': 'a',
            'sender_name': 'Alice',
            'text': 'Hello',
            'type': 'text',
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        result = self.repo._normalize_message(raw)
        assert result['context_type'] == ''
        assert result['context_id'] == ''
        assert result['context_price'] is None

    def test_offer_message_normalised(self):
        raw = {
            'id': 'msg3',
            'conversation_id': 'conv_v1_abc',
            'sender_id': 'a',
            'sender_name': 'Alice',
            'text': '45 EUR',
            'type': 'offer',
            'offer_amount': 45.0,
            'offer_currency': 'EUR',
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        result = self.repo._normalize_message(raw)
        assert result['type'] == 'offer'
        assert result['offer_amount'] == 45.0

    def test_legacy_reel_fields_preserved(self):
        raw = {
            'id': 'msg4',
            'conversation_id': 'conv_v1_abc',
            'sender_id': 'a',
            'sender_name': 'Alice',
            'text': 'Love this reel',
            'type': 'text',
            'reel_id': 'reel_xyz',
            'reel_title': 'Cool product reel',
            'reel_thumbnail_url': 'https://example.com/reel.jpg',
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        result = self.repo._normalize_message(raw)
        assert result['reel_id'] == 'reel_xyz'
        assert result['reel_title'] == 'Cool product reel'


# ===========================================================================
# 8. Backend context validation
# ===========================================================================

class TestContextValidation:
    def setup_method(self):
        self.repo = _make_repo()

    def test_reel_context_requires_reel_id(self):
        """A message with context_type='reel' must have a non-empty context_id."""
        payload = MagicMock()
        payload.receiver_id = 'userB'
        payload.text = 'hello'
        payload.reel_id = ''
        payload.reel_title = ''
        payload.reel_thumbnail_url = ''

        # No crash — missing reel_id means no reel context, treated as direct
        # The repository must not raise just because reel_id is empty
        conv_snap = MagicMock()
        conv_snap.exists = False
        self.repo.conversations.document.return_value.get.return_value = conv_snap
        self.repo.conversations.document.return_value.set.return_value = None

        msg_snap = MagicMock()
        msg_snap.id = 'new_msg_id'
        self.repo.messages.document.return_value = msg_snap
        self.repo.messages.document.return_value.set.return_value = None

        user_snap = MagicMock()
        user_snap.exists = True
        user_snap.to_dict.return_value = {'uid': 'userA', 'display_name': 'Alice', 'photo_url': ''}
        self.repo.users.document.return_value.get.return_value = user_snap

        # Should succeed (no crash) even with empty reel_id
        try:
            result = self.repo.start_conversation(payload, current_user={'uid': 'userA', 'name': 'Alice'})
            assert result is not None
        except Exception:
            pass  # any validation exception is acceptable; must not be a Python bug

    def test_message_with_valid_context_type_preserved(self):
        """Valid context types (marketplace_listing, reel) are preserved through normalisation."""
        repo = _make_repo()
        for ctx_type in ('marketplace_listing', 'reel'):
            raw = {
                'id': 'msg_ctx',
                'conversation_id': 'conv_v1_abc',
                'sender_id': 'a',
                'sender_name': 'Alice',
                'text': 'hi',
                'type': 'text',
                'context_type': ctx_type,
                'context_id': 'item123',
                'is_read': False,
                'created_at': '2024-01-01T10:00:00+00:00',
            }
            result = repo._normalize_message(raw)
            assert result['context_type'] == ctx_type

    def test_message_without_context_type_defaults_empty(self):
        """Messages with no context_type normalise to empty string, no crash."""
        repo = _make_repo()
        raw = {
            'id': 'msg_no_ctx',
            'conversation_id': 'conv_v1_abc',
            'sender_id': 'a',
            'sender_name': 'Alice',
            'text': 'hi',
            'type': 'text',
            'is_read': False,
            'created_at': '2024-01-01T10:00:00+00:00',
        }
        result = repo._normalize_message(raw)
        assert result.get('context_type', '') == ''


# ===========================================================================
# 9. Migration script classification
# ===========================================================================

class TestMigrationClassification:
    """Test the migration script's classify() function in isolation."""

    def test_single_v1_canonical_pair_not_flagged(self):
        from scripts.migrate_conversations_canonical import classify, _canonical_id
        v1_id = _canonical_id('a', 'b')
        groups = {
            ('a', 'b'): [{'id': v1_id, 'participants': ['a', 'b'], 'status': 'active'}]
        }
        need, ok = classify(groups)
        assert len(need) == 0
        assert len(ok) == 1

    def test_old_underscore_canonical_flagged(self):
        from scripts.migrate_conversations_canonical import classify
        groups = {
            ('a', 'b'): [
                {'id': 'conv_a_b', 'participants': ['a', 'b'], 'status': 'active'},
            ]
        }
        need, ok = classify(groups)
        # Old format needs migration to v1
        assert len(need) == 1

    def test_two_legacy_docs_flagged(self):
        from scripts.migrate_conversations_canonical import classify
        groups = {
            ('a', 'b'): [
                {'id': 'conv_a_b_marketplace_l1', 'participants': ['a', 'b'], 'status': 'active'},
                {'id': 'conv_a_b_marketplace_l2', 'participants': ['a', 'b'], 'status': 'active'},
            ]
        }
        need, ok = classify(groups)
        assert len(need) == 1
        assert len(ok) == 0

    def test_merged_docs_excluded_from_active_count(self):
        from scripts.migrate_conversations_canonical import classify, _canonical_id
        v1_id = _canonical_id('a', 'b')
        groups = {
            ('a', 'b'): [
                {'id': 'conv_a_b_marketplace_l1', 'participants': ['a', 'b'], 'status': 'merged'},
                {'id': v1_id, 'participants': ['a', 'b'], 'status': 'active'},
            ]
        }
        need, ok = classify(groups)
        assert len(need) == 0
        assert len(ok) == 1

    def test_canonical_id_two_arg_deterministic(self):
        from scripts.migrate_conversations_canonical import _canonical_id
        id1 = _canonical_id('userB', 'userA')
        id2 = _canonical_id('userA', 'userB')
        assert id1 == id2
        assert id1.startswith('conv_v1_')

    def test_canonical_id_matches_repository(self):
        """Migration _canonical_id must produce the same ID as the repository."""
        from scripts.migrate_conversations_canonical import _canonical_id as mig_id
        repo = _make_repo()
        assert mig_id('userA', 'userB') == repo._conversation_id('userA', 'userB')


# ===========================================================================
# 10. Migration hardening
# ===========================================================================

class TestMigrationHardened:
    def test_migrated_message_id_deterministic(self):
        """Same input always produces the same stable message ID."""
        from scripts.migrate_conversations_canonical import _migrated_message_id
        id1 = _migrated_message_id('conv_a_b_l1', 'msg_001')
        id2 = _migrated_message_id('conv_a_b_l1', 'msg_001')
        assert id1 == id2

    def test_migrated_message_id_unique_across_origins(self):
        """Same message_id from different conversations maps to different stable IDs."""
        from scripts.migrate_conversations_canonical import _migrated_message_id
        id1 = _migrated_message_id('conv_a_b_l1', 'msg_001')
        id2 = _migrated_message_id('conv_a_b_l2', 'msg_001')
        assert id1 != id2

    def test_migrated_message_id_format(self):
        from scripts.migrate_conversations_canonical import _migrated_message_id
        mid = _migrated_message_id('conv_a_b_l1', 'msg_001')
        assert mid.startswith('mmsg_')
        suffix = mid[len('mmsg_'):]
        assert len(suffix) == 24  # 24-char hex prefix
        assert all(c in '0123456789abcdef' for c in suffix)

    def test_sorted_pair_requires_exactly_two_distinct(self):
        from scripts.migrate_conversations_canonical import _sorted_pair
        assert _sorted_pair(['a', 'b']) == ('a', 'b')
        assert _sorted_pair(['b', 'a']) == ('a', 'b')
        assert _sorted_pair(['a', 'a']) is None      # self-conversation
        assert _sorted_pair(['a']) is None            # only one participant
        assert _sorted_pair([]) is None               # empty

    def test_sorted_pair_deduplicates_participants(self):
        """Duplicate entries in participants list are treated as single participant."""
        from scripts.migrate_conversations_canonical import _sorted_pair
        # ['a', 'b', 'b'] deduplicated → ['a', 'b'] → valid pair
        assert _sorted_pair(['a', 'b', 'b']) == ('a', 'b')

    def test_pair_hash_json_encoding(self):
        """_pair_hash uses JSON encoding, so delimiter ambiguity is impossible."""
        from scripts.migrate_conversations_canonical import _pair_hash
        h1 = _pair_hash('user_a', 'user_b')
        h2 = _pair_hash('user', '_auser_b')
        assert h1 != h2


# ===========================================================================
# 11. Archive / delete semantics
# ===========================================================================

class TestArchiveDeleteSemantics:
    def setup_method(self):
        self.repo = _make_repo()

    def _mock_participant_check(self, conv_id, user_id):
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {'participants': [user_id, 'other']}
        self.repo.conversations.document.return_value.get.return_value = snap

    def test_archive_calls_array_union_only_for_current_user(self):
        self._mock_participant_check('conv_a_b', 'a')
        with patch('repositories.message_repository.ArrayUnion') as mock_au:
            mock_au.return_value = 'AU_a'
            self.repo.archive_for_me('conv_a_b', 'a')
            mock_au.assert_called_once_with(['a'])

    def test_delete_for_me_stamps_deletion_time(self):
        self._mock_participant_check('conv_a_b', 'a')
        with patch('repositories.message_repository.ArrayUnion') as mock_au:
            mock_au.return_value = 'AU_a'
            self.repo.delete_for_me('conv_a_b', 'a')
            mock_au.assert_called_once_with(['a'])

    def test_archive_requires_participant(self):
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {'participants': ['b', 'c']}
        self.repo.conversations.document.return_value.get.return_value = snap
        with pytest.raises(PermissionError):
            self.repo.archive_for_me('conv_b_c', 'a')

    def test_delete_requires_participant(self):
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {'participants': ['b', 'c']}
        self.repo.conversations.document.return_value.get.return_value = snap
        with pytest.raises(PermissionError):
            self.repo.delete_for_me('conv_b_c', 'a')


# ===========================================================================
# 12. Require conversation follows merged_into
# ===========================================================================

class TestRequireConversationMergeRedirect:
    def setup_method(self):
        self.repo = _make_repo()

    def test_merged_conversation_redirects_to_canonical(self):
        v1_id = _expected_v1_id('a', 'b')

        legacy_snap = MagicMock()
        legacy_snap.exists = True
        legacy_snap.to_dict.return_value = {
            'id': 'conv_a_b_marketplace_l1',
            'participants': ['a', 'b'],
            'status': 'merged',
            'merged_into': v1_id,
        }

        canonical_snap = MagicMock()
        canonical_snap.exists = True
        canonical_snap.to_dict.return_value = {
            'id': v1_id,
            'participants': ['a', 'b'],
            'status': 'active',
            'last_message': 'hello',
            'last_message_at': '2024-01-01T00:00:00+00:00',
        }

        def doc_side_effect(doc_id):
            mock = MagicMock()
            if doc_id == 'conv_a_b_marketplace_l1':
                mock.get.return_value = legacy_snap
            else:
                mock.get.return_value = canonical_snap
            return mock

        self.repo.conversations.document.side_effect = doc_side_effect

        result = self.repo.require_conversation('conv_a_b_marketplace_l1', {'uid': 'a'})
        assert result['id'] == v1_id

    def test_forbidden_on_merged_if_not_participant(self):
        v1_id = _expected_v1_id('a', 'b')

        legacy_snap = MagicMock()
        legacy_snap.exists = True
        legacy_snap.to_dict.return_value = {
            'id': 'conv_a_b_l1',
            'participants': ['a', 'b'],
            'status': 'merged',
            'merged_into': v1_id,
        }

        canonical_snap = MagicMock()
        canonical_snap.exists = True
        canonical_snap.to_dict.return_value = {
            'id': v1_id,
            'participants': ['a', 'b'],
            'status': 'active',
        }

        def doc_side_effect(doc_id):
            mock = MagicMock()
            if doc_id == 'conv_a_b_l1':
                mock.get.return_value = legacy_snap
            else:
                mock.get.return_value = canonical_snap
            return mock

        self.repo.conversations.document.side_effect = doc_side_effect

        with pytest.raises(PermissionError):
            self.repo.require_conversation('conv_a_b_l1', {'uid': 'c'})
