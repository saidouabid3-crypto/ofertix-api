import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault('FIREBASE_REQUIRED', 'false')

from core.auth import require_active_user, require_admin
from repositories.geo_alert_repository import GeoAlertRepository
from repositories.marketplace_repository import is_public_marketplace_item
from repositories.profile_repository import ProfileRepository
from routes import admin as admin_routes
from routes import geo_alerts as geo_routes
from routes import marketplace as marketplace_routes
from routes import products as product_routes
from schemas.geo_alert_schema import GeoStoreDealCreate
from schemas.profile_schema import PublicProfileOut
from services import profile_service as profile_service_module
from services.public_product_service import sanitize_public_product


def _route_dependency_calls(router, path: str, method: str) -> set:
    for route in router.routes:
        if route.path == path and method.upper() in route.methods:
            return {dependency.call for dependency in route.dependant.dependencies}
    raise AssertionError(f'Route not found: {method} {path}')


def _geo_payload() -> GeoStoreDealCreate:
    return GeoStoreDealCreate(
        product_id='product-1',
        product_title='Public deal',
        store='Test store',
        price=10,
        latitude=40.4,
        longitude=-3.7,
    )


def test_geo_alert_anonymous_post_is_blocked():
    dependencies = _route_dependency_calls(
        geo_routes.router,
        '/geo-alerts/store-deals',
        'POST',
    )
    assert require_active_user in dependencies

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_active_user(authorization=None))
    assert exc.value.status_code == 401


def test_geo_alert_user_submission_cannot_force_active(monkeypatch):
    captured = {}

    def fake_create(payload, current_user, status='pending'):
        captured.update(
            payload=payload,
            current_user=current_user,
            status=status,
        )
        return {
            **payload.model_dump(),
            'id': 'geo-1',
            'status': status,
            'created_at': '2026-06-12T10:00:00',
            'updated_at': '2026-06-12T10:00:00',
        }

    monkeypatch.setattr(
        geo_routes.geo_alert_service,
        'create_store_deal',
        fake_create,
    )

    result = asyncio.run(
        geo_routes.create_store_deal(
            _geo_payload(),
            current_user={'uid': 'user-1'},
        )
    )

    assert result['status'] == 'pending'
    assert captured['status'] == 'pending'
    assert captured['current_user']['uid'] == 'user-1'


def test_geo_alert_admin_active_path_is_protected(monkeypatch):
    dependencies = _route_dependency_calls(
        geo_routes.router,
        '/geo-alerts/admin/store-deals',
        'POST',
    )
    assert require_admin in dependencies

    monkeypatch.setattr(
        geo_routes.geo_alert_service,
        'create_store_deal',
        lambda payload, current_user, status='pending': {
            **payload.model_dump(),
            'id': 'geo-admin-1',
            'status': status,
            'created_at': '2026-06-12T10:00:00',
            'updated_at': '2026-06-12T10:00:00',
        },
    )
    result = asyncio.run(
        geo_routes.create_active_store_deal(
            _geo_payload(),
            current_user={'uid': 'admin-1'},
        )
    )
    assert result['status'] == 'active'


def test_geo_alert_public_read_queries_only_active():
    class FakeQuery:
        def __init__(self):
            self.limit_value = None

        def limit(self, value):
            self.limit_value = value
            return self

        def stream(self):
            return []

    class FakeCollection:
        def __init__(self):
            self.where_args = None
            self.query = FakeQuery()

        def where(self, *args):
            self.where_args = args
            return self.query

    repository = GeoAlertRepository.__new__(GeoAlertRepository)
    repository.collection = FakeCollection()
    assert repository.nearby(40.4, -3.7, [], limit=20) == []
    assert repository.collection.where_args == ('status', '==', 'active')


@pytest.mark.parametrize(
    'status',
    ['pending', 'hidden', 'deleted', 'rejected', 'archived'],
)
def test_marketplace_public_visibility_rejects_hidden_statuses(status):
    assert not is_public_marketplace_item(
        {'status': status, 'isActive': True, 'visibleToUsers': True}
    )


def test_marketplace_public_visibility_accepts_active_visible_item():
    assert is_public_marketplace_item(
        {'status': 'active', 'isActive': True, 'visibleToUsers': True}
    )


def test_marketplace_public_visibility_rejects_banned_seller():
    assert not is_public_marketplace_item(
        {'status': 'approved', 'isActive': True, 'sellerBanned': True}
    )


def test_marketplace_public_by_id_returns_generic_404(monkeypatch):
    monkeypatch.setattr(
        marketplace_routes.service,
        'get_public_item',
        lambda item_id: None,
    )
    with pytest.raises(HTTPException) as exc:
        marketplace_routes.get_marketplace_item('hidden-item')
    assert exc.value.status_code == 404
    assert exc.value.detail == 'Marketplace item not found'


def test_marketplace_public_by_id_returns_active_item(monkeypatch):
    item = {'id': 'active-item', 'status': 'active', 'isActive': True}
    monkeypatch.setattr(
        marketplace_routes.service,
        'get_public_item',
        lambda item_id: item,
    )
    assert marketplace_routes.get_marketplace_item('active-item') == item


