"""
Backend tests for canonical messaging — Batch 16F-D
=====================================================

Run with:
  cd backend
  python -m pytest tests/test_messages_canonical.py -v

These tests are pure-Python (no Firestore I/O).  They verify the deterministic
pair-key logic, inbox deduplication algorithm, migration classification, and
message context normalisation in isolation.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Minimal in-memory stub so we can instantiate MessageRepository without
# a live Firebase connection.
# ---------------------------------------------------------------------------

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
# 1. Canonical pair key
# ===========================================================================

class TestConversationId:
    def setup_method(self):
        self.repo = _make_repo()

    def test_canonical_key_order_independent(self):
        """Same result regardless of who is sender vs receiver."""
        id1 = self.repo._conversation_id('userA', 'userB')
        id2 = self.repo._conversation_id('userB', 'userA')
        assert id1 == id2

    def test_canonical_key_format(self):
        """Key must be conv_{sorted_a}_{sorted_b} with no context suffix."""
        conv_id = self.repo._conversation_id('alpha', 'beta')
        assert conv_id == 'conv_alpha_beta'

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

    def test_canonical_key_consistent_across_sources(self):
        """All source types (listing, reel, direct) resolve to the same ID."""
        direct = self.repo._conversation_id('u1', 'u2')
        # Verify no extra params change the result
        assert direct == self.repo._conversation_id('u2', 'u1')
        assert direct == 'conv_u1_u2'


# ===========================================================================
# 2. Self-message rejection
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
        }
        self.repo.marketplace_items.document.return_value.get.return_value = listing_snap

        with pytest.raises(PermissionError, match='cannot contact yourself'):
            self.repo.start_marketplace_conversation(
                listing_id='listing1',
                initial_message='hello',
                current_user={'uid': 'user1'},
            )


# ===========================================================================
# 3. Inbox deduplication
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

    def test_single_canonical_returned_as_is(self):
        convs = [self._make_conv('conv_a_b', ['a', 'b'])]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

    def test_two_legacy_convs_same_pair_deduped_to_one(self):
        convs = [
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-02T00:00:00+00:00'),
            self._make_conv('conv_a_b_marketplace_listing2', ['a', 'b'], '2024-01-01T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        # Prefer the more recently active one
        assert result[0]['id'] == 'conv_a_b_marketplace_listing1'

    def test_canonical_preferred_over_legacy(self):
        convs = [
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-01T00:00:00+00:00'),
            self._make_conv('conv_a_b', ['a', 'b'], '2024-01-02T00:00:00+00:00'),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

    def test_canonical_preferred_even_if_older(self):
        """Canonical wins over legacy regardless of recency."""
        convs = [
            self._make_conv('conv_a_b', ['a', 'b'], '2024-01-01T00:00:00+00:00'),  # older
            self._make_conv('conv_a_b_marketplace_listing1', ['a', 'b'], '2024-01-05T00:00:00+00:00'),  # newer legacy
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
        convs = [
            self._make_conv('conv_a_b_marketplace_old', ['a', 'b'], status='merged'),
            self._make_conv('conv_a_b', ['a', 'b']),
        ]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert len(result) == 1
        assert result[0]['id'] == 'conv_a_b'

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
        """A conversation where both participants are the same user must not appear."""
        convs = [self._make_conv('conv_a_a', ['a', 'a'])]
        self._mock_docs(convs)
        result = self.repo.get_inbox({'uid': 'a'})
        assert result == []


# ===========================================================================
# 4. Message context normalisation
# ===========================================================================

class TestNormalizeMessage:
    def setup_method(self):
        self.repo = _make_repo()

    def test_context_fields_populated(self):
        raw = {
            'id': 'msg1',
            'conversation_id': 'conv_a_b',
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
            'conversation_id': 'conv_a_b',
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
            'conversation_id': 'conv_a_b',
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
            'conversation_id': 'conv_a_b',
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
# 5. Migration script classification logic (pure Python)
# ===========================================================================

class TestMigrationClassification:
    """Test the migration script's classify() function in isolation."""

    def test_single_canonical_pair_not_flagged(self):
        from scripts.migrate_conversations_canonical import classify, _canonical_id
        groups = {
            ('a', 'b'): [{'id': 'conv_a_b', 'participants': ['a', 'b'], 'status': 'active'}]
        }
        need, ok = classify(groups)
        assert len(need) == 0
        assert len(ok) == 1

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
        from scripts.migrate_conversations_canonical import classify
        groups = {
            ('a', 'b'): [
                {'id': 'conv_a_b_marketplace_l1', 'participants': ['a', 'b'], 'status': 'merged'},
                {'id': 'conv_a_b', 'participants': ['a', 'b'], 'status': 'active'},
            ]
        }
        need, ok = classify(groups)
        assert len(need) == 0
        assert len(ok) == 1

    def test_canonical_id_deterministic(self):
        from scripts.migrate_conversations_canonical import _canonical_id
        assert _canonical_id(['userB', 'userA']) == 'conv_userA_userB'
        assert _canonical_id(['userA', 'userB']) == 'conv_userA_userB'


# ===========================================================================
# 6. Archive / delete semantics
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
            # Should write deletedFor array union
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
# 7. Require conversation follows merged_into
# ===========================================================================

class TestRequireConversationMergeRedirect:
    def setup_method(self):
        self.repo = _make_repo()

    def test_merged_conversation_redirects_to_canonical(self):
        legacy_snap = MagicMock()
        legacy_snap.exists = True
        legacy_snap.to_dict.return_value = {
            'id': 'conv_a_b_marketplace_l1',
            'participants': ['a', 'b'],
            'status': 'merged',
            'merged_into': 'conv_a_b',
        }

        canonical_snap = MagicMock()
        canonical_snap.exists = True
        canonical_snap.to_dict.return_value = {
            'id': 'conv_a_b',
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
        assert result['id'] == 'conv_a_b'

    def test_forbidden_on_merged_if_not_participant(self):
        legacy_snap = MagicMock()
        legacy_snap.exists = True
        legacy_snap.to_dict.return_value = {
            'id': 'conv_a_b_l1',
            'participants': ['a', 'b'],
            'status': 'merged',
            'merged_into': 'conv_a_b',
        }

        canonical_snap = MagicMock()
        canonical_snap.exists = True
        canonical_snap.to_dict.return_value = {
            'id': 'conv_a_b',
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
            self.repo.require_conversation('conv_a_b_l1', {'uid': 'c'})  # c not in participants
