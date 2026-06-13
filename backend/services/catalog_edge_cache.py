from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger("ofertix.catalog_cache")

# ─── Firestore errors that trigger stale-if-error fallback ───────────────────
try:
    from google.api_core.exceptions import (
        DeadlineExceeded,
        InternalServerError,
        ResourceExhausted,
        ServiceUnavailable,
    )
    _STALE_TRIGGER = (ResourceExhausted, DeadlineExceeded, ServiceUnavailable, InternalServerError)
except ImportError:  # pragma: no cover
    _STALE_TRIGGER = (Exception,)  # type: ignore[assignment]

# ─── TTL policy (seconds) ─────────────────────────────────────────────────────
PRODUCTS_FRESH_TTL    = 600    # 10 min
PRODUCTS_STALE_TTL    = 86400  # 24 h
SEARCH_FRESH_TTL      = 300    # 5 min
SEARCH_STALE_TTL      = 21600  # 6 h
TRENDING_FRESH_TTL    = 900    # 15 min
TRENDING_STALE_TTL    = 86400  # 24 h
HOME_FEED_FRESH_TTL   = 600    # 10 min
HOME_FEED_STALE_TTL   = 86400  # 24 h
MARKETPLACE_FRESH_TTL = 300    # 5 min
MARKETPLACE_STALE_TTL = 21600  # 6 h
REELS_FRESH_TTL       = 120    # 2 min
REELS_STALE_TTL       = 7200   # 2 h
NEGATIVE_CACHE_TTL    = 60     # empty result — very short

_JITTER_FACTOR = 0.15         # ±15 %
_MAX_MEM_ENTRIES = 500


def _apply_jitter(ttl: int) -> int:
    offset = int(ttl * _JITTER_FACTOR * (2 * random.random() - 1))
    return max(30, ttl + offset)


# ─── Memory entry ─────────────────────────────────────────────────────────────

class _Entry:
    __slots__ = ("value", "wall_created", "mono_expires", "mono_stale_until")

    def __init__(self, value: Any, fresh_ttl: int, stale_ttl: int) -> None:
        now = time.monotonic()
        self.value = value
        self.wall_created = time.time()
        self.mono_expires = now + _apply_jitter(fresh_ttl)
        self.mono_stale_until = now + _apply_jitter(stale_ttl)

    @property
    def is_fresh(self) -> bool:
        return time.monotonic() < self.mono_expires

    @property
    def is_usable_stale(self) -> bool:
        return time.monotonic() < self.mono_stale_until


# ─── In-memory layer (always available; Render-safe) ─────────────────────────

class _MemoryLayer:
    def __init__(self) -> None:
        self._store: dict[str, _Entry] = {}
        self._insertion_order: list[str] = []

    def get(self, key: str) -> _Entry | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if not entry.is_usable_stale:
            self._evict(key)
            return None
        return entry

    def set(self, key: str, entry: _Entry) -> None:
        if len(self._store) >= _MAX_MEM_ENTRIES and key not in self._store:
            self._evict_oldest()
        self._store[key] = entry
        if key in self._insertion_order:
            self._insertion_order.remove(key)
        self._insertion_order.append(key)

    def clear(self) -> int:
        count = len(self._store)
        self._store.clear()
        self._insertion_order.clear()
        return count

    def _evict(self, key: str) -> None:
        self._store.pop(key, None)
        try:
            self._insertion_order.remove(key)
        except ValueError:
            pass

    def _evict_oldest(self) -> None:
        while self._insertion_order and len(self._store) >= _MAX_MEM_ENTRIES:
            old = self._insertion_order.pop(0)
            self._store.pop(old, None)

    @property
    def entry_count(self) -> int:
        return len(self._store)

    def top_keys(self, n: int = 10) -> list[str]:
        return self._insertion_order[-n:]


# ─── Metrics ──────────────────────────────────────────────────────────────────

class _Metrics:
    __slots__ = ("hit", "miss", "stale_served", "firestore_errors", "last_warmup_at")

    def __init__(self) -> None:
        self.hit = 0
        self.miss = 0
        self.stale_served = 0
        self.firestore_errors = 0
        self.last_warmup_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cacheHitCount": self.hit,
            "cacheMissCount": self.miss,
            "staleServedCount": self.stale_served,
            "firestoreErrorCount": self.firestore_errors,
            "lastWarmupAt": self.last_warmup_at,
        }


# ─── Main cache service ───────────────────────────────────────────────────────

