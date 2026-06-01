from pydantic import BaseModel, Field
from typing import List, Optional


class AdminStat(BaseModel):
    key: str
    label: str
    value: float | int
    suffix: str = ''


class AdminTopProduct(BaseModel):
    id: str = ''
    name: str
    store: str = ''
    clicks: int = 0
    revenue: float = 0.0
    countryCode: str = 'global'


class AdminConnectorStatus(BaseModel):
    source: str
    countryCode: str = 'global'
    enabled: bool = False
    lastSyncAt: str | None = None
    lastStatus: str = 'not_configured'
    lastError: str = ''


class AdminAiQueryLog(BaseModel):
    id: str = ''
    subject: Optional[str] = None
    uid: Optional[str] = None
    count: int = 0
    blocked: bool = False
    createdAt: Optional[str] = None


class AdminScrapeFailure(BaseModel):
    id: str = ''
    url: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None
    createdAt: Optional[str] = None


class AdminFlaggedProduct(BaseModel):
    id: str = ''
    name: Optional[str] = None
    store: Optional[str] = None
    adminIssue: Optional[str] = None
    countryCode: Optional[str] = None


class AdminPendingLocalReview(BaseModel):
    id: str = ''
    title: Optional[str] = None
    storeId: Optional[str] = None
    merchantId: Optional[str] = None
    countryCode: Optional[str] = None
    createdAt: Optional[str] = None


class AdminSystemError(BaseModel):
    id: str = ''
    path: Optional[str] = None
    message: Optional[str] = None
    createdAt: Optional[str] = None


class AdminDashboardResponse(BaseModel):
    live: bool = True
    totalUsers: int = 0
    totalClicks: int = 0
    totalOrders: int = 0
    revenue: float = 0.0
    totalProducts: int = 0
    totalReels: int = 0
    totalMarketplaceItems: int = 0
    openReports: int = 0
    topSearches: List[str] = Field(default_factory=list)
    topProducts: List[AdminTopProduct] = Field(default_factory=list)
    connectors: List[AdminConnectorStatus] = Field(default_factory=list)
    recentAiQueries: List[AdminAiQueryLog] = Field(default_factory=list)
    failedScrapings: List[AdminScrapeFailure] = Field(default_factory=list)
    flaggedProducts: List[AdminFlaggedProduct] = Field(default_factory=list)
    pendingLocalReviews: List[AdminPendingLocalReview] = Field(default_factory=list)
    systemErrors: List[AdminSystemError] = Field(default_factory=list)
