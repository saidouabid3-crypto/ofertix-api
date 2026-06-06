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


# ─── Overview ────────────────────────────────────────────────────────────────

class AdminOverviewResponse(BaseModel):
    totalUsers: int = 0
    totalReels: int = 0
    pendingReels: int = 0
    reportedReels: int = 0
    hiddenReels: int = 0
    rejectedReels: int = 0
    totalSellItems: int = 0
    pendingSellItems: int = 0
    reportedSellItems: int = 0
    totalReports: int = 0
    openReports: int = 0
    systemErrors: int = 0
    aiErrors: int = 0
    failedUploads: int = 0
    totalProducts: int = 0


# ─── Moderation ──────────────────────────────────────────────────────────────

class AdminModerationItem(BaseModel):
    id: str = ''
    title: Optional[str] = None
    description: Optional[str] = None
    status: str = 'approved'
    creatorId: Optional[str] = None
    creatorName: Optional[str] = None
    creatorUsername: Optional[str] = None
    creatorAvatarUrl: Optional[str] = None
    thumbnailUrl: Optional[str] = None
    videoUrl: Optional[str] = None
    imageUrl: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    store: Optional[str] = None
    category: Optional[str] = None
    reportsCount: int = 0
    createdAt: Optional[str] = None
    itemType: str = 'reel'  # 'reel' | 'marketplace'


class AdminModerationList(BaseModel):
    items: List[AdminModerationItem] = Field(default_factory=list)
    total: int = 0


# ─── Reports ─────────────────────────────────────────────────────────────────

class AdminReport(BaseModel):
    id: str = ''
    reportType: str = 'unknown'
    targetId: Optional[str] = None
    targetTitle: Optional[str] = None
    reporterId: Optional[str] = None
    reporterName: Optional[str] = None
    reason: Optional[str] = None
    status: str = 'open'
    adminNote: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class AdminReportList(BaseModel):
    reports: List[AdminReport] = Field(default_factory=list)
    total: int = 0


# ─── Users ───────────────────────────────────────────────────────────────────

class AdminUserView(BaseModel):
    uid: str = ''
    email: str = ''
    displayName: str = ''
    username: str = ''
    photoUrl: str = ''
    role: str = 'user'
    isAdmin: bool = False
    isVerified: bool = False
    sellerVerified: bool = False
    isBanned: bool = False
    reportsCount: int = 0
    reelsCount: int = 0
    sellItemsCount: int = 0
    followersCount: int = 0
    createdAt: Optional[str] = None


class AdminUserList(BaseModel):
    users: List[AdminUserView] = Field(default_factory=list)
    total: int = 0


# ─── Product quality ─────────────────────────────────────────────────────────

class AdminProductQualityItem(BaseModel):
    id: str = ''
    name: Optional[str] = None
    store: Optional[str] = None
    price: Optional[float] = None
    imageUrl: Optional[str] = None
    affiliateUrl: Optional[str] = None
    status: Optional[str] = None
    issue: Optional[str] = None
    countryCode: Optional[str] = None
    # Trust engine fields (populated after a quality scan or refresh)
    qualityScore: Optional[int] = None
    trustStatus: Optional[str] = None
    qualityFlags: Optional[List[str]] = None
    mediaQuality: Optional[dict] = None
    linkHealth: Optional[dict] = None
    priceConfidence: Optional[str] = None
    qualityUpdatedAt: Optional[str] = None


class AdminProductQualityList(BaseModel):
    items: List[AdminProductQualityItem] = Field(default_factory=list)
    total: int = 0


# ─── Product trust scan ───────────────────────────────────────────────────────

class ProductTrustScanRequest(BaseModel):
    dryRun: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    write: bool = False


class ProductTrustScanSummary(BaseModel):
    scanned: int = 0
    wouldUpdate: int = 0
    updated: int = 0
    missingImage: int = 0
    missingLink: int = 0
    missingPrice: int = 0
    singleImageOnly: int = 0
    duplicates: int = 0
    quarantined: int = 0
    needsReview: int = 0
    trusted: int = 0
    dryRun: bool = True


# ─── Product duplicates ───────────────────────────────────────────────────────

class DuplicateScanRequest(BaseModel):
    dryRun: bool = True
    limit: int = Field(default=300, ge=1, le=500)
    write: bool = False


class DuplicateScanSummary(BaseModel):
    scanned: int = 0
    groupsFound: int = 0
    candidateProducts: int = 0
    wouldUpdate: int = 0
    updated: int = 0
    dryRun: bool = True


class DuplicateProductItem(BaseModel):
    id: str = ''
    name: Optional[str] = None
    imageUrl: Optional[str] = None
    galleryCount: int = 0
    price: Optional[float] = None
    currency: Optional[str] = None
    store: Optional[str] = None
    primaryUrl: Optional[str] = None
    hasAffiliateUrl: bool = False
    hasProductUrl: bool = False
    qualityScore: Optional[int] = None
    trustStatus: Optional[str] = None
    priceConfidence: Optional[str] = None
    duplicateStatus: Optional[str] = None
    duplicateReasons: List[str] = Field(default_factory=list)
    duplicateScore: int = 0
    status: Optional[str] = None
    updatedAt: Optional[str] = None


class DuplicateGroup(BaseModel):
    groupId: str = ''
    reasonSummary: Optional[str] = None
    highestScore: int = 0
    products: List[DuplicateProductItem] = Field(default_factory=list)


class DuplicateGroupList(BaseModel):
    groups: List[DuplicateGroup] = Field(default_factory=list)
    total: int = 0


class DuplicateMarkMasterRequest(BaseModel):
    productId: str
    note: Optional[str] = None


class DuplicateHideRequest(BaseModel):
    masterProductId: str
    note: Optional[str] = None


class DuplicateActionRequest(BaseModel):
    note: Optional[str] = None


# ─── System health ────────────────────────────────────────────────────────────

class AdminImportLog(BaseModel):
    id: str = ''
    source: Optional[str] = None
    status: Optional[str] = None
    itemsImported: int = 0
    errors: int = 0
    createdAt: Optional[str] = None


class AdminSystemHealthResponse(BaseModel):
    systemErrors: List[AdminSystemError] = Field(default_factory=list)
    importLogs: List[AdminImportLog] = Field(default_factory=list)
    aiErrors: List[AdminAiQueryLog] = Field(default_factory=list)
    failedScrapings: List[AdminScrapeFailure] = Field(default_factory=list)


# ─── Audit logs ──────────────────────────────────────────────────────────────

class AdminLogEntry(BaseModel):
    id: str = ''
    adminUid: str = ''
    adminEmail: str = ''
    action: str = ''
    targetType: str = ''
    targetId: str = ''
    beforeStatus: Optional[str] = None
    afterStatus: Optional[str] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    createdAt: Optional[str] = None


class AdminLogList(BaseModel):
    logs: List[AdminLogEntry] = Field(default_factory=list)
    total: int = 0


# ─── Action request ──────────────────────────────────────────────────────────

class AdminActionRequest(BaseModel):
    reason: Optional[str] = None
    note: Optional[str] = None
    role: Optional[str] = None
