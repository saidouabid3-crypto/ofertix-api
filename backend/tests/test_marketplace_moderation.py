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


# ════════════════════════════════════════════════════════════════════════════
# Batch 15B-A additions
# ════════════════════════════════════════════════════════════════════════════

# ── Task 1: restore sets approved, not active ─────────────────────────────────

def test_restore_sets_status_approved_not_active(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='hidden')
    result = repo.restore_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert result['status'] == 'approved'
    assert ref.captured['status'] == 'approved'


def test_restore_sets_isactive_true(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='hidden')
    repo.restore_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert ref.captured['isActive'] is True


def test_restore_sets_visible_to_users_true(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='hidden')
    repo.restore_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert ref.captured['visibleToUsers'] is True


def test_restore_clears_rejection_reason(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='rejected')
    repo.restore_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert ref.captured.get('rejectionReason') is None


def test_restored_item_is_public_safe():
    """An item in the state that restore produces passes the public visibility check."""
    restored = {'status': 'approved', 'isActive': True, 'visibleToUsers': True}
    assert is_public_marketplace_item(restored)


# ── Task 2: seller counter sync ───────────────────────────────────────────────

def test_approve_calls_seller_sell_count_sync(monkeypatch):
    """After approve, _sync_seller_sell_count is called with the item's sellerId."""
    synced = []
    ref = _FakeRef(data={'status': 'pending', 'sellerId': 'seller-42'})
    monkeypatch.setattr('repositories.admin_repository.db', _FakeDb(ref))
    repo = AdminRepository()
    monkeypatch.setattr(repo, '_sync_seller_sell_count', lambda uid: synced.append(uid))
    repo.approve_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert synced == ['seller-42']


def test_reject_calls_seller_sell_count_sync(monkeypatch):
    synced = []
    ref = _FakeRef(data={'status': 'approved', 'sellerId': 'seller-42'})
    monkeypatch.setattr('repositories.admin_repository.db', _FakeDb(ref))
    repo = AdminRepository()
    monkeypatch.setattr(repo, '_sync_seller_sell_count', lambda uid: synced.append(uid))
    repo.reject_marketplace_item('item-1', 'admin-uid', 'admin@test.com', 'spam')
    assert synced == ['seller-42']


def test_hide_calls_seller_sell_count_sync(monkeypatch):
    synced = []
    ref = _FakeRef(data={'status': 'approved', 'sellerId': 'seller-42'})
    monkeypatch.setattr('repositories.admin_repository.db', _FakeDb(ref))
    repo = AdminRepository()
    monkeypatch.setattr(repo, '_sync_seller_sell_count', lambda uid: synced.append(uid))
    repo.hide_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert synced == ['seller-42']


def test_sync_seller_sell_count_counts_only_public_items(monkeypatch):
    """_sync_seller_sell_count writes the count of public-safe items to the user doc."""
    written = {}

    class _ItemDoc:
        def __init__(self, data):
            self._data = data
        def to_dict(self):
            return dict(self._data)

    class _ItemQuery:
        def where(self, *a):
            return self
        def limit(self, n):
            return self
        def stream(self):
            return [
                _ItemDoc({'status': 'approved', 'isActive': True}),   # public
                _ItemDoc({'status': 'approved', 'isActive': True}),   # public
                _ItemDoc({'status': 'pending', 'isActive': True}),    # excluded
                _ItemDoc({'status': 'hidden', 'isActive': False}),    # excluded
            ]

    class _UserRef:
        def set(self, data, merge=False):
            written.update(data)

    class _SyncDb:
        def collection(self, name):
            return self
        def where(self, *a):
            return self
        def limit(self, n):
            return self
        def stream(self):
            return [
                _ItemDoc({'status': 'approved', 'isActive': True}),
                _ItemDoc({'status': 'approved', 'isActive': True}),
                _ItemDoc({'status': 'pending', 'isActive': True}),
                _ItemDoc({'status': 'hidden', 'isActive': False}),
            ]
        def document(self, uid=None):
            return _UserRef()

    monkeypatch.setattr('repositories.admin_repository.db', _SyncDb())
    repo = AdminRepository()
    repo._sync_seller_sell_count('seller-1')
    assert written.get('sell_items_count') == 2


def test_sync_seller_sell_count_noop_for_empty_seller(monkeypatch):
    """No DB call if seller_id is empty."""
    calls = []

    class _NoopDb:
        def collection(self, name):
            calls.append(name)
            return self

    monkeypatch.setattr('repositories.admin_repository.db', _NoopDb())
    repo = AdminRepository()
    repo._sync_seller_sell_count('')
    assert calls == []


