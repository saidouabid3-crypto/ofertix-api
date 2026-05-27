from pydantic import BaseModel, Field
from typing import List


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
