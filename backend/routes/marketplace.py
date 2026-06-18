import asyncio
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from core.auth import require_active_user
from core.market_config import normalize_market
from services.catalog_edge_cache import catalog_cache, MARKETPLACE_FRESH_TTL, MARKETPLACE_STALE_TTL
from services.cloudinary_upload_service import cloudinary_upload_service
from services.marketplace_service import MarketplaceService
from services.review_service import review_service
from schemas.marketplace_schema import MarketplaceValidationError
from schemas.review_schema import CreateReviewRequest, ReviewOut

router = APIRouter(prefix='/marketplace', tags=['marketplace'])
service = MarketplaceService()

_IMAGE_ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
_IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post('/upload-image')
async def upload_marketplace_image(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_active_user),
):
    if not file.content_type or file.content_type not in _IMAGE_ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail={'code': 'INVALID_IMAGE_TYPE', 'message': 'Only JPEG, PNG, or WebP images are allowed'},
        )
    import io
    content = await file.read()
    if len(content) > _IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail={'code': 'IMAGE_TOO_LARGE', 'message': 'Image must be under 5 MB'},
        )
    file.file = io.BytesIO(content)
    try:
        result = cloudinary_upload_service.upload_marketplace_image(file)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail={'code': 'IMAGE_UPLOAD_UNAVAILABLE', 'message': 'Image upload is temporarily unavailable'},
        )
    url = result.get('secure_url') or ''
    if not url:
        raise HTTPException(
            status_code=503,
            detail={'code': 'IMAGE_UPLOAD_UNAVAILABLE', 'message': 'Image upload is temporarily unavailable'},
        )
    # Pre-envelope the response so ApiEnvelopeMiddleware passes it through
    # unchanged (the middleware only wraps when the three envelope keys are absent).
    return {
        'success': True,
        'data': {
            'url': url,
            'publicId': result.get('public_id', ''),
            'width': result.get('width'),
            'height': result.get('height'),
        },
        'error': None,
    }


@router.get('/my-items')
def get_my_marketplace_items(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(require_active_user),
):
    """Return authenticated seller's own items including pending/hidden (owner-only view)."""
    return {'items': service.get_my_items(current_user['uid'], limit=limit)}


@router.get('/items')
async def list_marketplace_items(
    limit: int = Query(default=30, ge=1, le=100),
    country: str = Query(default='es'),
    city: Optional[str] = None,
    category: Optional[str] = None,
):
    # Read governor: cap at 40 to reduce Firestore reads per request.
    effective_limit = min(limit, 40)
    market = normalize_market(country)
    key = catalog_cache.build_key(
        'marketplace',
        country=market,
        city=city or None,
        category=category or None,
        limit=effective_limit,
    )

    async def _load() -> dict:
        items = await asyncio.to_thread(
            service.list_items,
            limit=effective_limit,
            city=city,
            category=category,
            country=country,
        )
        return {'items': items}

    return await catalog_cache.get_or_load(
        key, _load, fresh_ttl=MARKETPLACE_FRESH_TTL, stale_ttl=MARKETPLACE_STALE_TTL
    )

@router.post('/items')
def create_marketplace_item(payload: Dict[str, Any], current_user: dict = Depends(require_active_user)):
    try:
        return service.create_item(payload, current_user=current_user)
    except MarketplaceValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={'code': exc.code, 'message': exc.message},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={'code': 'VALIDATION_ERROR', 'message': str(exc)},
        )

@router.get('/items/{item_id}')
def get_marketplace_item(item_id: str):
    item = service.get_public_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item

@router.get('/items/{item_id}/similar')
def get_similar_marketplace_items(
    item_id: str,
    limit: int = Query(default=8, ge=1, le=12),
):
    return {'items': service.get_similar_items(item_id, limit=limit)}

def _update_my_marketplace_item(
    item_id: str,
    payload: Dict[str, Any],
    current_user: dict,
):
    try:
        item = service.update_item(item_id, payload, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except MarketplaceValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={'code': exc.code, 'message': exc.message},
        )
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item


@router.patch('/my-items/{item_id}')
def update_my_marketplace_item(
    item_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(require_active_user),
):
    return _update_my_marketplace_item(item_id, payload, current_user)


@router.patch('/items/{item_id}')
def update_marketplace_item(
    item_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(require_active_user),
):
    return _update_my_marketplace_item(item_id, payload, current_user)


def _archive_my_marketplace_item(item_id: str, current_user: dict):
    try:
        item = service.delete_item(item_id, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item


@router.delete('/my-items/{item_id}')
def archive_my_marketplace_item(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    return _archive_my_marketplace_item(item_id, current_user)


@router.delete('/items/{item_id}')
def delete_marketplace_item(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    item = _archive_my_marketplace_item(item_id, current_user)
    return {'ok': True, 'archived': True, 'deleted': False, 'item': item}


def _mark_my_marketplace_item_sold(item_id: str, current_user: dict):
    try:
        item = service.mark_item_sold(item_id, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except MarketplaceValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={'code': exc.code, 'message': exc.message},
        )
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item


@router.post('/my-items/{item_id}/mark-sold')
def mark_my_marketplace_item_sold(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    return _mark_my_marketplace_item_sold(item_id, current_user)


@router.post('/items/{item_id}/mark-sold')
def mark_marketplace_item_sold(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    return _mark_my_marketplace_item_sold(item_id, current_user)

@router.post('/items/{item_id}/favorite')
def favorite_marketplace_item(
    item_id: str,
    payload: Dict[str, Any] | None = None,
    current_user: dict = Depends(require_active_user),
):
    return service.favorite_item(item_id, current_user['uid'])

@router.delete('/items/{item_id}/favorite')
def unfavorite_marketplace_item(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    return service.unfavorite_item(item_id, current_user['uid'])

@router.get('/items/{item_id}/favorite')
def get_marketplace_item_favorite_status(
    item_id: str,
    current_user: dict = Depends(require_active_user),
):
    return {'is_saved': service.is_item_favorited(item_id, current_user['uid'])}

@router.post('/reviews', response_model=ReviewOut)
def create_marketplace_review(
    payload: CreateReviewRequest,
    current_user: dict = Depends(require_active_user),
):
    try:
        return review_service.create_review(payload, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post('/items/{item_id}/report')
def report_marketplace_item(
    item_id: str,
    payload: Dict[str, Any] | None = None,
    current_user: dict = Depends(require_active_user),
):
    reason = (payload or {}).get('reason') or 'No reason provided'
    return service.report_item(item_id, current_user['uid'], reason)