# ── Task 3: visibleToUsers legacy compatibility ───────────────────────────────

def test_legacy_approved_active_item_without_visible_flag_is_public():
    """Old items with no visibleToUsers field stay public if approved and active."""
    assert is_public_marketplace_item({'status': 'approved', 'isActive': True})


def test_legacy_pending_item_without_visible_flag_is_hidden():
    assert not is_public_marketplace_item({'status': 'pending', 'isActive': True})


def test_legacy_hidden_item_without_visible_flag_is_hidden():
    assert not is_public_marketplace_item({'status': 'hidden', 'isActive': False})


def test_new_create_sets_visible_to_users_false(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item({'title': 'New item'}, current_user={'uid': 'user-1'})
    assert captured.get('visibleToUsers') is False


def test_new_approve_sets_visible_to_users_true(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch)
    repo.approve_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert ref.captured.get('visibleToUsers') is True


def test_reject_sets_visible_to_users_false(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='approved')
    repo.reject_marketplace_item('item-1', 'admin-uid', 'admin@test.com', 'policy')
    assert ref.captured.get('visibleToUsers') is False


def test_hide_sets_visible_to_users_false(monkeypatch):
    repo, ref = _make_admin_repo(monkeypatch, initial_status='approved')
    repo.hide_marketplace_item('item-1', 'admin-uid', 'admin@test.com')
    assert ref.captured.get('visibleToUsers') is False


# ════════════════════════════════════════════════════════════════════════════
# Batch 15C additions — image upload endpoint + image URL safety
# ════════════════════════════════════════════════════════════════════════════

import asyncio

from services.marketplace_service import _assert_safe_image_url, _normalize_and_validate_images


# ── Upload endpoint auth ──────────────────────────────────────────────────────

def test_upload_image_endpoint_requires_auth():
    deps = _route_deps(marketplace_routes.router, '/marketplace/upload-image', 'POST')
    assert require_active_user in deps


# ── Upload endpoint content-type validation ───────────────────────────────────

def test_upload_image_rejects_non_image_content_type():
    from routes.marketplace import upload_marketplace_image

    class _BadFile:
        content_type = 'application/pdf'
        filename = 'cv.pdf'

        async def read(self):
            return b'fake'

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_marketplace_image(_BadFile(), current_user={'uid': 'u1'}))
    assert exc.value.status_code == 400


def test_upload_image_rejects_svg():
    from routes.marketplace import upload_marketplace_image

    class _SvgFile:
        content_type = 'image/svg+xml'
        filename = 'evil.svg'

        async def read(self):
            return b'<svg/>'

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_marketplace_image(_SvgFile(), current_user={'uid': 'u1'}))
    assert exc.value.status_code == 400


# ── Upload endpoint returns 503 when Cloudinary is unavailable ────────────────

def test_upload_image_returns_503_if_cloudinary_unavailable(monkeypatch):
    import routes.marketplace as mp_module
    from routes.marketplace import upload_marketplace_image

    def _fail(_file):
        raise Exception('Cloudinary not configured')

    monkeypatch.setattr(
        mp_module.cloudinary_upload_service,
        'upload_marketplace_image',
        _fail,
    )

    class _ImgFile:
        content_type = 'image/jpeg'
        filename = 'photo.jpg'

        async def read(self):
            return b'\xff\xd8' + b'x' * 100

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_marketplace_image(_ImgFile(), current_user={'uid': 'u1'}))
    assert exc.value.status_code == 503


# ── Image URL safety — unit tests ─────────────────────────────────────────────

@pytest.mark.parametrize('bad_url', [
    'data:image/jpeg;base64,/9j/abc',
    'data:image/png;base64,iVBORw0K',
    'file:///etc/passwd',
    'file://C:/Windows/System32',
    'blob:http://example.com/some-id',
])
def test_assert_safe_image_url_rejects_blocked_schemes(bad_url):
    with pytest.raises(ValueError):
        _assert_safe_image_url(bad_url)


@pytest.mark.parametrize('bad_url', [
    'http://localhost/img.jpg',
    'http://127.0.0.1/img.jpg',
    'https://localhost:8080/img.jpg',
])
def test_assert_safe_image_url_rejects_internal_hosts(bad_url):
    with pytest.raises(ValueError):
        _assert_safe_image_url(bad_url)


@pytest.mark.parametrize('good_url', [
    'https://res.cloudinary.com/ofertix/img.jpg',
    'https://cdn.example.com/photo.webp',
    'http://images.example.com/cover.png',
])
def test_assert_safe_image_url_accepts_safe_urls(good_url):
    _assert_safe_image_url(good_url)   # must not raise


# ── create_item image normalization ───────────────────────────────────────────

