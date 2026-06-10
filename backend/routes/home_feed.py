from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query

from services.catalog_edge_cache import (
    catalog_cache,
    HOME_FEED_FRESH_TTL,
    HOME_FEED_STALE_TTL,
)
from services.discovery_feed_service import build_discovery_feed

router = APIRouter(prefix='/home-feed', tags=['home-feed'])

_VALID_VARIANTS = frozenset('ABCD')


def _day_seed() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _bound_variant(variant: str, *, country: str, day: str) -> str:
    """Return A/B/C/D — use caller-supplied value if valid, else derive from country+day."""
    v = (variant or '').upper().strip()
    if v in _VALID_VARIANTS:
        return v
    # deterministic fallback: hash(country + day) → A/B/C/D
    h = int(hashlib.md5(f"{country}:{day}".encode()).hexdigest()[:4], 16)
    return 'ABCD'[h % 4]


def _apply_seen_demotion(feed: dict[str, Any], seen_ids: set[str]) -> dict[str, Any]:
    """
    Post-cache pass: move already-seen products to the end of the flat `products` list.
    Sections are left intact (they carry their own ordering from the discovery engine).
    Does not mutate the cached dict — returns a shallow copy.
    """
    if not seen_ids:
        return feed
    products: list[dict[str, Any]] = feed.get('products') or []
    if not products:
        return feed

    unseen = [p for p in products if str(p.get('id') or '') not in seen_ids]
    seen_tail = [p for p in products if str(p.get('id') or '') in seen_ids]
    result = dict(feed)
    result['products'] = unseen + seen_tail
    return result


@router.get('')
async def home_feed(
    country: str = 'es',
    limit: int = Query(40, ge=10, le=100),
    variant: str = Query('', description='Feed variant A/B/C/D (optional, for session diversity)'),
    seenIds: str = Query('', description='Comma-separated product IDs seen recently (max 50)'),
):
    day = _day_seed()
    v = _bound_variant(variant, country=country, day=day)

    # Bounded cache key: no raw seenIds included
    key = catalog_cache.build_key(
        'discovery_feed', country=country, limit=limit, day=day, variant=v
    )

    # Parse and cap seenIds for post-cache demotion
    seen_list: list[str] = [s.strip() for s in seenIds.split(',') if s.strip()][:50]
    seen_set: set[str] = set(seen_list)

    async def _load() -> dict:
        return await asyncio.to_thread(
            build_discovery_feed,
            country=country,
            limit=limit,
            day_seed=day,
            variant=v,
            seen_ids=seen_list,
        )

    result = await catalog_cache.get_or_load(
        key, _load, fresh_ttl=HOME_FEED_FRESH_TTL, stale_ttl=HOME_FEED_STALE_TTL
    )

    return _apply_seen_demotion(result, seen_set)
