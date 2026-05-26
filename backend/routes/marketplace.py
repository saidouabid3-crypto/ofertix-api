from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_user
from services.marketplace_service import MarketplaceService

router = APIRouter(prefix='/marketplace', tags=['marketplace'])
service = MarketplaceService()


@router.get('/items')
def list_marketplace_items(
    limit: int = Query(default=30, ge=1, le=100),
    city: Optional[str] = None,
    category: Optional[str] = None,
):
    return {'items': service.list_items(limit=limit, city=city, category=category)}


@router.post('/items')
def create_marketplace_item(payload: Dict[str, Any], current_user: dict = Depends(require_user)):
    try:
        secured = dict(payload)
        secured['sellerId'] = current_user['uid']
        secured['seller_id'] = current_user['uid']
        secured['sellerName'] = current_user.get('name') or current_user.get('email', '').split('@')[0] or 'Ofertix User'
        return service.create_item(secured)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get('/items/{item_id}')
def get_marketplace_item(item_id: str):
    item = service.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return item


@router.patch('/items/{item_id}')
def update_marketplace_item(item_id: str, payload: Dict[str, Any], current_user: dict = Depends(require_user)):
    item = service.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    owner = item.get('sellerId') or item.get('seller_id')
    if owner and owner != current_user['uid']:
        raise HTTPException(status_code=403, detail='Only seller can update this item')
    clean = dict(payload)
    clean.pop('sellerId', None)
    clean.pop('seller_id', None)
    updated = service.update_item(item_id, clean)
    if not updated:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return updated


@router.delete('/items/{item_id}')
def delete_marketplace_item(item_id: str, current_user: dict = Depends(require_user)):
    item = service.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    owner = item.get('sellerId') or item.get('seller_id')
    if owner and owner != current_user['uid']:
        raise HTTPException(status_code=403, detail='Only seller can delete this item')
    deleted = service.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='Marketplace item not found')
    return {'ok': True, 'deleted': True}


@router.post('/items/{item_id}/favorite')
def favorite_marketplace_item(item_id: str, current_user: dict = Depends(require_user)):
    return service.favorite_item(item_id, current_user['uid'])


@router.post('/items/{item_id}/report')
def report_marketplace_item(item_id: str, payload: Dict[str, Any], current_user: dict = Depends(require_user)):
    reason = payload.get('reason') or 'No reason provided'
    return service.report_item(item_id, current_user['uid'], reason)