def test_admin_marketplace_routes_require_admin():
    dependencies = _route_dependency_calls(
        admin_routes.router,
        '/admin/moderation/marketplace',
        'GET',
    )
    assert require_admin in dependencies


def test_public_profile_get_is_read_only(monkeypatch):
    expected = {'uid': 'user-1', 'display_name': 'User', 'reels_count': 4}
    monkeypatch.setattr(
        profile_service_module.profile_repository,
        'get_profile',
        lambda uid: expected,
    )

    def fail_if_called(uid):
        raise AssertionError('Public profile GET must not synchronize counters')

    monkeypatch.setattr(
        profile_service_module.profile_repository,
        'sync_creator_counters',
        fail_if_called,
    )
    assert profile_service_module.profile_service.get_profile('user-1') == expected


def test_public_profile_projection_removes_private_and_admin_fields():
    repository = ProfileRepository.__new__(ProfileRepository)
    projected = repository._normalize_profile(
        {
            'uid': 'admin-1',
            'display_name': 'Public name',
            'role': 'admin',
            'isAdmin': True,
            'email': 'private@example.com',
            'moderationFlags': ['internal'],
            'sellerVerified': True,
            'reels_count': 3,
        }
    )
    serialized = PublicProfileOut(**projected).model_dump()

    assert serialized['seller_verified'] is True
    assert serialized['reels_count'] == 3
    for field in ('role', 'isAdmin', 'email', 'moderationFlags'):
        assert field not in projected
        assert field not in serialized


def test_creator_sell_items_only_returns_public_safe_items():
    class FakeDoc:
        def __init__(self, item_id, data):
            self.id = item_id
            self._data = data

        def to_dict(self):
            return dict(self._data)

    class FakeQuery:
        def __init__(self, docs):
            self.docs = docs

        def where(self, *args):
            return self

        def limit(self, value):
            return self

        def stream(self):
            return self.docs

    docs = [
        FakeDoc('active', {'status': 'active', 'isActive': True}),
        FakeDoc('approved', {'status': 'approved', 'isActive': True}),
        FakeDoc('pending', {'status': 'pending', 'isActive': True}),
        FakeDoc('hidden', {'status': 'hidden', 'isActive': True}),
        FakeDoc(
            'banned',
            {'status': 'active', 'isActive': True, 'sellerBanned': True},
        ),
    ]
    repository = ProfileRepository.__new__(ProfileRepository)
    repository.marketplace = FakeQuery(docs)

    items = repository.get_sell_items('seller-1')
    assert {item['id'] for item in items} == {'active', 'approved'}


def test_product_detail_missing_or_hidden_returns_generic_404(monkeypatch):
    async def missing(product_id, market):
        return None

    monkeypatch.setattr(product_routes, '_load_public_product', missing)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(product_routes.get_product_detail('hidden-product'))
    assert exc.value.status_code == 404
    assert exc.value.detail == 'Product not found'


def test_product_detail_public_product_keeps_response_shape(monkeypatch):
    async def visible(product_id, market):
        return {'id': product_id, 'name': 'Visible product', 'status': 'active'}

    monkeypatch.setattr(product_routes, '_load_public_product', visible)
    result = asyncio.run(product_routes.get_product_detail('product-1'))
    assert result['ok'] is True
    assert result['product']['id'] == 'product-1'
    assert result['sections'] == {}
    assert result['aiVerdict'] == {}
    assert result['dealDNA'] == {}


def test_public_product_sanitizer_removes_internal_fields():
    product = sanitize_public_product(
        {
            'id': 'product-1',
            'status': 'active',
            'adminIssue': 'internal',
            'moderationNotes': 'private',
        }
    )
    assert product == {'id': 'product-1', 'status': 'active'}


def test_marketplace_create_item_forces_pending_and_inactive(monkeypatch):
    """User-supplied status/isActive must be overridden; items start pending/inactive."""
    from services.marketplace_service import MarketplaceService

    captured = {}

    class FakeRepo:
        def create_item(self, payload):
            captured.update(payload)
            return {**payload, 'id': 'new-item'}

    svc = MarketplaceService.__new__(MarketplaceService)
    svc.repo = FakeRepo()

    monkeypatch.setattr(
        'services.marketplace_service.profile_repository',
        type('P', (), {'get_profile': staticmethod(lambda uid: {})})(),
    )

    payload = {
        'title': 'Test item',
        'price': 50,
        'status': 'active',        # attacker-supplied — must be overridden
        'isActive': True,          # attacker-supplied — must be overridden
        'isFeatured': True,        # must be stripped
        'isSponsored': True,       # must be stripped
        'sellerBanned': False,     # must be stripped
        'adminIssue': 'none',      # must be stripped
    }
    result = svc.create_item(payload, current_user={'uid': 'user-1'})

    assert captured['status'] == 'pending', 'status must be forced to pending'
    assert captured['isActive'] is False, 'isActive must be forced to False'
    assert 'isFeatured' not in captured
    assert 'isSponsored' not in captured
    assert 'sellerBanned' not in captured
    assert 'adminIssue' not in captured
    assert result['id'] == 'new-item'
