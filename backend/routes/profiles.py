from fastapi import APIRouter, HTTPException, Query

from schemas.profile_schema import CreatorProfileResponse, PublicProfileOut
from schemas.smart_reel_schema import SmartReelOut
from services.profile_service import profile_service

router = APIRouter(prefix='/profiles', tags=['Profiles'])


@router.get('/{uid}', response_model=PublicProfileOut)
async def get_profile(uid: str):
    profile = profile_service.get_profile(uid)
    if not profile:
        raise HTTPException(status_code=404, detail='Profile not found')
    return profile


@router.get('/{uid}/reels', response_model=list[SmartReelOut])
async def get_creator_reels(uid: str, limit: int = Query(default=30, ge=1, le=50)):
    return profile_service.get_creator_reels(uid=uid, limit=limit)


@router.get('/{uid}/creator', response_model=CreatorProfileResponse)
async def get_creator_profile(uid: str, limit: int = Query(default=30, ge=1, le=50)):
    item = profile_service.get_creator_profile(uid=uid, limit=limit)
    if not item:
        raise HTTPException(status_code=404, detail='Creator profile not found')
    return item
