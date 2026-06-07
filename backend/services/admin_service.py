from typing import Any, Dict, Optional

from repositories.admin_repository import AdminRepository


class AdminService:
    def __init__(self) -> None:
        self.repo = AdminRepository()

    # ── original ──────────────────────────────────────────────────────────────

    def dashboard(self) -> Dict[str, Any]:
        return self.repo.dashboard()

    # ── overview ──────────────────────────────────────────────────────────────

    def overview(self) -> Dict[str, Any]:
        return self.repo.overview()

    # ── moderation: reels ─────────────────────────────────────────────────────

    def list_moderation_reels(self, status: str, limit: int) -> Dict[str, Any]:
        return self.repo.list_moderation_reels(status=status, limit=limit)

    def approve_reel(self, reel_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.approve_reel(reel_id, admin['uid'], admin.get('email', ''), reason)

    def reject_reel(self, reel_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.reject_reel(reel_id, admin['uid'], admin.get('email', ''), reason)

    def hide_reel(self, reel_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.hide_reel(reel_id, admin['uid'], admin.get('email', ''), reason)

    def restore_reel(self, reel_id: str, admin: dict) -> Dict[str, Any]:
        return self.repo.restore_reel(reel_id, admin['uid'], admin.get('email', ''))

    # ── moderation: marketplace ───────────────────────────────────────────────

    def list_moderation_marketplace(self, status: str, limit: int) -> Dict[str, Any]:
        return self.repo.list_moderation_marketplace(status=status, limit=limit)

    def approve_marketplace_item(self, item_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.approve_marketplace_item(item_id, admin['uid'], admin.get('email', ''), reason)

    def reject_marketplace_item(self, item_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.reject_marketplace_item(item_id, admin['uid'], admin.get('email', ''), reason)

    def hide_marketplace_item(self, item_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.hide_marketplace_item(item_id, admin['uid'], admin.get('email', ''), reason)

    def restore_marketplace_item(self, item_id: str, admin: dict) -> Dict[str, Any]:
        return self.repo.restore_marketplace_item(item_id, admin['uid'], admin.get('email', ''))

    # ── reports ───────────────────────────────────────────────────────────────

    def list_reports(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_reports(limit=limit)

    def resolve_report(self, report_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.update_report_status(report_id, 'resolved', admin['uid'], admin.get('email', ''), note)

    def dismiss_report(self, report_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.update_report_status(report_id, 'dismissed', admin['uid'], admin.get('email', ''), note)

    def add_report_note(self, report_id: str, admin: dict, note: str) -> Dict[str, Any]:
        return self.repo.update_report_status(report_id, 'reviewed', admin['uid'], admin.get('email', ''), note)

    # ── users ─────────────────────────────────────────────────────────────────

    def list_users(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_users(limit=limit)

    def get_user(self, uid: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_user(uid)

    def verify_user(self, uid: str, admin: dict) -> Dict[str, Any]:
        return self.repo.verify_user(uid, admin['uid'], admin.get('email', ''))

    def unverify_user(self, uid: str, admin: dict) -> Dict[str, Any]:
        return self.repo.unverify_user(uid, admin['uid'], admin.get('email', ''))

    def verify_seller(self, uid: str, admin: dict) -> Dict[str, Any]:
        return self.repo.verify_seller(uid, admin['uid'], admin.get('email', ''))

    def remove_seller_verification(self, uid: str, admin: dict) -> Dict[str, Any]:
        return self.repo.remove_seller_verification(uid, admin['uid'], admin.get('email', ''))

    def ban_user(self, uid: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.ban_user(uid, admin['uid'], admin.get('email', ''), reason)

    def unban_user(self, uid: str, admin: dict) -> Dict[str, Any]:
        return self.repo.unban_user(uid, admin['uid'], admin.get('email', ''))

    def change_user_role(self, uid: str, role: str, admin: dict) -> Dict[str, Any]:
        return self.repo.change_user_role(uid, role, admin['uid'], admin.get('email', ''))

    # ── product quality ───────────────────────────────────────────────────────

    def list_product_quality(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_product_quality(limit=limit)

    def hide_product(self, product_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.hide_product(product_id, admin['uid'], admin.get('email', ''), reason)

    def restore_product(self, product_id: str, admin: dict) -> Dict[str, Any]:
        return self.repo.restore_product(product_id, admin['uid'], admin.get('email', ''))

    def mark_product_review(self, product_id: str, admin: dict, reason: Optional[str]) -> Dict[str, Any]:
        return self.repo.mark_product_review(product_id, admin['uid'], admin.get('email', ''), reason)

    def mark_product_safe(self, product_id: str, admin: dict) -> Dict[str, Any]:
        return self.repo.mark_product_safe(product_id, admin['uid'], admin.get('email', ''))

    # ── duplicate review ──────────────────────────────────────────────────────

    def scan_product_duplicates(self, dry_run: bool, limit: int, write: bool) -> Dict[str, Any]:
        return self.repo.scan_product_duplicates(limit=limit, dry_run=dry_run, write=write)

    def list_product_duplicates(self, status: str, limit: int) -> Dict[str, Any]:
        return self.repo.list_product_duplicates(status=status, limit=limit)

    def mark_duplicate_master(self, group_id: str, product_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.mark_duplicate_master(group_id, product_id, admin['uid'], admin.get('email', ''), note)

    def hide_duplicate_product(self, product_id: str, master_product_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.hide_duplicate_product(product_id, master_product_id, admin['uid'], admin.get('email', ''), note)

    def dismiss_duplicate_product(self, product_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.dismiss_duplicate_product(product_id, admin['uid'], admin.get('email', ''), note)

    def restore_duplicate_product(self, product_id: str, admin: dict) -> Dict[str, Any]:
        return self.repo.restore_duplicate_product(product_id, admin['uid'], admin.get('email', ''))

    def refresh_product_quality(self, product_id: str) -> Dict[str, Any]:
        return self.repo.refresh_product_quality(product_id)

    def scan_products_quality(self, dry_run: bool, limit: int, write: bool) -> Dict[str, Any]:
        return self.repo.scan_products_quality(limit=limit, dry_run=dry_run, write=write)

    # ── import batches ────────────────────────────────────────────────────────

    def list_import_batches(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_import_batches(limit=limit)

    def get_import_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_import_batch(batch_id)

    def hide_import_batch_products(self, batch_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.hide_import_batch_products(batch_id, admin['uid'], admin.get('email', ''), note)

    def mark_import_batch_review(self, batch_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.mark_import_batch_review(batch_id, admin['uid'], admin.get('email', ''), note)

    def restore_import_batch_products(self, batch_id: str, admin: dict, note: Optional[str]) -> Dict[str, Any]:
        return self.repo.restore_import_batch_products(batch_id, admin['uid'], admin.get('email', ''), note)

    def list_source_trust(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_source_trust(limit=limit)

    # ── system health ─────────────────────────────────────────────────────────

    def system_health(self) -> Dict[str, Any]:
        return self.repo.system_health()

    # ── audit logs ────────────────────────────────────────────────────────────

    def list_admin_logs(self, limit: int) -> Dict[str, Any]:
        return self.repo.list_admin_logs(limit=limit)

    # ── public catalog governance ─────────────────────────────────────────────

    def catalog_public_preview(self, limit: int = 500) -> Dict[str, Any]:
        from services.public_catalog_policy import public_catalog_preview
        return public_catalog_preview(limit=limit)

    def update_catalog_config(self, updates: Dict[str, Any], admin: dict) -> Dict[str, Any]:
        from services.public_catalog_policy import update_catalog_config
        return update_catalog_config(updates, admin['uid'], admin.get('email', ''))


admin_service = AdminService()