class CatalogEdgeCache:
    """
    Two-layer (memory + optional Redis), stale-if-error catalog cache.

    Usage
    -----
    key    = catalog_cache.build_key("products", country="es", page=1, limit=20)
    result = await catalog_cache.get_or_load(key, loader,
                 fresh_ttl=PRODUCTS_FRESH_TTL,
                 stale_ttl=PRODUCTS_STALE_TTL)
    """

    def __init__(self) -> None:
        self._mem = _MemoryLayer()
        self._metrics = _Metrics()
        self._locks: dict[str, asyncio.Lock] = {}
        self._redis_enabled = False

    # ─── Key building ──────────────────────────────────────────────────────────

    @staticmethod
    def build_key(kind: str, **params: Any) -> str:
        """Stable, normalized cache key for a catalog request."""
        clean: dict[str, Any] = {}
        for k, v in sorted(params.items()):
            if v is None or v == "":
                continue
            clean[k] = v.strip().lower() if isinstance(v, str) else v
        fp = hashlib.md5(
            json.dumps(clean, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return f"catalog:{kind}:v1:{fp}"

    # ─── Internal helpers ──────────────────────────────────────────────────────

    def _lock_for(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _store(self, key: str, value: Any, fresh_ttl: int, stale_ttl: int) -> None:
        # Negative-cache guard: empty results get a very short TTL.
        products = value.get("products") if isinstance(value, dict) else None
        count = value.get("count", 1) if isinstance(value, dict) else 1
        if isinstance(products, list) and len(products) == 0 and count == 0:
            fresh_ttl = min(fresh_ttl, NEGATIVE_CACHE_TTL)
            stale_ttl = min(stale_ttl, NEGATIVE_CACHE_TTL)
        self._mem.set(key, _Entry(value, fresh_ttl, stale_ttl))

    @staticmethod
    def _annotate(value: dict[str, Any], *, hit: bool, stale: bool,
                  reason: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
        meta: dict[str, Any] = {"hit": hit, "stale": stale, "source": "memory"}
        if stale and reason:
            meta["reason"] = reason
        if stale and generated_at:
            meta["generatedAt"] = generated_at
        result = dict(value)
        result["cache"] = meta
        return result

    # ─── get_or_load (main API) ────────────────────────────────────────────────

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[dict[str, Any]]],
        *,
        fresh_ttl: int,
        stale_ttl: int,
    ) -> dict[str, Any]:
        """
        1. Fresh memory hit → return immediately.
        2. Otherwise acquire per-key lock (single-flight).
        3. Re-check inside lock, then call loader.
        4. On Firestore quota/availability error → return stale if available.
        5. No stale available → re-raise for an honest 5xx.
        """
        # 1. Fresh hit (outside lock — fast path)
        entry = self._mem.get(key)
        if entry is not None and entry.is_fresh:
            self._metrics.hit += 1
            return self._annotate(entry.value, hit=True, stale=False)

        # 2. Single-flight gate
        lock = self._lock_for(key)
        async with lock:
            # Re-check after acquiring lock — another coroutine may have loaded
            entry = self._mem.get(key)
            if entry is not None and entry.is_fresh:
                self._metrics.hit += 1
                return self._annotate(entry.value, hit=True, stale=False)

            # 3. Load from source
            try:
                value = await loader()
                self._store(key, value, fresh_ttl, stale_ttl)
                self._metrics.miss += 1
                return self._annotate(value, hit=False, stale=False)

            except _STALE_TRIGGER as exc:
                self._metrics.firestore_errors += 1
                logger.warning(
                    "Firestore unavailable (key=%s, type=%s): %s — checking stale cache",
                    key, type(exc).__name__, exc,
                )
                # 4. Stale fallback
                if entry is not None and entry.is_usable_stale:
                    self._metrics.stale_served += 1
                    generated_at = datetime.fromtimestamp(
                        entry.wall_created, tz=timezone.utc
                    ).isoformat()
                    return self._annotate(
                        entry.value,
                        hit=True,
                        stale=True,
                        reason="firestore_unavailable",
                        generated_at=generated_at,
                    )
                # 5. No stale cache — propagate for honest 5xx
                raise

    # ─── Admin helpers ─────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        return {
            "memoryCacheEntries": self._mem.entry_count,
            "redisEnabled": self._redis_enabled,
            **self._metrics.to_dict(),
            "topKeys": self._mem.top_keys(10),
        }

    def clear(self) -> dict[str, Any]:
        cleared = self._mem.clear()
        return {"ok": True, "clearedEntries": cleared}

    def mark_warmup_done(self) -> None:
        self._metrics.last_warmup_at = datetime.now(timezone.utc).isoformat()


# ─── Singleton ─────────────────────────────────────────────────────────────────
catalog_cache = CatalogEdgeCache()


# ─── Read governor ─────────────────────────────────────────────────────────────

def safe_stream(query: Any, *, limit: int, context: str = "") -> list[Any]:
    """
    Execute a bounded Firestore query and return a list of DocumentSnapshots.

    Always requires a positive ``limit`` to prevent unbounded collection scans.
    Passing ``limit <= 0`` raises ``ValueError`` immediately.  Estimated read
    count is logged at DEBUG level for quota auditing.

    Usage::

        docs = safe_stream(
            db.collection("products").where(...),
            limit=500,
            context="products_route",
        )
    """
    if limit <= 0:
        raise ValueError(
            f"safe_stream requires limit > 0 to prevent unbounded Firestore reads "
            f"(context={context!r})"
        )
    docs = list(query.limit(limit).stream())
    logger.debug(
        "safe_stream: read %d docs [limit=%d, ctx=%r]",
        len(docs), limit, context,
    )
    return docs
