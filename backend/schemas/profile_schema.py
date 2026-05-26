from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.smart_reel_schema import SmartReelOut


class PublicProfileOut(BaseModel):
    uid: str
    email: str = ''
    display_name: str = 'Ofertix User'
    username: str = ''
    username_lower: str = ''
    photo_url: str = ''
    bio: str = ''
    country: str = 'global'
    currency: str = 'EUR'
    is_creator: bool = False
    followers_count: int = 0
    following_count: int = 0
    reels_count: int = 0
    total_likes: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreatorProfileResponse(BaseModel):
    profile: PublicProfileOut
    reels: List[SmartReelOut] = Field(default_factory=list)
