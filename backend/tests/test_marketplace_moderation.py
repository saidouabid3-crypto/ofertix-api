"""
Batch 15B: Marketplace moderation flow tests.

Covers:
  - User create flow: anonymous blocked, pending forced, bypass fields stripped
  - Repository fail-closed default
  - Admin approve / reject / hide actions
  - Public visibility guards (regression)
  - Seller profile item filtering (regression)
"""
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault('FIREBASE_REQUIRED', 'false')

from core.auth import require_active_user, require_admin
from repositories.admin_repository import AdminRepository
from repositories.marketplace_repository import MarketplaceRepository, is_public_marketplace_item
from repositories.profile_repository import ProfileRepository
from routes import admin as admin_routes
from routes import marketplace as marketplace_routes
from services.marketplace_service import MarketplaceService


# ── helpers ───────────────────────────────────────────────────────────────────

def _route_deps(router, path: str, method: str) -> set:
    for route in router.routes:
        if route.path == path and method.upper() in route.methods:
            return {dep.call for dep in route.dependant.dependencies}
    raise AssertionError(f'Route not found: {method} {path}')


class _FakeDoc:
    def __init__(self, exists=True, data=None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return dict(self._data)


class _FakeRef:
    def __init__(self, data=None):
        self._data = data or {'status': 'pending'}
        self.captured: dict = {}

    def get(self):
        return _FakeDoc(True, self._data)

    def update(self, payload):
        self.captured = payload


class _FakeLogColl:
    def add(self, data):
        pass


class _FakeDb:
    def __init__(self, ref: _FakeRef):
        self._ref = ref

    def collection(self, name):
        if name == 'admin_logs':
            return _FakeLogColl()
        return self

    def document(self, item_id=None):
        return self._ref


def _make_admin_repo(monkeypatch, initial_status='pending'):
    ref = _FakeRef(data={'status': initial_status})
    monkeypatch.setattr('repositories.admin_repository.db', _FakeDb(ref))
    return AdminRepository(), ref


def _make_marketplace_service(monkeypatch):
    import services.marketplace_service as svc_module

    captured: dict = {}

    class FakeRepo:
        def create_item(self, payload):
            captured.update(payload)
            return {**payload, 'id': 'new-item'}

    svc = MarketplaceService.__new__(MarketplaceService)
    svc.repo = FakeRepo()
    monkeypatch.setattr(
        svc_module,
        'profile_repository',
        type('P', (), {'get_profile': staticmethod(lambda uid: {})})(),
    )
    return svc, captured


# ── 1. Anonymous create blocked ───────────────────────────────────────────────

def test_marketplace_anonymous_create_blocked():
    deps = _route_deps(marketplace_routes.router, '/marketplace/items', 'POST')
    assert require_active_user in deps


# ── 2. Authenticated user create returns pending/inactive/hidden ──────────────

def test_marketplace_user_create_returns_pending(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'Test'}, current_user={'uid': 'user-1'})
    assert captured['status'] == 'pending'
    assert captured['isActive'] is False
    assert captured['visibleToUsers'] is False


# ── 3. User cannot force status approved / active ────────────────────────────

@pytest.mark.parametrize('forced_status', ['approved', 'active', 'published'])
def test_marketplace_user_cannot_force_public_status(monkeypatch, forced_status):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'Test', 'status': forced_status}, current_user={'uid': 'user-1'})
    assert captured['status'] == 'pending'


# ── 4. User cannot force isActive true ───────────────────────────────────────

def test_marketplace_user_cannot_force_isactive_true(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'Test', 'isActive': True}, current_user={'uid': 'user-1'})
    assert captured['isActive'] is False


# ── 5. User cannot force visibleToUsers true ─────────────────────────────────

def test_marketplace_user_cannot_force_visible_to_users(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'Test', 'visibleToUsers': True}, current_user={'uid': 'user-1'})
    assert captured['visibleToUsers'] is False


# ── 6. User cannot set trust/admin bypass fields ──────────────────────────────

@pytest.mark.parametrize('field', [
    'isFeatured', 'isSponsored', 'sellerBanned',
    'isSellerBanned', 'sellerBlocked', 'adminIssue',
])
def test_marketplace_user_bypass_fields_stripped(monkeypatch, field):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'Test', field: True}, current_user={'uid': 'user-1'})
    assert field not in captured


# ── 7. Repository create default is fail-closed isActive=False ───────────────

def test_marketplace_repo_create_default_isactive_false(monkeypatch):
    captured_set: dict = {}

    class FakeRef:
        id = 'new-doc-id'

        def set(self, data):
            captured_set.update(data)

    class FakeColl:
        def document(self, doc_id=None):
            return FakeRef()

    class FakeDb:
        def collection(self, name):
            return FakeColl()

    monkeypatch.setattr('repositories.marketplace_repository.db', FakeDb())

    repo = MarketplaceRepository()
    repo.create_item({'title': 'No isActive supplied'})
    assert captured_set.get('isActive') is False


# ── 8. Admin approve route requires admin ────────────────────────────────────