def test_marketplace_create_rejects_base64_image(monkeypatch):
    svc, _ = _make_marketplace_service(monkeypatch)
    with pytest.raises(ValueError, match='blocked'):
        svc.create_item(
            {'title': 'Test', 'images': ['data:image/jpeg;base64,/9j/abc']},
            current_user={'uid': 'user-1'},
        )


def test_marketplace_create_rejects_file_path_image(monkeypatch):
    svc, _ = _make_marketplace_service(monkeypatch)
    with pytest.raises(ValueError):
        svc.create_item(
            {'title': 'Test', 'images': ['file:///private/photo.jpg']},
            current_user={'uid': 'user-1'},
        )


def test_marketplace_create_accepts_https_image_and_sets_cover(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item(
        {'title': 'Test', 'images': ['https://cdn.example.com/img.jpg']},
        current_user={'uid': 'user-1'},
    )
    assert captured['images'] == ['https://cdn.example.com/img.jpg']
    assert captured.get('image') == 'https://cdn.example.com/img.jpg'


def test_marketplace_create_cover_is_first_image(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    urls = [
        'https://cdn.example.com/first.jpg',
        'https://cdn.example.com/second.jpg',
    ]
    svc.create_item({'title': 'Test', 'images': urls}, current_user={'uid': 'user-1'})
    assert captured['image'] == urls[0]


def test_marketplace_create_with_images_remains_pending(monkeypatch):
    svc, captured = _make_marketplace_service(monkeypatch)
    svc.create_item(
        {'title': 'Test', 'images': ['https://cdn.example.com/img.jpg']},
        current_user={'uid': 'user-1'},
    )
    assert captured['status'] == 'pending'
    assert captured['isActive'] is False
    assert captured['visibleToUsers'] is False


# ── Normalize gallery field ───────────────────────────────────────────────────

def test_normalize_and_validate_images_accepts_gallery_field():
    payload = {'gallery': ['https://cdn.example.com/a.jpg']}
    _normalize_and_validate_images(payload)
    assert payload['images'] == ['https://cdn.example.com/a.jpg']
    assert payload.get('image') == 'https://cdn.example.com/a.jpg'


# ════════════════════════════════════════════════════════════════════════════
# Batch 15C-C — my-items owner endpoint
# ════════════════════════════════════════════════════════════════════════════

def test_my_items_endpoint_requires_auth():
    deps = _route_deps(marketplace_routes.router, '/marketplace/my-items', 'GET')
    assert require_active_user in deps


def test_my_items_returns_own_items_including_pending(monkeypatch):
    class _FakeDoc:
        def __init__(self, item_id, data):
            self.id = item_id
            self._data = data
        def to_dict(self):
            return dict(self._data)

    class _FakeQuery:
        def where(self, *a):
            return self
        def limit(self, n):
            return self
        def stream(self):
            return [
                _FakeDoc('item-approved', {'sellerId': 'user-1', 'status': 'approved', 'isActive': True}),
                _FakeDoc('item-pending', {'sellerId': 'user-1', 'status': 'pending', 'isActive': False}),
                _FakeDoc('item-rejected', {'sellerId': 'user-1', 'status': 'rejected', 'isActive': False}),
            ]

    class _FakeDb:
        def collection(self, name):
            return _FakeQuery()

    monkeypatch.setattr('repositories.marketplace_repository.db', _FakeDb())
    from repositories.marketplace_repository import MarketplaceRepository
    repo = MarketplaceRepository()
    items = repo.get_user_items('user-1')
    statuses = {i['status'] for i in items}
    assert 'approved' in statuses
    assert 'pending' in statuses
    assert 'rejected' in statuses


def test_my_items_does_not_include_other_users_items(monkeypatch):
    class _FakeDoc:
        def __init__(self, item_id, seller_id):
            self.id = item_id
            self._data = {'sellerId': seller_id, 'status': 'approved'}
        def to_dict(self):
            return dict(self._data)

    class _FakeQuery:
        def __init__(self, seller_filter):
            self._filter = seller_filter
        def where(self, field, op, value):
            return _FakeQuery(value)
        def limit(self, n):
            return self
        def stream(self):
            return [_FakeDoc('own', self._filter)]

    class _FakeColl:
        def where(self, field, op, value):
            return _FakeQuery(value)

    class _FakeDb:
        def collection(self, name):
            return _FakeColl()

    monkeypatch.setattr('repositories.marketplace_repository.db', _FakeDb())
    from repositories.marketplace_repository import MarketplaceRepository
    repo = MarketplaceRepository()
    items = repo.get_user_items('user-1')
    assert all(i['sellerId'] == 'user-1' for i in items)
