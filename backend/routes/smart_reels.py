from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from core.auth import require_active_user, require_user
from schemas.smart_reel_schema import (
    SmartReelCommentCreate,
    SmartReelCommentOut,
    SmartReelCreate,
    SmartReelFeedResponse,
    SmartReelMessageCreate,
    SmartReelMessageOut,
    SmartReelOut,
    SmartReelUpdate,
)
from services.cloudinary_upload_service import cloudinary_upload_service
from services.smart_reel_service import smart_reel_service

router = APIRouter(prefix='/smart-reels', tags=['Smart Reels'])


@router.get('/feed', response_model=SmartReelFeedResponse)
async def get_smart_reels_feed(
    limit: int = Query(default=10, ge=1, le=20),
    cursor: str | None = None,
    viewer_id: str | None = Query(default=None),
):
    return smart_reel_service.get_feed(limit=limit, cursor=cursor, viewer_id=viewer_id)


@router.post('', response_model=SmartReelOut)
async def create_smart_reel(
    payload: SmartReelCreate,
    current_user: dict = Depends(require_active_user),
):
    return smart_reel_service.create_reel(payload, current_user=current_user)


@router.post('/upload', response_model=SmartReelOut)
async def upload_smart_reel(
    video: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(''),
    store: str = Form(...),
    current_price: float = Form(...),
    old_price: Optional[float] = Form(None),
    currency: str = Form('EUR'),
    affiliate_url: Optional[str] = Form(None),
    product_id: Optional[str] = Form(None),
    current_user: dict = Depends(require_active_user),
):
    if not video.content_type or not video.content_type.startswith('video/'):
        raise HTTPException(status_code=400, detail='Only video files are allowed')

    upload_result = cloudinary_upload_service.upload_reel_video(video)
    video_url = upload_result.get('secure_url')

    if not video_url:
        raise HTTPException(status_code=500, detail='Video upload failed')

    payload = SmartReelCreate(
        title=title,
        description=description,
        store=store,
        current_price=current_price,
        old_price=old_price,
        currency=currency,
        video_url=video_url,
        affiliate_url=affiliate_url,
        product_id=product_id,
    )
    return smart_reel_service.create_reel(payload, current_user=current_user)


@router.patch('/{reel_id}', response_model=SmartReelOut)
async def update_smart_reel(
    reel_id: str,
    payload: SmartReelUpdate,
    current_user: dict = Depends(require_active_user),
):
    reel = smart_reel_service.update_reel(
        reel_id=reel_id,
        payload=payload,
        current_user=current_user,
    )

    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found or forbidden')

    return reel


@router.delete('/{reel_id}')
async def delete_smart_reel(
    reel_id: str,
    current_user: dict = Depends(require_active_user),
):
    ok = smart_reel_service.delete_reel(reel_id=reel_id, current_user=current_user)

    if not ok:
        raise HTTPException(status_code=404, detail='Smart reel not found or forbidden')

    return {'ok': True, 'deleted': True, 'reel_id': reel_id}


@router.post('/{reel_id}/view')
async def track_view(reel_id: str):
    reel = smart_reel_service.track_view(reel_id)

    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')

    return {'ok': True, 'views': reel['views']}


@router.post('/{reel_id}/like')
async def like_reel(
    reel_id: str,
    current_user: dict = Depends(require_active_user),
):
    result = smart_reel_service.like(reel_id, viewer_id=current_user['uid'])
    if result is None:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'is_liked': result.get('is_liked', False), 'likes': result.get('likes', 0)}


@router.post('/{reel_id}/click')
async def click_reel(reel_id: str):
    reel = smart_reel_service.click(reel_id)

    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')

    return {'ok': True, 'clicks': reel['clicks']}


@router.post('/{reel_id}/save')
async def save_reel(
    reel_id: str,
    current_user: dict = Depends(require_active_user),
):
    result = smart_reel_service.save(reel_id, viewer_id=current_user['uid'])
    if result is None:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'is_saved': result.get('is_saved', False), 'saves': result.get('saves', 0)}


@router.post('/{reel_id}/report')
async def report_reel(
    reel_id: str,
    current_user: dict = Depends(require_active_user),
):
    result = smart_reel_service.report(reel_id, viewer_id=current_user['uid'])
    return {'ok': True, 'reports': result.get('reports', 0), 'already_reported': result.get('already_reported', False)}


@router.post('/{reel_id}/message', response_model=SmartReelMessageOut)
async def message_creator(
    reel_id: str,
    payload: SmartReelMessageCreate,
    current_user: dict = Depends(require_active_user),
):
    message = smart_reel_service.send_message(
        reel_id=reel_id,
        payload=payload,
        current_user=current_user,
    )

    if not message:
        raise HTTPException(status_code=404, detail='Smart reel not found')

    return message


@router.get('/{reel_id}/comments')
async def get_comments(reel_id: str, limit: int = Query(default=50, ge=1, le=100)):
    return smart_reel_service.get_comments(reel_id=reel_id, limit=limit)


@router.post('/{reel_id}/comments', response_model=SmartReelCommentOut)
async def add_comment(
    reel_id: str,
    payload: SmartReelCommentCreate,
    current_user: dict = Depends(require_active_user),
):
    comment = smart_reel_service.add_comment(
        reel_id=reel_id,
        text=payload.text,
        current_user=current_user,
    )

    if not comment:
        raise HTTPException(status_code=404, detail='Smart reel not found')

    return comment


@router.post('/creators/{creator_id}/follow')
async def follow_creator(
    creator_id: str,
    current_user: dict = Depends(require_active_user),
):
    return smart_reel_service.follow_creator(
        creator_id=creator_id,
        current_user=current_user,
    )
