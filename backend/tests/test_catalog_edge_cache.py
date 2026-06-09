"""
Tests for CatalogEdgeCache and safe_stream read governor.

All tests are fully synchronous-compatible (use asyncio.run) and require
no Firestore connection — every loader/query is monkeypatched.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("FIREBASE_REQUIRED", "false")

import pytest
from services.catalog_edge_cache import (
    CatalogEdgeCache,
    NEGATIVE_CACHE_TTL,
    PRODUCTS_FRESH_TTL,
    PRODUCTS_STALE_TTL,
    safe_stream,
)

try:
    from google.api_core.exceptions import ResourceExhausted, DeadlineExceeded
    _HAS_GOOGLE = True
except ImportError:
    _HAS_GOOGLE = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _cache() -> CatalogEdgeCache:
    return CatalogEdgeCache()


def _response(count: int = 3) -> dict:
    return {
        "count": count,
        "products": [{"id": f"p{i}"} for i in range(count)],
        "country": "es",
    }


async def _loader(response: dict, *, calls: list[int]) -> dict:
    calls.append(1)
    return response


# ─── Test 1: cache miss → loader called once, result stored ──────────────────

def test_cache_miss_calls_loader_once_and_stores_result():
    cache = _cache()
    key = cache.build_key("products", country="es")
    calls: list[int] = []
    response = _response()

    result = asyncio.run(
        cache.get_or_load(
            key,
            lambda: _loader(response, calls=calls),
            fresh_ttl=PRODUCTS_FRESH_TTL,
            stale_ttl=PRODUCTS_STALE_TTL,
        )
    )

    assert len(calls) == 1
    assert result["count"] == 3
    assert result["cache"]["hit"] is False
    assert result["cache"]["stale"] is False
    # Entry is now stored
    assert cache._mem.get(key) is not None


# ─── Test 2: cache hit → loader NOT called ────────────────────────────────────

def test_cache_hit_does_not_call_loader():
    cache = _cache()
    key = cache.build_key("products", country="es")
    calls: list[int] = []
    response = _response()

    loader = lambda: _loader(response, calls=calls)

    # Prime the cache
    asyncio.run(cache.get_or_load(key, loader, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL))
    calls.clear()

    # Second call — must be cache hit
    result = asyncio.run(cache.get_or_load(key, loader, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL))

    assert len(calls) == 0
    assert result["cache"]["hit"] is True
    assert result["cache"]["stale"] is False


# ─── Test 3: Firestore error + stale cache → stale returned ──────────────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_firestore_error_with_stale_cache_returns_stale():
    cache = _cache()
    key = cache.build_key("search", q="shoes", country="es")
    response = _response(5)

    # Prime the cache
    asyncio.run(
        cache.get_or_load(
            key,
            lambda: _loader(response, calls=[]),
            fresh_ttl=PRODUCTS_FRESH_TTL,
            stale_ttl=PRODUCTS_STALE_TTL,
        )
    )

    # Force-expire the fresh TTL so next call would try to reload
    entry = cache._mem.get(key)
    assert entry is not None
    entry.mono_expires = 0.0  # expire fresh

    # Next call: loader raises ResourceExhausted
    async def _failing_loader() -> dict:
        raise ResourceExhausted("Quota exceeded.")

    result = asyncio.run(
        cache.get_or_load(
            key,
            _failing_loader,
            fresh_ttl=PRODUCTS_FRESH_TTL,
            stale_ttl=PRODUCTS_STALE_TTL,
        )
    )

    assert result["cache"]["hit"] is True
    assert result["cache"]["stale"] is True
    assert result["cache"]["reason"] == "firestore_unavailable"
    assert result["count"] == 5
    assert cache._metrics.stale_served == 1
    assert cache._metrics.firestore_errors == 1


# ─── Test 4: Firestore error + NO stale cache → exception propagates ─────────

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_firestore_error_no_stale_cache_raises():
    cache = _cache()
    key = cache.build_key("products", country="fr", page=99)

    async def _failing_loader() -> dict:
        raise ResourceExhausted("Quota exceeded.")

    with pytest.raises(ResourceExhausted):
        asyncio.run(
            cache.get_or_load(
                key,
                _failing_loader,
                fresh_ttl=PRODUCTS_FRESH_TTL,
                stale_ttl=PRODUCTS_STALE_TTL,
            )
        )

    assert cache._metrics.firestore_errors == 1
    assert cache._metrics.stale_served == 0


# ─── Test 5: empty result → short TTL (negative cache) ───────────────────────

def test_empty_result_uses_short_ttl():
    cache = _cache()
    key = cache.build_key("products", country="de", page=1)
    empty_response = {"count": 0, "products": [], "country": "de"}

    asyncio.run(
        cache.get_or_load(
            key,
            lambda: _loader(empty_response, calls=[]),
            fresh_ttl=PRODUCTS_FRESH_TTL,
            stale_ttl=PRODUCTS_STALE_TTL,
        )
    )

    entry = cache._mem.get(key)
    assert entry is not None
    # Fresh TTL should be ≤ NEGATIVE_CACHE_TTL (60 s) + jitter buffer
    remaining_fresh = entry.mono_expires - __import__("time").monotonic()
    assert remaining_fresh <= NEGATIVE_CACHE_TTL * 1.2, (
        f"Empty result cached for too long: {remaining_fresh:.0f}s "
        f"(expected ≤ {NEGATIVE_CACHE_TTL * 1.2:.0f}s)"
    )


# ─── Test 6: single-flight prevents duplicate loader calls ───────────────────

def test_single_flight_prevents_duplicate_loader_calls():
    cache = _cache()
    key = cache.build_key("products", country="us", page=1)
    calls: list[int] = []
    response = _response(10)

    async def _slow_loader() -> dict:
        await asyncio.sleep(0.02)  # simulates Firestore latency
        calls.append(1)
        return response

    async def _run_concurrent() -> list[dict]:
        return list(await asyncio.gather(
            cache.get_or_load(key, _slow_loader, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL),
            cache.get_or_load(key, _slow_loader, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL),
            cache.get_or_load(key, _slow_loader, fresh_ttl=PRODUCTS_FRESH_TTL, stale_ttl=PRODUCTS_STALE_TTL),
        ))

    results = asyncio.run(_run_concurrent())

    assert len(calls) == 1, f"Expected loader called once; called {len(calls)} times"
    assert all(r["count"] == 10 for r in results)


# ─── Test 7: public route does NOT return empty success on ResourceExhausted ──

@pytest.mark.skipif(not _HAS_GOOGLE, reason="google-cloud library required")
def test_public_route_does_not_convert_quota_error_to_empty_success():
    """
    When Firestore is quota-limited and no stale cache exists, the route
    must NOT silently return count=0.  It must propagate the error so the
    API returns an honest 5xx rather than misleading empty data.
    """
    cache = _cache()
    key = cache.build_key("products", country="es", page=1, limit=20)

    async def _quota_error_loader():
        raise ResourceExhausted("429 Quota exceeded.")

    with pytest.raises(ResourceExhausted):
        asyncio.run(
            cache.get_or_load(
                key,
                _quota_error_loader,
                fresh_ttl=PRODUCTS_FRESH_TTL,
                stale_ttl=PRODUCTS_STALE_TTL,
            )
        )


# ─── Test 8: safe_stream requires positive limit ──────────────────────────────

def test_safe_stream_requires_positive_limit():
    class _FakeQuery:
        def limit(self, n):
            return self
        def stream(self):
            return iter([])

    with pytest.raises(ValueError, match="safe_stream requires limit"):
        safe_stream(_FakeQuery(), limit=0, context="test_unbounded")

    with pytest.raises(ValueError, match="safe_stream requires limit"):
        safe_stream(_FakeQuery(), limit=-1, context="test_negative")

    # Positive limit must work without error
    docs = safe_stream(_FakeQuery(), limit=10, context="test_valid")
    assert docs == []


# ─── Test 9: cache key is stable and normalized ───────────────────────────────

def test_build_key_normalization():
    k1 = CatalogEdgeCache.build_key("products", country="ES", page=1)
    k2 = CatalogEdgeCache.build_key("products", country="es", page=1)
    k3 = CatalogEdgeCache.build_key("products", country=" es ", page=1)
    assert k1 == k2 == k3, "Country normalization should make these equal"

    k4 = CatalogEdgeCache.build_key("products", country="es", page=2)
    assert k1 != k4, "Different pages should produce different keys"


# ─── Test 10: cache status and clear ─────────────────────────────────────────

def test_cache_status_and_clear():
    cache = _cache()
    key = cache.build_key("products", country="it")
    asyncio.run(
        cache.get_or_load(
            key,
            lambda: _loader(_response(), calls=[]),
            fresh_ttl=PRODUCTS_FRESH_TTL,
            stale_ttl=PRODUCTS_STALE_TTL,
        )
    )

    status = cache.status()
    assert status["memoryCacheEntries"] == 1
    assert status["cacheMissCount"] == 1

    result = cache.clear()
    assert result["ok"] is True
    assert result["clearedEntries"] == 1
    assert cache.status()["memoryCacheEntries"] == 0
