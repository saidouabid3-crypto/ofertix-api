from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import require_active_user
from core.market_config import normalize_market
from services.marketplace_service import MarketplaceService

router = APIRouter(prefix='/marketplace', tags=['marketplace'])
service = MarketplaceService()

@router.get('/items')
def list_marketplace_items(limit: int = Query(default=30, ge=1, le=100), country: str = Query(default='es'), city: Optional[str] = None, category: Optional[str] = None):
    return {'items': service.list_items(limit=limit, city=city, category=category, country=normalize_market(country))}

@router.post('/items')
def create_marketplace_item(payload: Dict[str, Any], current_user: dict = Depends(require_active_user)):
    try:
        return service.create_item(payload, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get('/items/{item_id}')
def get_marketplace_item(item_id: str):
    item = service.get_public_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item

@router.patch('/items/{item_id}')
def update_marketplace_item(
    item_id: str,
    payload: Dict[str, Any],
    current_user: dict = Depends(require_active_user),
):
    try:
        item = service.update_item(item_id, payload, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item

@router.delete('/items/{item_id}')
def delete_marketplace_item(item_id: str, current_user: dict = Depends(require_active_user)):
    try:
        deleted = service.delete_item(item_id, current_user=current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return {'ok': True, 'deleted': True}

@router.post('/items/{item_id}/favorite')
def favorite_marketplace_item(
    item_id: str,
    payload: Dict[str, Any] | None = None,
    current_user: dict = Depends(require_active_user),
):
    return service.favorite_item(item_id, current_user['uid'])

@router.post('/items/{item_id}/report')
def report_marketplace_item(
    item_id: str,
    payload: Dict[str, Any] | None = None,
    current_user: dict = Depends(require_active_user),
):
    reason = (payload or {}).get('reason') or 'No reason provided'
    return service.report_item(item_id, current_user['uid'], reason)
