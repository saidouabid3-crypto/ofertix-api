import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_admin
from schemas.admin_schema import (
    AdminActionRequest,
    AdminDashboardResponse,
    AdminImportBatchList,
    AdminImportBatchModel,
    AdminLogList,
    AdminModerationList,
    AdminOverviewResponse,
    AdminProductQualityList,
    AdminReportList,
    AdminSourceTrustList,
    AdminSystemHealthResponse,
    AdminUserList,
    AdminUserView,
    CatalogConfigUpdateRequest,
    DuplicateActionRequest,
    DuplicateGroupList,
    DuplicateHideRequest,
    DuplicateMarkMasterRequest,
    DuplicateScanRequest,
    DuplicateScanSummary,
    ImportBatchActionRequest,
    ProductTrustScanRequest,
    ProductTrustScanSummary,
)
from services.admin_service import admin_service

router = APIRouter(prefix='/admin', tags=['Admin'])


# ─── original dashboard (preserved for backward compat) ──────────────────────

@router.get('/dashboard', response_model=AdminDashboardResponse)
def dashboard(current_user: dict = Depends(require_admin)):
    return admin_service.dashboard()


# ─── overview ─────────────────────────────────────────────────────────────────

@router.get('/overview', response_model=AdminOverviewResponse)
async def overview(current_user: dict = Depends(require_admin)):
    return admin_service.overview()


# ─── moderation: reels ────────────────────────────────────────────────────────

