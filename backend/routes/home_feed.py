from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from services.catalog_edge_cache import (
    catalog_cache,
    HOME_FEED_FRESH_TTL,
    HOME_FEED_STALE_TTL,
)
from services.home_feed_service import build_home_feed

router = APIRouter(prefix='/home-feed', tags=['home-feed'])


@router.get('')
async def home_feed(country: str = 'es', limit: int = Query(40, ge=10, le=100)):
    key = catalog_cache.build_key("home_feed", country=country, limit=limit)

    async def _load() -> dict:
        return await asyncio.to_thread(build_home_feed, country=country, limit=limit)

    return await catalog_cache.get_or_load(
        key, _load, fresh_ttl=HOME_FEED_FRESH_TTL, stale_ttl=HOME_FEED_STALE_TTL
    )
