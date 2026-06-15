import pytest
from fastapi import HTTPException

from core.auth import require_user


class _Doc:
    def __init__(self, collection, doc_id):
        self._collection = collection
        self.id = doc_id

    @property
    def exists(self):
        return self.id in self._collection.data

    def get(self):
        return self

    def to_dict(self):
        value = self._collection.data.get(self.id)
        return dict(value) if value is not None else None

    def set(self, value, merge=False):
        if merge:
            current = dict(self._collection.data.get(self.id) or {})
            current.update(value)
            self._collection.data[self.id] = current
        else:
            self._collection.data[self.id] = dict(value)


class _Query:
    def __init__(self, collection, docs=None):
        self.collection = collection
        self.docs = docs
        self.max_items = None
        self.order_field = None
        self.descending = False

    def where(self, field, operator, value):
        docs = []
        for doc_id, data in self.collection.data.items():
            field_value = data.get(field)
            if operator == 'array_contains' and value in (field_value or []):
                docs.append((doc_id, data))
            elif operator == '==' and field_value == value:
                docs.append((doc_id, data))
        return _Query(self.collection, docs)

    def order_by(self, field, direction=None):
        self.order_field = field
        self.descending = str(direction).upper().endswith('DESCENDING')
        return self

    def limit(self, value):
        self.max_items = value
        return self

    def stream(self):
        docs = list(self.docs if self.docs is not None else self.collection.data.items())
        if self.order_field:
            docs.sort(
                key=lambda item: str(item[1].get(self.order_field) or ''),
                reverse=self.descending,
            )
        if self.max_items is not None:
            docs = docs[:self.max_items]
        return [_Doc(self.collection, doc_id) for doc_id, _ in docs]


class _Collection(_Query):
    def __init__(self, data=None):
        self.data = data or {}
        super().__init__(self)

    def document(self, doc_id=None):
        doc_id = doc_id or f'auto-{len(self.data) + 1}'
        return _Doc(self, doc_id)


class _Db:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return self.collections.setdefault(name, _Collection())


import core.firebase as firebase_module

firebase_module.db = _Db()

from repositories.message_repository import MessageRepository
from routes import messages as message_routes
from schemas.message_schema import SendMessageRequest, StartMarketplaceConversationRequest
from services.message_service import MessageService


def _public_listing(seller_id='seller-1', status='approved'):
    return {
        'sellerId': seller_id,
        'sellerName': 'Seller',
        'title': 'Phone',
        'price': 250,
        'currencyCode': 'EUR',
        'city': 'Madrid',
        'coverImage': 'https://example.com/phone.jpg',
        'status': status,
        'isActive': status == 'approved',
        'visibleToUsers': status == 'approved',
    }


def _repo(monkeypatch, listing=None):
    fake_db = _Db()
    fake_db.collection('marketplace_items').data['listing-1'] = (
        listing or _public_listing()
    )
    fake_db.collection('users').data.update(
        {
            'buyer-1': {'displayName': 'Buyer'},
            'seller-1': {'displayName': 'Seller'},
            'stranger-1': {'displayName': 'Stranger'},
        }
    )
    monkeypatch.setattr('repositories.message_repository.db', fake_db)
    return MessageRepository(), fake_db


def test_inbox_requires_auth_dependency():
    route = next(
        route
        for route in message_routes.router.routes
        if route.path == '/messages/inbox'
    )
    dependencies = {
        dependency.call
        for dependency in route.dependant.dependencies
    }
    assert require_user in dependencies
    with pytest.raises(HTTPException) as exc:
        require_user(authorization=None)
    assert exc.value.status_code == 401


def test_marketplace_start_is_idempotent(monkeypatch):
    repo, fake_db = _repo(monkeypatch)
    user = {'uid': 'buyer-1', 'name': 'Buyer'}

    first = repo.start_marketplace_conversation('listing-1', '', user)
    second = repo.start_marketplace_conversation('listing-1', '', user)

    assert first['id'] == second['id']
    assert len(fake_db.collection('conversations').data) == 1
    assert len(fake_db.collection('chat_messages').data) == 0


