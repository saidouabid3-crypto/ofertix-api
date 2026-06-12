from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from repositories.marketplace_repository import MarketplaceRepository
from repositories.profile_repository import profile_repository
from core.market_config import normalize_market, SUPPORTED_MARKETS
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
            raise ValueError('Authenticated user is required')
        market = normalize_market(payload.get('sellerCountryCode') or payload.get('country') or 'es')
        payload['sellerCountryCode'] = market
        payload['country'] = market
        payload['countryCode'] = market
        payload['currency'] = payload.get('currency') or SUPPORTED_MARKETS[market]['currency']
        payload.setdefault('availableCountries', [market])
        payload.setdefault('shipsTo', [] if payload.get('pickupOnly', True) else [market])
        payload.setdefault('pickupOnly', True)
        payload['sellerId'] = user_id
        payload['userId'] = user_id
        payload['ownerId'] = user_id
        payload['creatorId'] = user_id
        # Security: user-created items must start pending and inactive until moderated.
        payload['status'] = 'pending'
        payload['isActive'] = False
        payload['visibleToUsers'] = False
        # Strip moderation/trust fields the user must not control.
        for _field in ('isFeatured', 'isSponsored', 'sellerBanned', 'isSellerBanned',
                       'sellerBlocked', 'moderationStatus', 'sellerStatus', 'adminIssue'):
            payload.pop(_field, None)
        # Validate and normalize image URLs (rejects base64, file://, localhost).
        _normalize_and_validate_images(payload)
        profile = profile_repository.get_profile(user_id) or {}
        payload['sellerName'] = payload.get('sellerName') or profile.get('display_name') or ''
        payload['sellerUsername'] = payload.get('sellerUsername') or profile.get('username') or ''
        payload['sellerAvatarUrl'] = payload.get('sellerAvatarUrl') or profile.get('avatar_url') or profile.get('photo_url') or ''
        payload['sellerVerified'] = bool(payload.get('sellerVerified') or profile.get('seller_verified') or profile.get('is_verified'))
        return self.repo.create_item(payload)

    def get_item(self, item_id: str):
        return self.repo.get_item(item_id)

    def get_public_item(self, item_id: str):
        return self.repo.get_public_item(item_id)

    def _assert_owner(self, item_id: str, current_user: dict) -> None:
        item = self.repo.get_item(item_id)
        if not item:
            return
        user_id = str(current_user.get('uid') or '').strip()
        owners = {
            str(item.get(key) or '').strip()
            for key in ('ownerId', 'userId', 'sellerId', 'creatorId')
        }
        owners.discard('')
        if owners and user_id not in owners:
            raise PermissionError('You can only modify your own marketplace items')

    def update_item(self, item_id: str, payload: Dict[str, Any], current_user: dict):
        self._assert_owner(item_id, current_user)
        for protected_key in ('ownerId', 'userId', 'sellerId', 'creatorId'):
            payload.pop(protected_key, None)
        return self.repo.update_item(item_id, payload)

    def delete_item(self, item_id: str, current_user: dict):
        self._assert_owner(item_id, current_user)
        return self.repo.delete_item(item_id)

    def favorite_item(self, item_id: str, user_id: str):
        return self.repo.favorite_item(item_id, user_id)

    def report_item(self, item_id: str, user_id: str, reason: str):
        return self.repo.report_item(item_id, user_id, reason)
