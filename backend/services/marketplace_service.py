from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from repositories.marketplace_repository import MarketplaceRepository
from repositories.profile_repository import profile_repository
from core.market_config import normalize_market
from schemas.marketplace_schema import (
    IMPORTANT_LISTING_FIELDS,
    MarketplaceValidationError,
    validate_and_normalize_listing,
)
from utils.market_filter import item_available_for_country, normalize_item_market_fields

_BLOCKED_URL_SCHEMES = ('data:', 'file://', 'blob:')
_BLOCKED_HOSTS = frozenset(('localhost', '127.0.0.1', '0.0.0.0', '::1'))


def _assert_safe_image_url(url: str) -> None:
    url = url.strip()
    if not url:
        return
    for scheme in _BLOCKED_URL_SCHEMES:
        if url.startswith(scheme):
            raise ValueError(f'Image URL not accepted: {scheme} scheme is blocked; upload via /marketplace/upload-image')
    if not url.startswith('http://') and not url.startswith('https://'):
        raise ValueError('Image URL must start with http:// or https://')
    try:
        host = urlparse(url).hostname or ''
    except Exception:
        raise ValueError('Image URL is not valid')
    if not host or host in _BLOCKED_HOSTS:
        raise ValueError('Image URL host is not accepted')


def _normalize_and_validate_images(payload: Dict[str, Any]) -> None:
    """Normalize images/image fields and reject unsafe URLs (base64, file://, localhost)."""
    raw_images = payload.get('images') or payload.get('gallery') or []
    if isinstance(raw_images, str):
        raw_images = [raw_images] if raw_images else []

    safe_urls: List[str] = []
    for raw in raw_images:
        url = str(raw or '').strip()
        if url:
            _assert_safe_image_url(url)
            safe_urls.append(url)

    payload['images'] = safe_urls

    single = str(payload.get('image') or '').strip()
    if single:
        _assert_safe_image_url(single)
    elif safe_urls:
        payload['image'] = safe_urls[0]


