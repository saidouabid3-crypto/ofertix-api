from __future__ import annotations

import asyncio
import hashlib
import re
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

# Accept any 1–12 char alphanumeric variant (A/B/C/D/0-9 or longer session tokens)
_VARIANT_RE = re.compile(r'^[A-Za-z0-9]{1,12}$')


def _day_seed() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _bound_variant(variant: str, *, country: str, day: str) -> str:
    """
    Return a safe variant string.
    Accepts any 1–12 char alphanumeric from the client (supports 0–9 refresh tokens).
    Falls back to deterministic ABCD hash when client sends nothing valid.
    """
    v = (variant or '').strip()
    if v and _VARIANT_RE.match(v):
        return v
    h = int(hashlib.md5(f"{country}:{day}".encode()).hexdigest()[:4], 16)
    return 'ABCD'[h % 4]


def _seen_fingerprint(seen_ids: list[str]) -> str:
    """Short MD5 fingerprint of the sorted seen-ID set — safe for cache keys."""
    if not seen_ids:
        return ''
    payload = '|'.join(sorted(set(seen_ids)))
    return hashlib.md5(payload.encode()).hexdigest()[:8]


def _apply_seen_demotion(feed: dict[str, Any], seen_ids: set[str]) -> dict[str, Any]:
    """
    Post-cache pass: push already-seen products to the end of both the flat
    `products` list AND every named section.
    Does not mutate the cached dict — returns a shallow copy.
    """
    if not seen_ids:
        return feed

    result = dict(feed)

    # Reorder flat products list
    products: list[dict[str, Any]] = feed.get('products') or []
    if products:
        unseen = [p for p in products if str(p.get('id') or '') not in seen_ids]
        seen_tail = [p for p in products if str(p.get('id') or '') in seen_ids]
        result['products'] = unseen + seen_tail

    # Reorder every named section
    sections = feed.get('sections')
    if isinstance(sections, dict):
        new_sections: dict[str, Any] = {}
        for sec_key, sec_items in sections.items():
            if not isinstance(sec_items, list):
                new_sections[sec_key] = sec_items
                continue
            unseen_s = [p for p in sec_items if str(p.get('id') or '') not in seen_ids]
            seen_s = [p for p in sec_items if str(p.get('id') or '') in seen_ids]
            new_sections[sec_key] = unseen_s + seen_s
        result['sections'] = new_sections

    return result


@router.get('')
async def home_feed(
    country: str = 'es',
    limit: int = Query(40, ge=10, le=100),
    variant: str = Query('', description='Feed variant / refresh token (1-12 alphanumeric)'),
    seenIds: str = Query('', description='Comma-separated product IDs seen recently (max 50)'),
):
    day = _day_seed()
    v = _bound_variant(variant, country=country, day=day)

    seen_list: list[str] = [s.strip() for s in seenIds.split(',') if s.strip()][:50]
    seen_set: set[str] = set(seen_list)

    # Include seen fingerprint so different seen-sets get properly demoted results
    seen_fp = _seen_fingerprint(seen_list)
    key = catalog_cache.build_key(
        'discovery_feed',
        country=country,
        limit=limit,
        day=day,
        variant=v,
        seen_fp=seen_fp,
    )

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