def test_existing_conversation_does_not_duplicate_initial_message(monkeypatch):
    repo, fake_db = _repo(monkeypatch)
    user = {'uid': 'buyer-1', 'name': 'Buyer'}

    repo.start_marketplace_conversation('listing-1', 'Hello', user)
    repo.start_marketplace_conversation('listing-1', 'Hello', user)

    assert len(fake_db.collection('chat_messages').data) == 1


def test_owner_cannot_contact_self(monkeypatch):
    repo, _ = _repo(monkeypatch)
    with pytest.raises(PermissionError, match='contact yourself'):
        repo.start_marketplace_conversation(
            'listing-1',
            '',
            {'uid': 'seller-1', 'name': 'Seller'},
        )


def test_pending_listing_cannot_be_contacted(monkeypatch):
    repo, _ = _repo(monkeypatch, _public_listing(status='pending'))
    with pytest.raises(PermissionError, match='not available'):
        repo.start_marketplace_conversation(
            'listing-1',
            '',
            {'uid': 'buyer-1', 'name': 'Buyer'},
        )


def test_participant_can_read_and_non_participant_cannot(monkeypatch):
    repo, _ = _repo(monkeypatch)
    conversation = repo.start_marketplace_conversation(
        'listing-1',
        'Hello',
        {'uid': 'buyer-1', 'name': 'Buyer'},
    )

    result = repo.require_conversation(conversation['id'], {'uid': 'seller-1'})
    assert result['listing_id'] == 'listing-1'
    with pytest.raises(PermissionError):
        repo.require_conversation(conversation['id'], {'uid': 'stranger-1'})


def test_send_message_updates_last_message(monkeypatch):
    repo, fake_db = _repo(monkeypatch)
    service = MessageService()
    service_repo = repo
    monkeypatch.setattr(
        'services.message_service.message_repository',
        service_repo,
    )
    conversation = repo.start_marketplace_conversation(
        'listing-1',
        '',
        {'uid': 'buyer-1', 'name': 'Buyer'},
    )

    message = service.send_message(
        conversation['id'],
        SendMessageRequest(text='Still available?'),
        {'uid': 'buyer-1', 'name': 'Buyer'},
    )

    stored = fake_db.collection('conversations').data[conversation['id']]
    assert message['text'] == 'Still available?'
    assert stored['last_message'] == 'Still available?'
    assert stored['unread_counts']['seller-1'] == 1


def test_offer_uses_listing_currency(monkeypatch):
    repo, _ = _repo(monkeypatch)
    conversation = repo.start_marketplace_conversation(
        'listing-1',
        '',
        {'uid': 'buyer-1', 'name': 'Buyer'},
    )

    offer = repo.add_offer(
        conversation['id'],
        sender_id='buyer-1',
        sender_name='Buyer',
        amount=200,
        currency='USD',
    )

    assert offer['offer_currency'] == 'EUR'


def test_inbox_is_bounded_and_sorted(monkeypatch):
    repo, fake_db = _repo(monkeypatch)
    conversations = fake_db.collection('conversations').data
    for index in range(8):
        conversations[f'conv-{index}'] = {
            'id': f'conv-{index}',
            'participants': ['buyer-1', 'seller-1'],
            'last_message_at': f'2026-01-{index + 1:02d}T00:00:00',
            'created_at': '2026-01-01T00:00:00',
            'updated_at': '2026-01-01T00:00:00',
        }

    inbox = repo.get_inbox({'uid': 'buyer-1'}, limit=3)

    assert [item['id'] for item in inbox] == ['conv-7', 'conv-6', 'conv-5']
    assert len(inbox) == 3


def test_marketplace_start_schema_allows_no_fake_initial_message():
    payload = StartMarketplaceConversationRequest(listing_id='listing-1')
    assert payload.initial_message == ''
