from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger("ofertix.redis")

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


class _MemoryRedis:
    """Dev fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _purge(self) -> None:
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if exp is not None and exp <= now]
        for key in expired:
            self._store.pop(key, None)

    def get(self, key: str) -> str | None:
        self._purge()
        row = self._store.get(key)
        if not row:
            return None
        return row[0]

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._purge()
        expires = time.time() + ex if ex else None
        self._store[key] = (value, expires)
        return True

    def incr(self, key: str) -> int:
        self._purge()
        current = int(self.get(key) or "0")
        new_value = current + 1
        _, expires = self._store.get(key, ("0", None))
        self._store[key] = (str(new_value), expires)
        return new_value

    def expire(self, key: str, seconds: int) -> bool:
        self._purge()
        if key not in self._store:
            return False
        value, _ = self._store[key]
        self._store[key] = (value, time.time() + seconds)
        return True

    def ttl(self, key: str) -> int:
        self._purge()
        row = self._store.get(key)
        if not row:
            return -2
        _, exp = row
        if exp is None:
            return -1
        remaining = int(exp - time.time())
        return max(remaining, -2)

    def ping(self) -> bool:
        return True


class RedisClient:
    def __init__(self) -> None:
        self._client: Any = None
        self._using_memory = False

    def connect(self) -> None:
        url = os.getenv("REDIS_URL", "").strip()
        if redis is None or not url:
            logger.warning("REDIS_URL not set or redis package missing; using in-memory rate limit store")
            self._client = _MemoryRedis()
            self._using_memory = True
            return

        try:
            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=3)
            client.ping()
            self._client = client
            self._using_memory = False
            logger.info("Redis connected")
        except Exception as exc:
            logger.warning("Redis connection failed (%s); using in-memory fallback", exc)
            self._client = _MemoryRedis()
            self._using_memory = True

    @property
    def is_memory_fallback(self) -> bool:
        return self._using_memory

    @property
    def raw(self) -> Any:
        if self._client is None:
            self.connect()
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._using_memory:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None


redis_client = RedisClient()