@router.get('/moderation/reels', response_model=AdminModerationList)
async def list_moderation_reels(
    status: str = Query(default='pending'),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_moderation_reels(status=status, limit=limit)


@router.post('/moderation/reels/{reel_id}/approve')
async def approve_reel(reel_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.approve_reel(reel_id, current_user, body.reason)


@router.post('/moderation/reels/{reel_id}/reject')
async def reject_reel(reel_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.reject_reel(reel_id, current_user, body.reason)


@router.post('/moderation/reels/{reel_id}/hide')
async def hide_reel(reel_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.hide_reel(reel_id, current_user, body.reason)


@router.post('/moderation/reels/{reel_id}/restore')
async def restore_reel(reel_id: str, current_user: dict = Depends(require_admin)):
    return admin_service.restore_reel(reel_id, current_user)


# ─── moderation: marketplace ──────────────────────────────────────────────────

@router.get('/moderation/marketplace', response_model=AdminModerationList)
async def list_moderation_marketplace(
    status: str = Query(default='pending'),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_moderation_marketplace(status=status, limit=limit)


@router.post('/moderation/marketplace/{item_id}/approve')
async def approve_marketplace_item(item_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.approve_marketplace_item(item_id, current_user, body.reason)


@router.post('/moderation/marketplace/{item_id}/reject')
async def reject_marketplace_item(item_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.reject_marketplace_item(item_id, current_user, body.reason)


@router.post('/moderation/marketplace/{item_id}/hide')
async def hide_marketplace_item(item_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.hide_marketplace_item(item_id, current_user, body.reason)


@router.post('/moderation/marketplace/{item_id}/restore')
async def restore_marketplace_item(item_id: str, current_user: dict = Depends(require_admin)):
    return admin_service.restore_marketplace_item(item_id, current_user)


# ─── reports ──────────────────────────────────────────────────────────────────

@router.get('/reports', response_model=AdminReportList)
async def list_reports(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_reports(limit=limit)


@router.post('/reports/{report_id}/resolve')
async def resolve_report(report_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.resolve_report(report_id, current_user, body.note)


@router.post('/reports/{report_id}/dismiss')
async def dismiss_report(report_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.dismiss_report(report_id, current_user, body.note)


@router.post('/reports/{report_id}/note')
async def add_report_note(report_id: str, body: AdminActionRequest, current_user: dict = Depends(require_admin)):
    note = body.note or ''
    if not note.strip():
        raise HTTPException(status_code=400, detail='Note is required')
    return admin_service.add_report_note(report_id, current_user, note)


# ─── users ────────────────────────────────────────────────────────────────────

@router.get('/users', response_model=AdminUserList)
async def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_users(limit=limit)


@router.get('/users/{uid}', response_model=AdminUserView)
async def get_user(uid: str, current_user: dict = Depends(require_admin)):
    user = admin_service.get_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    return user


@router.post('/users/{uid}/verify')
async def verify_user(uid: str, current_user: dict = Depends(require_admin)):
    return admin_service.verify_user(uid, current_user)


@router.post('/users/{uid}/unverify')
async def unverify_user(uid: str, current_user: dict = Depends(require_admin)):
    return admin_service.unverify_user(uid, current_user)


@router.post('/users/{uid}/verify-seller')
async def verify_seller(uid: str, current_user: dict = Depends(require_admin)):
    return admin_service.verify_seller(uid, current_user)


@router.post('/users/{uid}/remove-seller-verification')
async def remove_seller_verification(uid: str, current_user: dict = Depends(require_admin)):
    return admin_service.remove_seller_verification(uid, current_user)


@router.post('/users/{uid}/ban')
async def ban_user(uid: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.ban_user(uid, current_user, body.reason)


@router.post('/users/{uid}/unban')
async def unban_user(uid: str, current_user: dict = Depends(require_admin)):
    return admin_service.unban_user(uid, current_user)


@router.post('/users/{uid}/role')
async def change_user_role(uid: str, body: AdminActionRequest, current_user: dict = Depends(require_admin)):
    if not body.role:
        raise HTTPException(status_code=400, detail='role is required')
    result = admin_service.change_user_role(uid, body.role, current_user)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Invalid role'))
    return result


# ─── product quality ──────────────────────────────────────────────────────────

@router.get('/products/quality', response_model=AdminProductQualityList)
async def list_product_quality(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_product_quality(limit=limit)


@router.post('/products/quality/scan', response_model=ProductTrustScanSummary)
async def scan_products_quality(
    body: ProductTrustScanRequest = ProductTrustScanRequest(),
    current_user: dict = Depends(require_admin),
):
    return admin_service.scan_products_quality(
        dry_run=body.dryRun,
        limit=body.limit,
        write=body.write,
    )


@router.get('/products/duplicates', response_model=DuplicateGroupList)
async def list_product_duplicates(
    status: str = Query(default='candidate'),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_product_duplicates(status=status, limit=limit)


@router.post('/products/duplicates/scan', response_model=DuplicateScanSummary)
async def scan_product_duplicates(
    body: DuplicateScanRequest = DuplicateScanRequest(),
    current_user: dict = Depends(require_admin),
):
    return admin_service.scan_product_duplicates(dry_run=body.dryRun, limit=body.limit, write=body.write)


@router.post('/products/duplicates/{group_id}/mark-master')
async def mark_duplicate_master(
    group_id: str,
    body: DuplicateMarkMasterRequest,
    current_user: dict = Depends(require_admin),
):
    if not body.productId:
        raise HTTPException(status_code=400, detail='productId is required')
    result = admin_service.mark_duplicate_master(group_id, body.productId, current_user, body.note)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed'))
    return result


@router.post('/products/{product_id}/duplicates/hide')
async def hide_duplicate_product(
    product_id: str,
    body: DuplicateHideRequest,
    current_user: dict = Depends(require_admin),
):
    result = admin_service.hide_duplicate_product(product_id, body.masterProductId, current_user, body.note)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed'))
    return result


@router.post('/products/{product_id}/duplicates/dismiss')
async def dismiss_duplicate_product(
    product_id: str,
    body: DuplicateActionRequest = DuplicateActionRequest(),
    current_user: dict = Depends(require_admin),
):
    result = admin_service.dismiss_duplicate_product(product_id, current_user, body.note)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed'))
    return result


@router.post('/products/{product_id}/duplicates/restore')
async def restore_duplicate_product(product_id: str, current_user: dict = Depends(require_admin)):
    result = admin_service.restore_duplicate_product(product_id, current_user)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error', 'Failed'))
    return result


@router.post('/products/{product_id}/quality/refresh')
async def refresh_product_quality(product_id: str, current_user: dict = Depends(require_admin)):
    result = admin_service.refresh_product_quality(product_id)
    if not result.get('ok'):
        raise HTTPException(status_code=404, detail=result.get('error', 'Product not found'))
    return result


@router.post('/products/{product_id}/mark-safe')
async def mark_product_safe(product_id: str, current_user: dict = Depends(require_admin)):
    return admin_service.mark_product_safe(product_id, current_user)


@router.post('/products/{product_id}/hide')
async def hide_product(product_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.hide_product(product_id, current_user, body.reason)


@router.post('/products/{product_id}/restore')
async def restore_product(product_id: str, current_user: dict = Depends(require_admin)):
    return admin_service.restore_product(product_id, current_user)


@router.post('/products/{product_id}/mark-review')
async def mark_product_review(product_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.mark_product_review(product_id, current_user, body.reason)


# ─── import batches ───────────────────────────────────────────────────────────

@router.get('/imports/batches', response_model=AdminImportBatchList)
async def list_import_batches(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_import_batches(limit=limit)


@router.get('/imports/batches/{batch_id}', response_model=AdminImportBatchModel)
async def get_import_batch(batch_id: str, current_user: dict = Depends(require_admin)):
    batch = admin_service.get_import_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail='Import batch not found')
    return batch


@router.post('/imports/batches/{batch_id}/hide-products')
async def hide_import_batch_products(
    batch_id: str,
    body: ImportBatchActionRequest = ImportBatchActionRequest(),
    current_user: dict = Depends(require_admin),
):
    return admin_service.hide_import_batch_products(batch_id, current_user, body.note)


@router.post('/imports/batches/{batch_id}/mark-review')
async def mark_import_batch_review(
    batch_id: str,
    body: ImportBatchActionRequest = ImportBatchActionRequest(),
    current_user: dict = Depends(require_admin),
):
    return admin_service.mark_import_batch_review(batch_id, current_user, body.note)


@router.post('/imports/batches/{batch_id}/restore-products')
async def restore_import_batch_products(
    batch_id: str,
    body: ImportBatchActionRequest = ImportBatchActionRequest(),
    current_user: dict = Depends(require_admin),
):
    return admin_service.restore_import_batch_products(batch_id, current_user, body.note)


@router.get('/imports/source-trust', response_model=AdminSourceTrustList)
async def list_source_trust(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_source_trust(limit=limit)


# ─── system health ────────────────────────────────────────────────────────────

@router.get('/system-health', response_model=AdminSystemHealthResponse)
async def system_health(current_user: dict = Depends(require_admin)):
    return admin_service.system_health()


# ─── audit logs ───────────────────────────────────────────────────────────────

@router.get('/logs', response_model=AdminLogList)
async def list_admin_logs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
):
    return admin_service.list_admin_logs(limit=limit)


# ─── public catalog governance ────────────────────────────────────────────────

@router.get('/catalog/public-preview')
async def catalog_public_preview(
    limit: int = Query(default=500, ge=10, le=2000),
    current_user: dict = Depends(require_admin),
):
    """
    Dry-run: returns what the current catalog config would show/hide.
    Does NOT write to Firestore or modify any product.
    """
    return await asyncio.to_thread(admin_service.catalog_public_preview, limit)


@router.patch('/catalog/public-config')
async def update_catalog_public_config(
    body: CatalogConfigUpdateRequest,
    current_user: dict = Depends(require_admin),
):
    """
    Update app_config/catalog_governance fields.
    Only known boolean keys are accepted; unknown keys are silently ignored.
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return await asyncio.to_thread(admin_service.update_catalog_config, updates, current_user)
