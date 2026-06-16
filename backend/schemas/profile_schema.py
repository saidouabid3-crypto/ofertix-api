from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.smart_reel_schema import SmartReelOut


class PublicProfileOut(BaseModel):
    uid: str
    display_name: str = ''
    username: str = ''
    username_lower: str = ''
    photo_url: str = ''
    avatar_url: str = ''
    bio: str = ''
    country: str = 'global'
    city: str = ''
    currency: str = 'EUR'
    is_creator: bool = False
    is_verified: bool = False
    seller_verified: bool = False
    followers_count: int = 0
    following_count: int = 0
    reels_count: int = 0
    sell_items_count: int = 0
    total_likes: int = 0
    rating_average: float = 0
    rating_count: int = 0
    trust_level: str = 'new_seller'
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreatorProfileResponse(BaseModel):
    profile: PublicProfileOut
    reels: List[SmartReelOut] = Field(default_factory=list)


class ProfileUpdateIn(BaseModel):
    display_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    currency: Optional[str] = None
    photo_url: Optional[str] = None
    is_creator: Optional[bool] = None