class MarketplaceService:
    def __init__(self):
        self.repo = MarketplaceRepository()

    def list_items(self, limit: int = 30, city: Optional[str] = None, category: Optional[str] = None, country: str = 'es'):
        market = normalize_market(country)
        items = self.repo.list_items(limit=limit * 3, city=city, category=category)
        filtered = [normalize_item_market_fields(i, market) for i in items if item_available_for_country(i, market)]
        return filtered[:limit]

    def create_item(self, payload: Dict[str, Any], current_user: dict):
        user_id = str(current_user.get('uid') or '').strip()
        if not user_id:
            raise MarketplaceValidationError(
                'AUTHENTICATION_REQUIRED',
                'Authenticated user is required',
            )
        payload = {
            **payload,
            **validate_and_normalize_listing(payload),
        }
        payload['sellerId'] = user_id
        payload['userId'] = user_id
        payload['ownerId'] = user_id
        payload['creatorId'] = user_id
        # Security: user-created items must start pending and inactive until moderated.
        payload['status'] = 'pending'
        payload['isActive'] = False
        payload['visibleToUsers'] = False
        payload['viewCount'] = 0
        payload['favoriteCount'] = 0
        payload['reportCount'] = 0
        payload['approvedAt'] = None
        payload['rejectedAt'] = None
        payload['archivedAt'] = None
        payload['rejectionReason'] = None
        # Strip moderation/trust fields the user must not control.
        for _field in ('isFeatured', 'isSponsored', 'sellerBanned', 'isSellerBanned',
                       'sellerBlocked', 'moderationStatus', 'sellerStatus', 'adminIssue'):
            payload.pop(_field, None)
        # Validate and normalize image URLs (rejects base64, file://, localhost).
        _normalize_and_validate_images(payload)
        profile = profile_repository.get_profile(user_id) or {}
        payload['sellerName'] = (
            profile.get('display_name')
            or current_user.get('name')
            or ''
        )
        payload['sellerUsername'] = profile.get('username') or ''
        payload['sellerAvatarUrl'] = (
            profile.get('avatar_url')
            or profile.get('photo_url')
            or current_user.get('picture')
            or ''
        )
        payload['sellerVerified'] = bool(
            profile.get('seller_verified')
            or profile.get('sellerVerified')
            or profile.get('is_verified')
            or profile.get('isVerified')
        )
        return self.repo.create_item(payload)

    def get_item(self, item_id: str):
        return self.repo.get_item(item_id)

    def get_public_item(self, item_id: str):
        return self.repo.get_public_item(item_id)

    def get_similar_items(self, item_id: str, limit: int = 8):
        item = self.repo.get_public_item(item_id)
        if not item:
            return []
        limit = max(1, min(limit, 12))
        category = str(item.get('category') or '').strip() or None
        country = str(item.get('countryCode') or item.get('country') or 'es')
        candidates = self.list_items(
            limit=limit + 1, category=category, country=country
        )
        similar = [c for c in candidates if c.get('id') != item_id]
        return similar[:limit]

    def get_my_items(self, user_id: str, limit: int = 50):
        return self.repo.get_user_items(user_id, limit=limit)

    def _assert_owner(self, item_id: str, current_user: dict) -> Optional[Dict[str, Any]]:
        item = self.repo.get_item(item_id)
        if not item:
            return None
        user_id = str(current_user.get('uid') or '').strip()
        owners = {
            str(item.get(key) or '').strip()
            for key in ('ownerId', 'userId', 'sellerId', 'creatorId')
        }
        owners.discard('')
        if not owners or user_id not in owners:
            raise PermissionError('You can only modify your own marketplace items')
        return item

    def update_item(self, item_id: str, payload: Dict[str, Any], current_user: dict):
        existing = self._assert_owner(item_id, current_user)
        if not existing:
            return None
        status = str(existing.get('status') or '').strip().lower()
        if status in {'archived', 'deleted'}:
            raise MarketplaceValidationError(
                'LISTING_ARCHIVED',
                'Archived listings cannot be edited',
            )
        if status == 'hidden':
            raise MarketplaceValidationError(
                'LISTING_HIDDEN',
                'Hidden listings cannot be edited until restored by moderation',
            )

        merged = {**existing, **payload}
        normalized = validate_and_normalize_listing(merged)
        changed_important = any(
            normalized.get(key) != existing.get(key)
            for key in IMPORTANT_LISTING_FIELDS
        )
        update = dict(normalized)
        update['editedAt'] = datetime.now(timezone.utc)
        if changed_important and status in {'approved', 'active', 'published', 'rejected'}:
            update.update({
                'status': 'pending',
                'isActive': False,
                'visibleToUsers': False,
                'approvedAt': None,
                'rejectedAt': None,
                'rejectionReason': None,
            })
        return self.repo.update_item(item_id, update)

    def delete_item(self, item_id: str, current_user: dict):
        existing = self._assert_owner(item_id, current_user)
        if not existing:
            return None
        return self.repo.archive_item(item_id)

    def permanently_delete_item(self, item_id: str, current_user: dict):
        """Tombstone-delete: sets status='deleted'. Idempotent if already deleted."""
        existing = self._assert_owner(item_id, current_user)
        if not existing:
            return None
        if str(existing.get('status') or '').strip().lower() == 'deleted':
            return existing  # Idempotent
        return self.repo.delete_listing_tombstone(item_id)

    def mark_item_sold(self, item_id: str, current_user: dict):
        existing = self._assert_owner(item_id, current_user)
        if not existing:
            return None
        status = str(existing.get('status') or '').strip().lower()
        if status in {'archived', 'deleted'}:
            raise MarketplaceValidationError(
                'LISTING_ARCHIVED',
                'Archived listings cannot be marked sold',
            )
        if status == 'sold':
            return existing
        return self.repo.mark_item_sold(item_id)

    def favorite_item(self, item_id: str, user_id: str):
        return self.repo.favorite_item(item_id, user_id)

    def unfavorite_item(self, item_id: str, user_id: str):
        return self.repo.unfavorite_item(item_id, user_id)

    def is_item_favorited(self, item_id: str, user_id: str) -> bool:
        return self.repo.is_item_favorited(item_id, user_id)

    def report_item(self, item_id: str, user_id: str, reason: str):
        return self.repo.report_item(item_id, user_id, reason)
