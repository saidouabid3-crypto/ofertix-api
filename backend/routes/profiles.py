from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_active_user, require_user
from schemas.profile_schema import (
    CreatorProfileResponse,
    ProfileUpdateIn,
    PublicProfileOut,
)
from schemas.smart_reel_schema import SmartReelOut
from services.profile_service import profile_service

router = APIRouter(prefix='/profiles', tags=['Profiles'])


@router.get('/me', response_model=PublicProfileOut)
async def get_my_profile(current_user: dict = Depends(require_active_user)):
    profile = profile_service.get_profile(current_user['uid'])
    if not profile:
        raise HTTPException(status_code=404, detail='Profile not found')
    return profile


@router.get('/{uid}', response_model=PublicProfileOut)
async def get_profile(uid: str):
    profile = profile_service.get_profile(uid)
    if not profile:
        raise HTTPException(status_code=404, detail='Profile not found')
    return profile


@router.get('/{uid}/public', response_model=PublicProfileOut)
async def get_public_profile(uid: str):
    profile = profile_service.get_profile(uid)
    if not profile:
        raise HTTPException(status_code=404, detail='Profile not found')
    return profile


@router.get('/{uid}/reels', response_model=list[SmartReelOut])
async def get_creator_reels(uid: str, limit: int = Query(default=30, ge=1, le=50)):
    return profile_service.get_creator_reels(uid=uid, limit=limit)


@router.get('/{uid}/sell-items')
async def get_profile_sell_items(uid: str, limit: int = Query(default=30, ge=1, le=50)):
    return {'items': profile_service.get_sell_items(uid=uid, limit=limit)}


@router.get('/{uid}/creator', response_model=CreatorProfileResponse)
async def get_creator_profile(uid: str, limit: int = Query(default=30, ge=1, le=50)):
    item = profile_service.get_creator_profile(uid=uid, limit=limit)
    if not item:
        raise HTTPException(status_code=404, detail='Creator profile not found')
    return item


@router.post('/{uid}/follow')
async def follow_profile(uid: str, current_user: dict = Depends(require_active_user)):
    return profile_service.follow_profile(uid=uid, follower_uid=current_user['uid'])


@router.delete('/{uid}/follow')
async def unfollow_profile(uid: str, current_user: dict = Depends(require_active_user)):
    return profile_service.unfollow_profile(uid=uid, follower_uid=current_user['uid'])


@router.put('/me', response_model=PublicProfileOut)
async def update_my_profile(
    payload: ProfileUpdateIn,
    current_user: dict = Depends(require_active_user),
):
    """Update authenticated user's own profile. Only safe mutable fields accepted."""
    uid = current_user['uid']

    update_data: dict = {}

    if payload.display_name is not None:
        name = payload.display_name.strip()[:60]
        if name:
            update_data['display_name'] = name

    if payload.username is not None:
        username = payload.username.strip().lower()
        # Basic format check: 3-24 chars, alphanumeric + underscore only.
        import re
        if re.match(r'^[a-z0-9_]{3,24}$', username):
            update_data['username'] = username
            update_data['username_lower'] = username
        else:
            raise HTTPException(
                status_code=422,
                detail='Username must be 3-24 characters: letters, numbers, underscore only.',
            )

    if payload.bio is not None:
        update_data['bio'] = payload.bio.strip()[:140]

    if payload.country is not None:
        update_data['country'] = payload.country.strip().lower()[:10]

    if payload.city is not None:
        update_data['city'] = payload.city.strip()[:80]

    if payload.currency is not None:
        update_data['currency'] = payload.currency.strip().upper()[:6]

    if payload.photo_url is not None:
        url = payload.photo_url.strip()
        if url.startswith('http'):
            update_data['photo_url'] = url
        elif url == '':
            update_data['photo_url'] = ''
        else:
            raise HTTPException(status_code=422, detail='photo_url must be a valid http/https URL or empty string.')

    if payload.is_creator is not None:
        update_data['is_creator'] = payload.is_creator

    profile = profile_service.update_profile(uid=uid, data=update_data)
    if not profile:
        raise HTTPException(status_code=404, detail='Profile not found. Create your profile first.')
    return profile
