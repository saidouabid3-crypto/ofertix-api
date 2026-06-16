import pytest

from repositories.profile_repository import ProfileRepository


class _Increment:
    def __init__(self, amount):
        self.amount = amount


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
            for key, val in value.items():
                if isinstance(val, _Increment):
                    current[key] = (current.get(key) or 0) + val.amount
                else:
                    current[key] = val
            self._collection.data[self.id] = current
        else:
            self._collection.data[self.id] = dict(value)

    def update(self, value):
        self.set(value, merge=True)

    def delete(self):
        self._collection.data.pop(self.id, None)


class _Query:
    def __init__(self, collection, docs=None):
        self.collection = collection
        self.docs = docs
        self.max_items = None

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
        return self

    def limit(self, value):
        self.max_items = value
        return self

    def stream(self):
        docs = list(self.docs if self.docs is not None else self.collection.data.items())
        if self.max_items is not None:
            docs = docs[: self.max_items]
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


# Bootstrap: point core.firebase.db at a fake before the repository modules
# (whose module-level singletons call db.collection(...) at import time) get
# imported for the first time in this test session.
import core.firebase as firebase_module  # noqa: E402

if firebase_module.db is None or not isinstance(firebase_module.db, _Db):
    firebase_module.db = _Db()

import google.cloud.firestore_v1 as firestore_v1  # noqa: E402

firestore_v1.Increment = _Increment

from repositories.message_repository import MessageRepository  # noqa: E402
from repositories.review_repository import ReviewRepository  # noqa: E402


@pytest.fixture
def fake_db(monkeypatch):
    db = _Db()
    monkeypatch.setattr('repositories.message_repository.db', db)
    monkeypatch.setattr('repositories.review_repository.db', db)
    return db


def _start_conversation(db, buyer='buyer-1', seller='seller-1', listing='listing-1'):
    db.collection('marketplace_items').data[listing] = {
        'sellerId': seller,
        'sellerName': 'Seller',
        'title': 'Phone',
        'price': 250,
        'currencyCode': 'EUR',
        'status': 'approved',
        'isActive': True,
        'visibleToUsers': True,
    }
    repo = MessageRepository()
    conversation = repo.start_marketplace_conversation(
        listing, 'Hi, is this available?', {'uid': buyer, 'name': 'Buyer'}
    )
    return repo, conversation


def test_review_requires_real_interaction(fake_db):
    db = fake_db
    db.collection('marketplace_items').data['listing-2'] = {
        'sellerId': 'seller-2',
        'status': 'approved',
        'isActive': True,
        'visibleToUsers': True,
    }
    # Conversation exists but with no messages.
    db.collection('conversations').data['conv_buyer-2_seller-2_marketplace_listing-2'] = {
        'id': 'conv_buyer-2_seller-2_marketplace_listing-2',
        'participants': ['buyer-2', 'seller-2'],
        'listing_id': 'listing-2',
        'buyer_id': 'buyer-2',
        'seller_id': 'seller-2',
        'status': 'active',
    }
    review_repo = ReviewRepository()
    with pytest.raises(PermissionError):
        review_repo.create_review(
            reviewer_id='buyer-2',
            reviewer_name='Buyer',
            reviewee_id='seller-2',
            listing_id='listing-2',
            conversation_id='',
            rating=5,
            comment='',
        )


def test_self_review_blocked(fake_db):
    _, conversation = _start_conversation(fake_db)
    review_repo = ReviewRepository()
    with pytest.raises(PermissionError, match='yourself'):
        review_repo.create_review(
            reviewer_id='buyer-1',
            reviewer_name='Buyer',
            reviewee_id='buyer-1',
            listing_id='listing-1',
            conversation_id=conversation['id'],
            rating=5,
            comment='',
        )


def test_non_participant_cannot_review(fake_db):
    _, conversation = _start_conversation(fake_db)
    review_repo = ReviewRepository()
    with pytest.raises(PermissionError):
        review_repo.create_review(
            reviewer_id='stranger-1',
            reviewer_name='Stranger',
            reviewee_id='seller-1',
            listing_id='listing-1',
            conversation_id=conversation['id'],
            rating=5,
            comment='',
        )


def test_duplicate_review_blocked(fake_db):
    _, conversation = _start_conversation(fake_db)
    review_repo = ReviewRepository()
    review_repo.create_review(
        reviewer_id='buyer-1',
        reviewer_name='Buyer',
        reviewee_id='seller-1',
        listing_id='listing-1',
        conversation_id=conversation['id'],
        rating=4,
        comment='Good seller',
    )
    with pytest.raises(ValueError, match='already reviewed'):
        review_repo.create_review(
            reviewer_id='buyer-1',
            reviewer_name='Buyer',
            reviewee_id='seller-1',
            listing_id='listing-1',
            conversation_id=conversation['id'],
            rating=5,
            comment='',
        )


def test_rating_average_computed_correctly(fake_db):
    db = fake_db
    _, conversation = _start_conversation(db, buyer='buyer-1', seller='seller-1', listing='listing-1')
    _, conversation2 = _start_conversation(db, buyer='buyer-2', seller='seller-1', listing='listing-3')
    review_repo = ReviewRepository()

    review_repo.create_review(
        reviewer_id='buyer-1',
        reviewer_name='Buyer',
        reviewee_id='seller-1',
        listing_id='listing-1',
        conversation_id=conversation['id'],
        rating=4,
        comment='',
    )
    review_repo.create_review(
        reviewer_id='buyer-2',
        reviewer_name='Buyer 2',
        reviewee_id='seller-1',
        listing_id='listing-3',
        conversation_id=conversation2['id'],
        rating=5,
        comment='',
    )

    result = review_repo.list_reviews_for_user('seller-1')
    assert result['count'] == 2
    assert result['average'] == 4.5
    assert len(result['items']) == 2


def test_trust_level_uses_real_signals_only():
    repo = ProfileRepository.__new__(ProfileRepository)
    assert repo._trust_level(
        seller_verified=False, sell_items_count=0, rating_count=0,
        rating_average=0, created_at=None,
    ) == 'new_seller'
    assert repo._trust_level(
        seller_verified=True, sell_items_count=0, rating_count=0,
        rating_average=0, created_at=None,
    ) == 'verified_seller'
    assert repo._trust_level(
        seller_verified=False, sell_items_count=3, rating_count=0,
        rating_average=0, created_at=None,
    ) == 'active_seller'
    assert repo._trust_level(
        seller_verified=False, sell_items_count=3, rating_count=3,
        rating_average=5.0, created_at=None,
    ) == 'highly_rated_seller'
