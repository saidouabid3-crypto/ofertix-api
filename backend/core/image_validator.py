from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import httpx

logger = logging.getLogger("ofertix.images")

_MAX_IMAGES = 3
_HEAD_TIMEOUT = 4.0


def _candidate_urls(urls: Iterable[str], max_images: int) -> list[str]:
    candidates = []
    for url in urls:
        clean = str(url or "").strip()
        if clean.startswith("http") and clean not in candidates:
            candidates.append(clean)
        if len(candidates) >= max_images * 2:
            break
    return candidates


async def _url_alive(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    try:
        async with httpx.AsyncClient(timeout=_HEAD_TIMEOUT, follow_redirects=True) as client:
            response = await client.head(url)
            if response.status_code >= 400:
                response = await client.get(url)
            content_type = (response.headers.get("content-type") or "").lower()
            return response.status_code < 400 and ("image" in content_type or len(response.content) > 512)
    except Exception:
        return False


async def filter_valid_images(urls: Iterable[str], *, max_images: int = _MAX_IMAGES) -> list[str]:
    candidates = _candidate_urls(urls, max_images)
    checks = await asyncio.gather(*[_url_alive(url) for url in candidates[: max_images * 2]])
    valid = [url for url, ok in zip(candidates, checks) if ok]
    return valid[:max_images]


def filter_valid_images_sync(urls: Iterable[str], *, max_images: int = _MAX_IMAGES) -> list[str]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(filter_valid_images(urls, max_images=max_images))

    # A synchronous normalizer can run inside an async request handler. Starting
    # or blocking that active loop is invalid, so retain sanitized URLs and let
    # the dedicated async validator handle network checks where required.
    return _candidate_urls(urls, max_images)[:max_images]
