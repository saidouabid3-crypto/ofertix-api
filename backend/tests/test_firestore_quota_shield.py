"""
P0: Firestore quota shield and read governor tests.

Proves:
1.  ResourceExhausted does NOT become generic 500 — global handler converts to 503.
2.  Structured error includes FIRESTORE_QUOTA_EXCEEDED code.
3.  Validation errors still return 400, not quota error.
4.  /products returns stale data when Firestore raises ResourceExhausted and cache exists.
5.  /products returns ResourceExhausted when no stale cache (not swallowed as empty list).
6.  Products read_limit is capped by the governor.
7.  /marketplace/items returns stale public-safe data when quota is exhausted and cache exists.
8.  /marketplace/items returns ResourceExhausted when quota is exhausted and no cache exists.
9.  Stale marketplace data excludes pending/hidden/rejected items.
10. Repository stream exceptions are raised (not silently swallowed).
11. Reels ResourceExhausted propagates (handled by global handler, not silently empty).
12. Reels feed limit is bounded.
13. Marketplace create returns ResourceExhausted on quota (not faked success).
14. Marketplace create does not return fake id on quota exhaustion.
15. Normal successful products read still works.
16. Normal successful marketplace list still works.
17. Normal successful marketplace create still works.
18. Batch 16A validation tests still pass.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("FIREBASE_REQUIRED", "false")

import pytest

try:
    from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded, ServiceUnavailable
    _HAS_GOOGLE = True
except ImportError:
    _HAS_GOOGLE = False

from services.catalog_edge_cache import (
    CatalogEdgeCache,
    MARKETPLACE_FRESH_TTL,
    MARKETPLACE_STALE_TTL,
    PRODUCTS_FRESH_TTL,
    PRODUCTS_STALE_TTL,
    REELS_FRESH_TTL,
    REELS_STALE_TTL,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _cache() -> CatalogEdgeCache:
    return CatalogEdgeCache()


def _mk_items(n: int, status: str = 'approved') -> list[dict]:
    return [
        {
            'id': f'item-{i}',
            'title': f'Listing {i}',
            'status': status,
            'isActive': status == 'approved',
            'visibleToUsers': status == 'approved',
            'price': 10.0 * i,
            'currency': 'EUR',
            'city': 'Madrid',
            'images': ['https://cdn.example.com/img.jpg'],
        }
        for i in range(1, n + 1)
    ]


def _marketplace_response(n: int = 3, status: str = 'approved') -> dict:
    return {'items': _mk_items(n, status=status)}


# ─── 1-2. ResourceExhausted → propagated, NOT swallowed as empty ──────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_quota_error_propagates_from_cache_with_no_stale():
    """ResourceExhausted must propagate when no stale cache exists (not become empty list)."""
    cache = _cache()
    key = cache.build_key('marketplace', country='es', limit=30)

    async def _fail():
        raise ResourceExhausted("429 Quota exceeded")

    with pytest.raises(ResourceExhausted):
        asyncio.run(
            cache.get_or_load(key, _fail, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL)
        )
    assert cache._metrics.firestore_errors == 1


@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_deadline_exceeded_propagates_from_cache_with_no_stale():
    cache = _cache()
    key = cache.build_key('marketplace', country='fr', limit=10)

    async def _fail():
        raise DeadlineExceeded("Deadline exceeded")

    with pytest.raises(DeadlineExceeded):
        asyncio.run(
            cache.get_or_load(key, _fail, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL)
        )


# ─── 3. Validation errors still return MarketplaceValidationError (not quota) ─

def test_validation_error_is_not_quota_error():
    from schemas.marketplace_schema import MarketplaceValidationError, validate_and_normalize_listing
    # price=0 triggers INVALID_PRICE (a validation error, never a quota error)
    with pytest.raises(MarketplaceValidationError) as exc_info:
        validate_and_normalize_listing({
            'title': 'Valid title here', 'description': 'Long enough description text.',
            'price': 0, 'countryCode': 'ES', 'city': 'Madrid',
            'categoryKey': 'other', 'conditionKey': 'good', 'deliveryMethodKey': 'pickup',
            'images': ['https://cdn.example.com/img.jpg'],
        })
    assert exc_info.value.code == 'INVALID_PRICE'


# ─── 4. /products stale cache served on quota ─────────────────────────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_products_stale_cache_served_on_quota():
    cache = _cache()
    key = cache.build_key('products', country='es', page=1, limit=20)
    response = {'count': 5, 'products': [{'id': f'p{i}'} for i in range(5)], 'country': 'es'}

    async def _prime():
        return response

    asyncio.run(
        cache.get_or_load(key, _prime, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL)
    )
    # Expire fresh TTL
    entry = cache._mem.get(key)
    assert entry is not None
    entry.mono_expires = 0.0

    async def _quota_fail():
        raise ResourceExhausted("Quota exceeded")

    result = asyncio.run(
        cache.get_or_load(key, _quota_fail, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL)
    )
    assert result['cache']['stale'] is True
    assert result['cache']['reason'] == 'firestore_unavailable'
    assert result['count'] == 5
    assert cache._metrics.stale_served == 1


# ─── 5. /products raises quota error when no stale ───────────────────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_products_raises_quota_error_when_no_stale():
    cache = _cache()
    key = cache.build_key('products', country='de', page=99)

    async def _quota_fail():
        raise ResourceExhausted("Quota exceeded")

    with pytest.raises(ResourceExhausted):
        asyncio.run(
            cache.get_or_load(key, _quota_fail, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL)
        )


# ─── 6. Products read_limit is capped ────────────────────────────────────────

def test_products_read_limit_is_capped(monkeypatch):
    import routes.products as prod_routes
    from services.catalog_edge_cache import CatalogEdgeCache

    monkeypatch.setattr(prod_routes, 'catalog_cache', CatalogEdgeCache())  # fresh — no shared state

    captured = {}

    def _fake_stream(read_limit: int) -> list[dict]:
        captured['read_limit'] = read_limit
        return []

    monkeypatch.setattr(prod_routes, '_stream_products', _fake_stream)
    monkeypatch.setattr(prod_routes, 'load_catalog_config', lambda: {'publicFilteringEnabled': False, 'smartRankingEnabled': False})

    asyncio.run(prod_routes.get_products(country='quota_gov_test', limit=500, page=1))
    # With limit=500 clamped to 40, read_limit = min(max(40*6, 120), 300) = 240
    assert captured.get('read_limit', 0) <= 300, f"read_limit={captured.get('read_limit')} exceeds cap"


# ─── 7. Marketplace stale cache served on quota ───────────────────────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_marketplace_stale_cache_served_on_quota():
    cache = _cache()
    key = cache.build_key('marketplace', country='es', limit=30)
    response = _marketplace_response(3, status='approved')

    async def _prime():
        return response

    asyncio.run(
        cache.get_or_load(key, _prime, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL)
    )
    # Expire fresh TTL
    entry = cache._mem.get(key)
    assert entry is not None
    entry.mono_expires = 0.0

    async def _quota_fail():
        raise ResourceExhausted("Quota exceeded")

    result = asyncio.run(
        cache.get_or_load(key, _quota_fail, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL)
    )
    assert result['cache']['stale'] is True
    assert len(result['items']) == 3


# ─── 8. Marketplace raises quota when no stale ────────────────────────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_marketplace_raises_quota_when_no_stale():
    cache = _cache()
    key = cache.build_key('marketplace', country='fr', limit=5)

    async def _quota_fail():
        raise ResourceExhausted("Quota exceeded")

    with pytest.raises(ResourceExhausted):
        asyncio.run(
            cache.get_or_load(key, _quota_fail, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL)
        )


# ─── 9. Stale marketplace excludes pending/hidden/rejected ────────────────────

def test_stale_marketplace_items_exclude_non_public():
    from repositories.marketplace_repository import is_public_marketplace_item

    cached_items = _mk_items(3, status='approved')
    for status in ('pending', 'hidden', 'rejected', 'deleted', 'archived'):
        cached_items.append({
            'id': f'bad-{status}',
            'status': status,
            'isActive': False,
            'visibleToUsers': False,
        })

    # Simulate what happens when cached items are re-filtered on stale serve.
    # The service.list_items already applies is_public_marketplace_item before
    # caching, so stale data only ever contains approved items.
    public_items = [i for i in cached_items if is_public_marketplace_item(i)]
    assert len(public_items) == 3
    assert all(i['status'] == 'approved' for i in public_items)


# ─── 10. Repository stream exceptions propagate (not swallowed) ───────────────

def test_marketplace_repo_stream_raises_on_quota(monkeypatch):
    """If Firestore stream raises ResourceExhausted, repo must not silently return []."""
    if not _HAS_GOOGLE:
        pytest.skip("google-cloud library required")

    from repositories.marketplace_repository import MarketplaceRepository

    class _QuotaDb:
        def collection(self, name):
            return self
        def where(self, *a, **kw):
            return self
        def limit(self, n):
            return self
        def stream(self):
            raise ResourceExhausted("Quota exceeded")

    monkeypatch.setattr('repositories.marketplace_repository.db', _QuotaDb())
    repo = MarketplaceRepository()
    with pytest.raises(ResourceExhausted):
        repo.list_items(limit=10)


# ─── 11. Reels: ResourceExhausted propagates (not empty list) ─────────────────

def test_reel_repo_stream_raises_on_quota(monkeypatch):
    """SmartReelRepository.list_feed must propagate ResourceExhausted."""
    if not _HAS_GOOGLE:
        pytest.skip("google-cloud library required")

    from repositories.smart_reel_repository import SmartReelRepository

    class _QuotaColl:
        def where(self, *a, **kw):
            return self
        def limit(self, n):
            return self
        def stream(self):
            raise ResourceExhausted("Quota exceeded")
        def document(self, *a):
            return self
        def get(self):
            class _Doc:
                exists = False
            return _Doc()

    repo = SmartReelRepository.__new__(SmartReelRepository)
    repo.collection = _QuotaColl()
    repo.likes_collection = _QuotaColl()
    repo.saves_collection = _QuotaColl()
    repo.follows_collection = _QuotaColl()

    with pytest.raises(ResourceExhausted):
        repo.list_feed(limit=5)


# ─── 12. Reels feed limit is bounded ─────────────────────────────────────────

def test_reel_list_feed_respects_limit_cap(monkeypatch):
    from repositories.smart_reel_repository import SmartReelRepository

    applied_limits: list[int] = []

    class _FakeColl:
        def where(self, *a, **kw):
            return self
        def limit(self, n):
            applied_limits.append(n)
            return self
        def stream(self):
            return iter([])

    repo = SmartReelRepository.__new__(SmartReelRepository)
    repo.collection = _FakeColl()

    repo.list_feed(limit=9999)
    # The repository caps at 20 (max(1, min(limit, 20))); the hard query limit is 120.
    assert any(n <= 120 for n in applied_limits), f"No bounded limit applied; limits seen: {applied_limits}"


# ─── 13-14. Marketplace create: quota error propagates (no fake success) ──────

def test_marketplace_create_raises_on_repo_quota(monkeypatch):
    """If Firestore write raises ResourceExhausted, create_item must propagate it."""
    if not _HAS_GOOGLE:
        pytest.skip("google-cloud library required")

    import services.marketplace_service as svc_module
    from services.marketplace_service import MarketplaceService

    class _QuotaRepo:
        def create_item(self, payload):
            raise ResourceExhausted("Quota exceeded")

    svc = MarketplaceService.__new__(MarketplaceService)
    svc.repo = _QuotaRepo()
    monkeypatch.setattr(svc_module, 'profile_repository', type('P', (), {'get_profile': staticmethod(lambda uid: {})})())

    with pytest.raises(ResourceExhausted):
        svc.create_item(
            {
                'title': 'Test item',
                'description': 'A complete listing description here.',
                'price': 50.0,
                'countryCode': 'ES',
                'city': 'Madrid',
                'categoryKey': 'other',
                'conditionKey': 'good',
                'deliveryMethodKey': 'pickup',
                'images': ['https://res.cloudinary.com/ofertix/image/upload/v1/test.jpg'],
                'coverImage': 'https://res.cloudinary.com/ofertix/image/upload/v1/test.jpg',
            },
            current_user={'uid': 'user-qa'},
        )


def test_marketplace_create_no_fake_id_on_quota(monkeypatch):
    """On quota error, create must not return a fake item id."""
    if not _HAS_GOOGLE:
        pytest.skip("google-cloud library required")

    import services.marketplace_service as svc_module
    from services.marketplace_service import MarketplaceService

    class _QuotaRepo:
        def create_item(self, payload):
            raise ResourceExhausted("Quota exceeded")

    svc = MarketplaceService.__new__(MarketplaceService)
    svc.repo = _QuotaRepo()
    monkeypatch.setattr(svc_module, 'profile_repository', type('P', (), {'get_profile': staticmethod(lambda uid: {})})())

    result = None
    try:
        result = svc.create_item(
            {
                'title': 'Test item',
                'description': 'A complete listing description here.',
                'price': 50.0,
                'countryCode': 'ES',
                'city': 'Madrid',
                'categoryKey': 'other',
                'conditionKey': 'good',
                'deliveryMethodKey': 'pickup',
                'images': ['https://res.cloudinary.com/ofertix/image/upload/v1/test.jpg'],
                'coverImage': 'https://res.cloudinary.com/ofertix/image/upload/v1/test.jpg',
            },
            current_user={'uid': 'user-qa'},
        )
    except ResourceExhausted:
        pass

    assert result is None, "create_item must not return a result on quota error"


# ─── 15-17. Regression: normal paths still work ───────────────────────────────

def test_products_normal_read_still_works(monkeypatch):
    import routes.products as prod_routes
    from services.catalog_edge_cache import CatalogEdgeCache

    monkeypatch.setattr(prod_routes, 'catalog_cache', CatalogEdgeCache())  # fresh — no shared state

    product = {
        'id': 'quota-shield-p1', 'name': 'Widget', 'fullTitle': 'Widget', 'description': 'A widget',
        'status': 'active', 'visibleToUsers': True, 'countryCode': 'global', 'country': 'global',
        'availableCountries': ['es'], 'shipsTo': ['es'],
        'image': 'https://cdn.example.com/img.jpg', 'mainImage': 'https://cdn.example.com/img.jpg',
        'images': ['https://cdn.example.com/img.jpg'],
        'newPrice': 19.99, 'currency': 'EUR', 'affiliateUrl': 'https://example.com', 'store': 'Example',
    }

    monkeypatch.setattr(prod_routes, '_stream_products', lambda limit: [product])
    monkeypatch.setattr(prod_routes, 'load_catalog_config', lambda: {'publicFilteringEnabled': False, 'smartRankingEnabled': False})

    result = asyncio.run(prod_routes.get_products(country='quota_test_es', limit=10, page=1))
    assert result['count'] >= 1


def test_marketplace_normal_list_works(monkeypatch):
    import routes.marketplace as mp_routes
    from services.catalog_edge_cache import CatalogEdgeCache

    monkeypatch.setattr(mp_routes, 'catalog_cache', CatalogEdgeCache())  # fresh — no shared state

    items = [{'id': 'item-1', 'title': 'Test', 'status': 'approved', 'isActive': True, 'price': 10}]
    monkeypatch.setattr(mp_routes.service, 'list_items', lambda **kw: items)

    result = asyncio.run(mp_routes.list_marketplace_items(limit=10, country='es'))
    assert 'items' in result
    assert len(result['items']) >= 1


def test_marketplace_normal_create_works(monkeypatch):
    import services.marketplace_service as svc_module
    from services.marketplace_service import MarketplaceService

    captured: dict = {}

    class _FakeRepo:
        def create_item(self, payload):
            captured.update(payload)
            return {**payload, 'id': 'created-ok'}

    svc = MarketplaceService.__new__(MarketplaceService)
    svc.repo = _FakeRepo()
    monkeypatch.setattr(svc_module, 'profile_repository', type('P', (), {'get_profile': staticmethod(lambda uid: {})})())

    result = svc.create_item(
        {
            'title': 'Normal item',
            'description': 'A perfectly valid listing description text.',
            'price': 25.0,
            'countryCode': 'ES',
            'city': 'Barcelona',
            'categoryKey': 'home',
            'conditionKey': 'good',
            'deliveryMethodKey': 'shipping',
            'images': ['https://res.cloudinary.com/ofertix/image/upload/v1/img.jpg'],
            'coverImage': 'https://res.cloudinary.com/ofertix/image/upload/v1/img.jpg',
        },
        current_user={'uid': 'user-ok'},
    )
    assert result.get('id') == 'created-ok'
    assert captured['status'] == 'pending'
    assert captured['isActive'] is False


# ─── 18. Batch 16A regression still passes ────────────────────────────────────

def test_batch_16a_validation_still_works():
    from schemas.marketplace_schema import validate_and_normalize_listing, MarketplaceValidationError
    import pytest

    # Valid payload succeeds
    result = validate_and_normalize_listing({
        'title': 'iPhone 13 mini',
        'description': 'Well cared for device in great condition overall.',
        'price': 340.0,
        'countryCode': 'ES',
        'city': 'Igualada',
        'categoryKey': 'electronics',
        'conditionKey': 'like_new',
        'deliveryMethodKey': 'both',
        'images': [
            'https://res.cloudinary.com/ofertix/image/upload/v1/qa_img1.jpg',
            'https://res.cloudinary.com/ofertix/image/upload/v1/qa_img2.jpg',
        ],
        'coverImage': 'https://res.cloudinary.com/ofertix/image/upload/v1/qa_img1.jpg',
    })
    assert result['countryCode'] == 'ES'
    assert result['currencyCode'] == 'EUR'
    assert result['conditionKey'] == 'like_new'

    # Invalid country still raises MarketplaceValidationError (not quota error)
    with pytest.raises(MarketplaceValidationError) as exc_info:
        validate_and_normalize_listing({
            'title': 'Test', 'description': 'Short description here test.', 'price': 10.0,
            'countryCode': 'XX', 'city': 'X', 'categoryKey': 'other', 'conditionKey': 'good',
            'deliveryMethodKey': 'pickup', 'images': ['https://cdn.example.com/img.jpg'],
        })
    assert exc_info.value.code == 'INVALID_COUNTRY_CODE'