def test_admin_approve_marketplace_route_requires_admin():
    deps = _route_deps(
        admin_routes.router,
        '/admin/moderation/marketplace/{item_id}/approve',
        'POST',
    )
    assert require_admin in deps


# ── 9. Anonymous admin approve blocked ───────────────────────────────────────

def test_admin_anonymous_approve_blocked():
    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_admin(authorization=None))
    assert exc.value.status_code == 401


# ── 10. Admin approve sets status=approved, isActive=True, visibleToUsers=True

def test_admin_approve_sets_approved_and_active(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch)
    result = repo.approve_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert result == {'ok': True, 'id': 'item-1', 'status': 'approved'}
    assert ref.captured['status'] == 'approved'
    assert ref.captured['isActive'] is True
    assert ref.captured['visibleToUsers'] is True


# ── 11. Admin approve sets approvedAt and approvedBy ─────────────────────────

def test_admin_approve_sets_approval_timestamps(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch)
    repo.approve_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert 'approvedAt' in ref.captured
    assert ref.captured.get('approvedBy') == 'admin-uid'


# ── 12. Admin approve clears rejectionReason ─────────────────────────────────

def test_admin_approve_clears_rejection_reason(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='rejected')
    repo.approve_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert 'rejectionReason' in ref.captured
    assert ref.captured['rejectionReason'] is None


# ── 13. Admin reject sets rejected, inactive, saves reason ───────────────────

def test_admin_reject_sets_rejected_and_inactive(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch)
    result = repo.reject_marketplace_item('item-1', 'admin-uid', 'admin@test.com', 'spam')
    assert result['status'] == 'rejected'
    assert ref.captured['status'] == 'rejected'
    assert ref.captured['isActive'] is False
    assert ref.captured['visibleToUsers'] is False
    assert ref.captured.get('rejectedAt') is not None
    assert ref.captured.get('rejectedBy') == 'admin-uid'
    assert ref.captured.get('rejectionReason') == 'spam'


# ── 14. Admin hide removes from public visibility ────────────────────────────

def test_admin_hide_removes_from_public_visibility(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='approved')
    result = repo.hide_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert result['status'] == 'hidden'
    assert ref.captured['isActive'] is False
    assert ref.captured['visibleToUsers'] is False


# ── 15-18. Public list visibility guards (regression) ────────────────────────

@pytest.mark.parametrize('status', ['pending', 'hidden', 'rejected', 'deleted', 'archived'])
def test_public_list_excludes_non_public_status(status):
    assert not is_public_marketplace_item({'status': status, 'isActive': True})


def test_public_list_includes_approved_active():
    assert is_public_marketplace_item({'status': 'approved', 'isActive': True})


def test_public_list_excludes_item_with_visible_to_users_false():
    assert not is_public_marketplace_item(
        {'status': 'approved', 'isActive': True, 'visibleToUsers': False}
    )


# ── 19-20. Public by-ID (regression) ─────────────────────────────────────────

def test_public_by_id_hides_pending_item(monkeypatch):
    monkeypatch.setattr(marketplace_routes.service, 'get_public_item', lambda _: None)
    with pytest.raises(HTTPException) as exc:
        marketplace_routes.get_marketplace_item('pending-item')
    assert exc.value.status_code == 404


def test_public_by_id_returns_approved_item(monkeypatch):
    item = {'id': 'item-1', 'status': 'approved', 'isActive': True}
    monkeypatch.setattr(marketplace_routes.service, 'get_public_item', lambda _: item)
    assert marketplace_routes.get_marketplace_item('item-1') == item


# ── 21-22. Seller profile sell-items (regression) ────────────────────────────

def test_seller_profile_includes_only_approved_active():
    class FakeDoc:
        def __init__(self, item_id, status, active=True):
            self.id = item_id
            self._data = {'status': status, 'isActive': active}

        def to_dict(self):
            return dict(self._data)

    class FakeQuery:
        def where(self, *a):
            return self

        def limit(self, v):
            return self

        def stream(self):
            return [
                FakeDoc('approved', 'approved', True),
                FakeDoc('active', 'active', True),
                FakeDoc('pending', 'pending', True),
                FakeDoc('hidden', 'hidden', True),
                FakeDoc('rejected', 'rejected', True),
            ]

    repo = ProfileRepository.__new__(ProfileRepository)
    repo.marketplace = FakeQuery()
    items = repo.get_sell_items('seller-1')
    ids = {i['id'] for i in items}
    assert 'approved' in ids
    assert 'active' in ids
    assert 'pending' not in ids
    assert 'hidden' not in ids
    assert 'rejected' not in ids


# ── 23-27. Regression: catalog stack untouched ───────────────────────────────

def test_is_public_marketplace_item_approved_without_visible_flag():
    """Items without visibleToUsers set are still public if status and isActive are correct."""
    assert is_public_marketplace_item({'status': 'approved', 'isActive': True})


def test_is_public_marketplace_item_rejects_banned_seller():
    assert not is_public_marketplace_item(
        {'status': 'approved', 'isActive': True, 'sellerBanned': True}
    )
