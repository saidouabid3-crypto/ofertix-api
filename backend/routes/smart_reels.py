from typing import Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile

from schemas.smart_reel_schema import SmartReelCommentCreate, SmartReelCommentOut, SmartReelCreate, SmartReelFeedResponse, SmartReelMessageCreate, SmartReelMessageOut, SmartReelOut, SmartReelUpdate
from services.cloudinary_upload_service import cloudinary_upload_service
from services.smart_reel_service import smart_reel_service

router = APIRouter(prefix='/smart-reels', tags=['Smart Reels'])


@router.get('/feed', response_model=SmartReelFeedResponse)
async def get_smart_reels_feed(limit: int = Query(default=10, ge=1, le=20), cursor: str | None = None, viewer_id: str | None = Query(default=None)):
    return smart_reel_service.get_feed(limit=limit, cursor=cursor, viewer_id=viewer_id)


@router.post('', response_model=SmartReelOut)
async def create_smart_reel(payload: SmartReelCreate):
    return smart_reel_service.create_reel(payload)


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
    creator_id: str = Form('mobile_user'),
    creator_name: str = Form('Ofertix User'),
    creator_avatar_url: str = Form(''),
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
        creator_id=creator_id,
        creator_name=creator_name,
        creator_avatar_url=creator_avatar_url,
    )
    return smart_reel_service.create_reel(payload)


@router.patch('/{reel_id}', response_model=SmartReelOut)
async def update_smart_reel(reel_id: str, payload: SmartReelUpdate, actor_id: str = Query(default='mobile_user')):
    reel = smart_reel_service.update_reel(reel_id=reel_id, payload=payload, actor_id=actor_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return reel


@router.delete('/{reel_id}')
async def delete_smart_reel(reel_id: str, actor_id: str = Query(default='mobile_user')):
    ok = smart_reel_service.delete_reel(reel_id=reel_id, actor_id=actor_id)
    if not ok:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'deleted': True, 'reel_id': reel_id}


@router.post('/{reel_id}/view')
async def track_view(reel_id: str):
    reel = smart_reel_service.track_view(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'views': reel['views']}


@router.post('/{reel_id}/like')
async def like_reel(reel_id: str):
    reel = smart_reel_service.like(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'likes': reel['likes']}


@router.post('/{reel_id}/click')
async def click_reel(reel_id: str):
    reel = smart_reel_service.click(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'clicks': reel['clicks']}


@router.post('/{reel_id}/save')
async def save_reel(reel_id: str):
    reel = smart_reel_service.save(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'saves': reel['saves']}


@router.post('/{reel_id}/report')
async def report_reel(reel_id: str):
    reel = smart_reel_service.report(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return {'ok': True, 'reports': reel['reports']}


@router.post('/{reel_id}/message', response_model=SmartReelMessageOut)
async def message_creator(reel_id: str, payload: SmartReelMessageCreate):
    message = smart_reel_service.send_message(reel_id=reel_id, payload=payload)
    if not message:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return message


@router.get('/{reel_id}/comments')
async def get_comments(reel_id: str, limit: int = Query(default=50, ge=1, le=100)):
    return smart_reel_service.get_comments(reel_id=reel_id, limit=limit)


@router.post('/{reel_id}/comments', response_model=SmartReelCommentOut)
async def add_comment(reel_id: str, payload: SmartReelCommentCreate):
    comment = smart_reel_service.add_comment(reel_id=reel_id, text=payload.text, user_id=payload.user_id, user_name=payload.user_name)
    if not comment:
        raise HTTPException(status_code=404, detail='Smart reel not found')
    return comment


@router.post('/creators/{creator_id}/follow')
async def follow_creator(creator_id: str, follower_id: str = Body(default='mobile_user', embed=True)):
    return smart_reel_service.follow_creator(creator_id=creator_id, follower_id=follower_id)
