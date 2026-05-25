from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form

from schemas.smart_reel_schema import (
    SmartReelCreate,
    SmartReelOut,
    SmartReelFeedResponse,
)
from services.smart_reel_service import smart_reel_service
from services.cloudinary_upload_service import cloudinary_upload_service

router = APIRouter(prefix="/smart-reels", tags=["Smart Reels"])


@router.get("/feed", response_model=SmartReelFeedResponse)
async def get_smart_reels_feed(
    limit: int = Query(default=10, ge=1, le=20),
    cursor: str | None = None,
):
    return smart_reel_service.get_feed(limit=limit, cursor=cursor)


@router.post("", response_model=SmartReelOut)
async def create_smart_reel(payload: SmartReelCreate):
    return smart_reel_service.create_reel(payload)


@router.post("/upload", response_model=SmartReelOut)
async def upload_smart_reel(
    video: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    store: str = Form(...),
    current_price: float = Form(...),
    old_price: Optional[float] = Form(None),
    currency: str = Form("EUR"),
    affiliate_url: Optional[str] = Form(None),
    product_id: Optional[str] = Form(None),
):
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(
            status_code=400,
            detail="Only video files are allowed",
        )

    upload_result = cloudinary_upload_service.upload_reel_video(video)
    video_url = upload_result.get("secure_url")

    if not video_url:
        raise HTTPException(
            status_code=500,
            detail="Video upload failed",
        )

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

    return smart_reel_service.create_reel(payload)


@router.post("/{reel_id}/view")
async def track_view(reel_id: str):
    reel = smart_reel_service.track_view(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Smart reel not found")
    return {"ok": True, "views": reel["views"]}


@router.post("/{reel_id}/like")
async def like_reel(reel_id: str):
    reel = smart_reel_service.like(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Smart reel not found")
    return {"ok": True, "likes": reel["likes"]}


@router.post("/{reel_id}/click")
async def click_reel(reel_id: str):
    reel = smart_reel_service.click(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Smart reel not found")
    return {"ok": True, "clicks": reel["clicks"]}


@router.post("/{reel_id}/save")
async def save_reel(reel_id: str):
    reel = smart_reel_service.save(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Smart reel not found")
    return {"ok": True, "saves": reel["saves"]}


@router.post("/{reel_id}/report")
async def report_reel(reel_id: str):
    reel = smart_reel_service.report(reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Smart reel not found")
    return {"ok": True, "reports": reel["reports"]}