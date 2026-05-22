from typing import List, Optional
from pydantic import BaseModel, Field


class AIHistoryMessage(BaseModel):
    role: str
    content: str


class AISearchRequest(BaseModel):
    query: str
    countryCode: str = "global"
    currency: str = "EUR"
    language: str = "auto"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    history: List[AIHistoryMessage] = Field(default_factory=list)


class AIProduct(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    image: Optional[str] = None
    store: Optional[str] = None
    category: Optional[str] = None
    oldPrice: Optional[float] = None
    newPrice: Optional[float] = None
    discount: Optional[int] = None
    isOnline: Optional[bool] = None
    isGlobal: Optional[bool] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class AISearchResponse(BaseModel):
    answer: str
    searchQuery: str
    productQueries: List[str] = Field(default_factory=list)
    intent: str
    onlineOnly: bool
    localOnly: bool
    nearby: bool = False
    maxPrice: Optional[float] = None
    category: Optional[str] = None
    sortBy: str
    suggestions: List[str] = Field(default_factory=list)
    buyingTips: List[str] = Field(default_factory=list)
    needsProducts: bool = True
    products: List[AIProduct] = Field(default_factory=list)