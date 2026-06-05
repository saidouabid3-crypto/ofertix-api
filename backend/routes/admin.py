from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_admin
from schemas.admin_schema import (
    AdminActionRequest,
    AdminDashboardResponse,
    AdminLogList,
    AdminModerationList,
    AdminOverviewResponse,
    AdminProductQualityList,
    AdminReportList,
    AdminSystemHealthResponse,
    AdminUserList,
    AdminUserView,
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


@router.post('/products/{product_id}/hide')
async def hide_product(product_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.hide_product(product_id, current_user, body.reason)


@router.post('/products/{product_id}/restore')
async def restore_product(product_id: str, current_user: dict = Depends(require_admin)):
    return admin_service.restore_product(product_id, current_user)


@router.post('/products/{product_id}/mark-review')
async def mark_product_review(product_id: str, body: AdminActionRequest = AdminActionRequest(), current_user: dict = Depends(require_admin)):
    return admin_service.mark_product_review(product_id, current_user, body.reason)


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
