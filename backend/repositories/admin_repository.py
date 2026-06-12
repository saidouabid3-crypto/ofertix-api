from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.firebase import db
from repositories.marketplace_repository import is_public_marketplace_item
from utils.country_intelligence import GLOBAL_CODES, enrich_country_fields, normalize_country


COUNTRY_ALIASES = {
    'amazon es': 'es', 'amazon.es': 'es', 'amazones': 'es', 'es amazon': 'es',
    'amazon france': 'fr', 'amazon fr': 'fr', 'amazon.fr': 'fr',
    'amazon de': 'de', 'amazon.de': 'de',
    'amazon it': 'it', 'amazon.it': 'it',
    'amazon uk': 'uk', 'amazon.co.uk': 'uk',
    'amazon us': 'us', 'amazon.com': 'us',
    'amazon ca': 'ca', 'amazon.ca': 'ca',
    'jumia ma': 'ma', 'jumia morocco': 'ma', 'jumia maroc': 'ma',
    'jumia dz': 'dz', 'jumia algeria': 'dz', 'jumia eg': 'eg',
    'noon ae': 'ae', 'noon uae': 'ae', 'noon sa': 'sa', 'noon egypt': 'eg',
    'carrefour es': 'es', 'mediamarkt es': 'es', 'pccomponentes': 'es',
    'walmart ca': 'ca', 'bestbuy ca': 'ca', 'walmart us': 'us', 'bestbuy us': 'us',
    'mercado libre mx': 'mx', 'mercadolibre mx': 'mx',
}

_REPORT_COLLECTIONS = ['reel_reports', 'item_reports', 'marketplace_reports', 'product_reports']


def _safe_aggregate_count(collection: str, fallback_limit: int = 2000) -> int:
    try:
        query = db.collection(collection).count()
        result = query.get()
        if result and result[0]:
            value = getattr(result[0], 'value', None)
            if isinstance(value, int):
                return value
            data = result[0][0].value if isinstance(result[0], list) else None
            if isinstance(data, int):
                return data
    except Exception:
        pass

    try:
        return sum(1 for _ in db.collection(collection).limit(fallback_limit).stream())
    except Exception:
        return 0


def _safe_count_where(collection: str, field: str, value: Any, limit: int = 2000) -> int:
    try:
        return sum(
            1 for _ in db.collection(collection).where(field, '==', value).limit(limit).stream()
        )
    except Exception:
        return 0


def _safe_sum(collection: str, field: str, limit: int = 500) -> float:
    total = 0.0
    try:
        for doc in db.collection(collection).limit(limit).stream():
            data = doc.to_dict() or {}
            value = data.get(field, 0) or 0
            if isinstance(value, (int, float)):
                total += float(value)
    except Exception:
        return 0.0
    return total


def _infer_country_from_source(data: Dict[str, Any]) -> str:
    explicit = normalize_country(
        data.get('countryCode')
        or data.get('country_code')
        or data.get('storeCountry')
        or data.get('country')
        or ''
    )
    if explicit and explicit not in GLOBAL_CODES:
        return explicit

    haystack = ' '.join(
        str(data.get(key, '') or '').lower()
        for key in ['source', 'store', 'provider', 'affiliateUrl', 'url', 'productUrl', 'marketplace']
    )

    for marker, country in COUNTRY_ALIASES.items():
        if marker in haystack:
            return country

    return 'global'


def _clean_top_product(doc_id: str, data: Dict[str, Any]) -> Dict[str, Any] | None:
    enriched = enrich_country_fields(data)
    country = _infer_country_from_source(enriched)
    if country in GLOBAL_CODES:
        return None

    price = _to_float(
        enriched.get('price')
        or enriched.get('currentPrice')
        or enriched.get('current_price')
        or enriched.get('salePrice')
        or 0
    )

    title = enriched.get('name') or enriched.get('title') or enriched.get('productName') or 'Product'
    store = enriched.get('store') or enriched.get('source') or enriched.get('provider') or ''
    clicks = int(enriched.get('clicks') or enriched.get('clickCount') or 0)
    revenue = _to_float(enriched.get('revenue') or enriched.get('commission') or enriched.get('estimatedRevenue') or 0)

    if not str(title).strip():
        return None

    return {
        'id': doc_id,
        'name': str(title).strip(),
        'store': str(store).strip(),
        'clicks': clicks,
        'revenue': revenue,
        'countryCode': country,
        'price': price,
    }


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value or '0').replace(',', '.'))
    except Exception:
        return 0.0


def _ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AdminRepository:
    # ─────────────────────── original dashboard ──────────────────────────────

    def dashboard(self) -> Dict[str, Any]:
        total_users = _safe_aggregate_count('users')
        total_products = _safe_aggregate_count('products')
        total_reels = _safe_aggregate_count('smart_reels')
        total_marketplace = _safe_aggregate_count('marketplace_items')
        open_reports = _safe_aggregate_count('item_reports') + _safe_aggregate_count('smart_reel_reports')

        total_clicks = int(
            _safe_sum('products', 'clicks')
            + _safe_sum('smart_reels', 'clicks')
            + _safe_sum('affiliate_clicks', 'count')
        )
        total_orders = int(_safe_aggregate_count('orders') + _safe_aggregate_count('cashback_transactions'))
        revenue = float(
            _safe_sum('orders', 'commission')
            + _safe_sum('cashback_transactions', 'revenue')
            + _safe_sum('ad_events', 'estimatedRevenue')
        )

        return {
            'live': True,
            'totalUsers': total_users,
            'totalClicks': total_clicks,
            'totalOrders': total_orders,
            'revenue': round(revenue, 2),
            'totalProducts': total_products,
            'totalReels': total_reels,
            'totalMarketplaceItems': total_marketplace,
            'openReports': open_reports,
            'topSearches': self.top_searches(),
            'topProducts': self.top_products(),
            'connectors': self.connector_status(),
            'recentAiQueries': self.recent_ai_queries(),
            'failedScrapings': self.failed_scrapings(),
            'flaggedProducts': self.flagged_products(),
            'pendingLocalReviews': self.pending_local_reviews(),
            'systemErrors': self.system_errors(),
        }

    def recent_ai_queries(self, limit: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            docs = (
                db.collection('ai_usage_logs')
                .order_by('createdAt', direction='DESCENDING')
                .limit(limit)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict() or {}
                items.append(
                    {
                        'id': doc.id,
                        'subject': data.get('subject'),
                        'uid': data.get('uid'),
                        'count': data.get('count'),
                        'blocked': data.get('blocked') is True,
                        'createdAt': _ts(data.get('createdAt')),
                    }
                )
        except Exception:
            pass
        return items

    def failed_scrapings(self, limit: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            docs = db.collection('scrape_failures').order_by('createdAt', direction='DESCENDING').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                items.append(
                    {
                        'id': doc.id,
                        'url': data.get('url'),
                        'source': data.get('source'),
                        'error': data.get('error'),
                        'createdAt': _ts(data.get('createdAt')),
                    }
                )
        except Exception:
            try:
                for doc in db.collection('api_connectors').limit(limit).stream():
                    data = doc.to_dict() or {}
                    if data.get('lastStatus') not in {None, '', 'ok', 'success'}:
                        items.append(
                            {
                                'id': doc.id,
                                'url': data.get('source') or doc.id,
                                'source': data.get('source') or doc.id,
                                'error': data.get('lastError') or data.get('lastStatus'),
                                'createdAt': _ts(data.get('lastSyncAt')),
                            }
                        )
            except Exception:
                pass
        return items

    def flagged_products(self, limit: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            docs = db.collection('products').where('status', '==', 'needs_market_review').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                items.append(
                    {
                        'id': doc.id,
                        'name': data.get('name') or data.get('title'),
                        'store': data.get('store'),
                        'adminIssue': data.get('adminIssue'),
                        'countryCode': data.get('countryCode'),
                    }
                )
        except Exception:
            pass
        return items

    def pending_local_reviews(self, limit: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            docs = db.collection('local_offers').where('status', '==', 'pending').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                items.append(
                    {
                        'id': doc.id,
                        'title': data.get('title') or data.get('name'),
                        'storeId': data.get('storeId'),
                        'merchantId': data.get('merchantId'),
                        'countryCode': data.get('countryCode'),
                        'createdAt': _ts(data.get('createdAt')),
                    }
                )
        except Exception:
            pass
        return items

    def system_errors(self, limit: int = 25) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            docs = db.collection('system_errors').order_by('createdAt', direction='DESCENDING').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                items.append(
                    {
                        'id': doc.id,
                        'path': data.get('path'),
                        'message': data.get('message') or data.get('error'),
                        'createdAt': _ts(data.get('createdAt')),
                    }
                )
        except Exception:
            pass
        return items

    def top_searches(self, limit: int = 8) -> List[str]:
        try:
            docs = (
                db.collection('search_analytics')
                .order_by('count', direction='DESCENDING')
                .limit(limit)
                .stream()
            )
            items = []
            for doc in docs:
                data = doc.to_dict() or {}
                query = data.get('query') or data.get('term') or doc.id
                if query:
                    items.append(str(query))
            return items
        except Exception:
            return []

    def top_products(self, limit: int = 6) -> List[Dict[str, Any]]:
        try:
            try:
                docs = (
                    db.collection('products')
                    .order_by('clicks', direction='DESCENDING')
                    .limit(limit * 4)
                    .stream()
                )
            except Exception:
                docs = db.collection('products').limit(limit * 4).stream()

            items: List[Dict[str, Any]] = []
            for doc in docs:
                cleaned = _clean_top_product(doc.id, doc.to_dict() or {})
                if cleaned is not None:
                    items.append(cleaned)
                if len(items) >= limit:
                    break
            return items
        except Exception:
            return []

    def connector_status(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            docs = db.collection('api_connectors').limit(limit).stream()
            items = []
            for doc in docs:
                data = doc.to_dict() or {}
                country = normalize_country(data.get('countryCode') or data.get('country') or 'global')
                items.append({
                    'source': data.get('source') or data.get('name') or doc.id,
                    'countryCode': country,
                    'enabled': bool(data.get('enabled', False)),
                    'lastSyncAt': str(data.get('lastSyncAt') or '') or None,
                    'lastStatus': data.get('lastStatus') or data.get('status') or 'not_configured',
                    'lastError': data.get('lastError') or '',
                })
            return items
        except Exception:
            return []

    # ─────────────────────── overview ────────────────────────────────────────

    def overview(self) -> Dict[str, Any]:
        total_users = _safe_aggregate_count('users')
        total_reels = _safe_aggregate_count('smart_reels')
        pending_reels = _safe_count_where('smart_reels', 'status', 'pending')
        hidden_reels = _safe_count_where('smart_reels', 'status', 'hidden')
        rejected_reels = _safe_count_where('smart_reels', 'status', 'rejected')
        reported_reels = _safe_aggregate_count('reel_reports')
        total_sell = _safe_aggregate_count('marketplace_items')
        pending_sell = _safe_count_where('marketplace_items', 'status', 'pending')
        reported_sell = _safe_aggregate_count('item_reports')
        total_reports = sum(_safe_aggregate_count(c) for c in _REPORT_COLLECTIONS)
        open_reports = _safe_count_where('reel_reports', 'status', 'open') + _safe_count_where('item_reports', 'status', 'open')
        system_errors = _safe_aggregate_count('system_errors')
        ai_errors = _safe_count_where('ai_usage_logs', 'blocked', True)
        failed_uploads = _safe_aggregate_count('scrape_failures')
        total_products = _safe_aggregate_count('products')

        return {
            'totalUsers': total_users,
            'totalReels': total_reels,
            'pendingReels': pending_reels,
            'reportedReels': reported_reels,
            'hiddenReels': hidden_reels,
            'rejectedReels': rejected_reels,
            'totalSellItems': total_sell,
            'pendingSellItems': pending_sell,
            'reportedSellItems': reported_sell,
            'totalReports': total_reports,
            'openReports': open_reports,
            'systemErrors': system_errors,
            'aiErrors': ai_errors,
            'failedUploads': failed_uploads,
            'totalProducts': total_products,
        }

    # ─────────────────────── moderation: reels ───────────────────────────────

    def list_moderation_reels(self, status: str = 'pending', limit: int = 50) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        try:
            query = db.collection('smart_reels').where('status', '==', status).limit(limit)
            for doc in query.stream():
                data = doc.to_dict() or {}
                reel_id = data.get('id') or doc.id
                reports_count = 0
                try:
                    reports_count = sum(1 for _ in db.collection('reel_reports').where('reelId', '==', reel_id).limit(50).stream())
                except Exception:
                    pass
                items.append({
                    'id': reel_id,
                    'title': data.get('title'),
                    'description': data.get('description'),
                    'status': data.get('status', 'approved'),
                    'creatorId': data.get('creator_id'),
                    'creatorName': data.get('creator_name'),
                    'creatorUsername': data.get('creator_username') or '',
                    'creatorAvatarUrl': data.get('creator_avatar_url'),
                    'thumbnailUrl': data.get('thumbnail_url'),
                    'videoUrl': data.get('video_mp4_url'),
                    'price': _to_float(data.get('current_price')),
                    'currency': data.get('currency'),
                    'store': data.get('store'),
                    'reportsCount': reports_count,
                    'createdAt': _ts(data.get('created_at') or data.get('createdAt')),
                    'itemType': 'reel',
                })
        except Exception:
            pass
        return {'items': items, 'total': len(items)}

    def _moderate_reel(
        self,
        reel_id: str,
        new_status: str,
        admin_uid: str,
        admin_email: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        ref = db.collection('smart_reels').document(reel_id)
        doc = ref.get()
        before_status = None
        if doc.exists:
            before_status = (doc.to_dict() or {}).get('status')
        ref.update({'status': new_status, 'updatedAt': _now_iso(), 'adminModeratedAt': _now_iso()})
        self._write_admin_log(
            action=f'reel_{new_status}',
            target_type='reel',
            target_id=reel_id,
            admin_uid=admin_uid,
            admin_email=admin_email,
            before_status=before_status,
            after_status=new_status,
            reason=reason,
        )
        return {'ok': True, 'id': reel_id, 'status': new_status}

    def approve_reel(self, reel_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_reel(reel_id, 'approved', admin_uid, admin_email, reason)

    def reject_reel(self, reel_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_reel(reel_id, 'rejected', admin_uid, admin_email, reason)

    def hide_reel(self, reel_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_reel(reel_id, 'hidden', admin_uid, admin_email, reason)

    def restore_reel(self, reel_id: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._moderate_reel(reel_id, 'approved', admin_uid, admin_email)

    # ─────────────────────── moderation: marketplace ─────────────────────────

    def list_moderation_marketplace(self, status: str = 'pending', limit: int = 50) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        try:
            query = db.collection('marketplace_items').where('status', '==', status).limit(limit)
            for doc in query.stream():
                data = doc.to_dict() or {}
                item_id = doc.id
                reports_count = 0
                try:
                    reports_count = sum(
                        1 for _ in db.collection('item_reports').where('itemId', '==', item_id).limit(50).stream()
                    )
                except Exception:
                    pass
                price_raw = data.get('price') or data.get('currentPrice') or data.get('salePrice')
                items.append({
                    'id': item_id,
                    'title': data.get('title') or data.get('name'),
                    'description': data.get('description'),
                    'status': data.get('status', 'active'),
                    'creatorId': data.get('sellerId') or data.get('userId') or data.get('creatorId'),
                    'creatorName': data.get('sellerName'),
                    'creatorUsername': data.get('sellerUsername') or '',
                    'creatorAvatarUrl': data.get('sellerAvatarUrl'),
                    'imageUrl': (data.get('images') or [''])[0] if isinstance(data.get('images'), list) else data.get('imageUrl'),
                    'price': _to_float(price_raw) if price_raw is not None else None,
                    'currency': data.get('currency'),
                    'store': data.get('store') or data.get('category'),
                    'category': data.get('category'),
                    'reportsCount': reports_count,
                    'createdAt': _ts(data.get('createdAt')),
                    'itemType': 'marketplace',
                })
        except Exception:
            pass
        return {'items': items, 'total': len(items)}

    def _moderate_marketplace(
        self,
        item_id: str,
        new_status: str,
        admin_uid: str,
        admin_email: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        ref = db.collection('marketplace_items').document(item_id)
        doc = ref.get()
        doc_data = doc.to_dict() or {} if doc.exists else {}
        before_status = doc_data.get('status')
        seller_id = (
            doc_data.get('sellerId')
            or doc_data.get('userId')
            or doc_data.get('ownerId')
            or ''
        )
        is_public = new_status in {'active', 'approved', 'published'}
        now = _now_iso()
        update: Dict[str, Any] = {
            'status': new_status,
            'isActive': is_public,
            'visibleToUsers': is_public,
            'updatedAt': now,
            'adminModeratedAt': now,
        }
        if is_public:
            update['approvedAt'] = now
            update['approvedBy'] = admin_uid
            update['rejectionReason'] = None
        elif new_status == 'rejected':
            update['rejectedAt'] = now
            update['rejectedBy'] = admin_uid
            if reason:
                update['rejectionReason'] = reason
        ref.update(update)
        self._write_admin_log(
            action=f'marketplace_{new_status}',
            target_type='marketplace_item',
            target_id=item_id,
            admin_uid=admin_uid,
            admin_email=admin_email,
            before_status=before_status,
            after_status=new_status,
            reason=reason,
        )
        self._sync_seller_sell_count(seller_id)
        return {'ok': True, 'id': item_id, 'status': new_status}

    def _sync_seller_sell_count(self, seller_id: str) -> None:
        """Recount and persist seller's public sell_items_count after any moderation action."""
        if not seller_id:
            return
        try:
            count = 0
            docs = (
                db.collection('marketplace_items')
                .where('sellerId', '==', seller_id)
                .limit(200)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict() or {}
                if is_public_marketplace_item(data):
                    count += 1
            db.collection('users').document(seller_id).set(
                {'sell_items_count': count, 'updated_at': _now_iso()},
                merge=True,
            )
        except Exception:
            pass

    def approve_marketplace_item(self, item_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_marketplace(item_id, 'approved', admin_uid, admin_email, reason)

    def reject_marketplace_item(self, item_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_marketplace(item_id, 'rejected', admin_uid, admin_email, reason)

    def hide_marketplace_item(self, item_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_marketplace(item_id, 'hidden', admin_uid, admin_email, reason)

    def restore_marketplace_item(self, item_id: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._moderate_marketplace(item_id, 'approved', admin_uid, admin_email)

    # ─────────────────────── reports center ──────────────────────────────────

    def list_reports(self, limit: int = 50) -> Dict[str, Any]:
        reports: List[Dict[str, Any]] = []
        per_coll = max(1, limit // len(_REPORT_COLLECTIONS))
        collection_types = {
            'reel_reports': 'reel_report',
            'item_reports': 'marketplace_report',
            'marketplace_reports': 'marketplace_report',
            'product_reports': 'product_report',
        }
        for coll_name in _REPORT_COLLECTIONS:
            try:
                docs = db.collection(coll_name).limit(per_coll).stream()
                for doc in docs:
                    data = doc.to_dict() or {}
                    reports.append({
                        'id': doc.id,
                        'reportType': collection_types.get(coll_name, coll_name),
                        'targetId': data.get('reelId') or data.get('itemId') or data.get('productId') or data.get('targetId'),
                        'targetTitle': data.get('reelTitle') or data.get('itemTitle') or data.get('productName') or data.get('targetTitle'),
                        'reporterId': data.get('reporterId') or data.get('userId') or data.get('uid'),
                        'reporterName': data.get('reporterName') or data.get('userName'),
                        'reason': data.get('reason'),
                        'status': data.get('status') or 'open',
                        'adminNote': data.get('adminNote') or data.get('note'),
                        'createdAt': _ts(data.get('createdAt')),
                        'updatedAt': _ts(data.get('updatedAt')),
                    })
            except Exception:
                pass
        reports.sort(key=lambda r: r.get('createdAt') or '', reverse=True)
        reports = reports[:limit]
        return {'reports': reports, 'total': len(reports)}

    def _resolve_report_collection(self, report_id: str) -> Optional[str]:
        for coll in _REPORT_COLLECTIONS:
            try:
                doc = db.collection(coll).document(report_id).get()
                if doc.exists:
                    return coll
            except Exception:
                pass
        return None

    def update_report_status(
        self,
        report_id: str,
        new_status: str,
        admin_uid: str,
        admin_email: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        coll = self._resolve_report_collection(report_id)
        if not coll:
            return {'ok': False, 'error': 'Report not found'}
        update: Dict[str, Any] = {'status': new_status, 'updatedAt': _now_iso()}
        if note:
            update['adminNote'] = note
        db.collection(coll).document(report_id).update(update)
        self._write_admin_log(
            action=f'report_{new_status}',
            target_type='report',
            target_id=report_id,
            admin_uid=admin_uid,
            admin_email=admin_email,
            after_status=new_status,
            note=note,
        )
        return {'ok': True, 'id': report_id, 'status': new_status}

    # ─────────────────────── user management ─────────────────────────────────

    def list_users(self, limit: int = 50) -> Dict[str, Any]:
        users: List[Dict[str, Any]] = []
        try:
            docs = db.collection('users').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                role = str(data.get('role') or data.get('userRole') or 'user').lower()
                users.append({
                    'uid': doc.id,
                    'email': data.get('email') or '',
                    'displayName': data.get('displayName') or data.get('display_name') or '',
                    'username': data.get('username') or '',
                    'photoUrl': data.get('photoUrl') or data.get('photo_url') or data.get('avatarUrl') or '',
                    'role': role,
                    'isAdmin': bool(data.get('isAdmin') or data.get('admin') or role in {'admin', 'owner', 'super_admin'}),
                    'isVerified': bool(data.get('isVerified') or data.get('is_verified')),
                    'sellerVerified': bool(data.get('sellerVerified') or data.get('seller_verified')),
                    'isBanned': bool(data.get('isBanned') or data.get('banned')),
                    'reportsCount': int(data.get('reportsCount') or 0),
                    'reelsCount': int(data.get('reelsCount') or 0),
                    'sellItemsCount': int(data.get('sellItemsCount') or 0),
                    'followersCount': int(data.get('followersCount') or 0),
                    'createdAt': _ts(data.get('createdAt')),
                })
        except Exception:
            pass
        return {'users': users, 'total': len(users)}

    def get_user(self, uid: str) -> Optional[Dict[str, Any]]:
        try:
            doc = db.collection('users').document(uid).get()
            if not doc.exists:
                return None
            data = doc.to_dict() or {}
            role = str(data.get('role') or data.get('userRole') or 'user').lower()
            return {
                'uid': doc.id,
                'email': data.get('email') or '',
                'displayName': data.get('displayName') or data.get('display_name') or '',
                'username': data.get('username') or '',
                'photoUrl': data.get('photoUrl') or data.get('photo_url') or data.get('avatarUrl') or '',
                'role': role,
                'isAdmin': bool(data.get('isAdmin') or data.get('admin') or role in {'admin', 'owner', 'super_admin'}),
                'isVerified': bool(data.get('isVerified') or data.get('is_verified')),
                'sellerVerified': bool(data.get('sellerVerified') or data.get('seller_verified')),
                'isBanned': bool(data.get('isBanned') or data.get('banned')),
                'reportsCount': int(data.get('reportsCount') or 0),
                'reelsCount': int(data.get('reelsCount') or 0),
                'sellItemsCount': int(data.get('sellItemsCount') or 0),
                'followersCount': int(data.get('followersCount') or 0),
                'createdAt': _ts(data.get('createdAt')),
            }
        except Exception:
            return None

    def _update_user_field(
        self,
        uid: str,
        updates: Dict[str, Any],
        action: str,
        admin_uid: str,
        admin_email: str,
        reason: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        ref = db.collection('users').document(uid)
        updates['updatedAt'] = _now_iso()
        ref.set(updates, merge=True)
        self._write_admin_log(
            action=action,
            target_type='user',
            target_id=uid,
            admin_uid=admin_uid,
            admin_email=admin_email,
            reason=reason,
            note=note,
        )
        return {'ok': True, 'uid': uid}

    def verify_user(self, uid: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._update_user_field(uid, {'isVerified': True, 'is_verified': True}, 'user_verify', admin_uid, admin_email)

    def unverify_user(self, uid: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._update_user_field(uid, {'isVerified': False, 'is_verified': False}, 'user_unverify', admin_uid, admin_email)

    def verify_seller(self, uid: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._update_user_field(uid, {'sellerVerified': True, 'seller_verified': True}, 'seller_verify', admin_uid, admin_email)

    def remove_seller_verification(self, uid: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._update_user_field(uid, {'sellerVerified': False, 'seller_verified': False}, 'seller_unverify', admin_uid, admin_email)

    def ban_user(self, uid: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._update_user_field(uid, {'isBanned': True, 'banned': True, 'banReason': reason}, 'user_ban', admin_uid, admin_email, reason=reason)

    def unban_user(self, uid: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._update_user_field(uid, {'isBanned': False, 'banned': False}, 'user_unban', admin_uid, admin_email)

    def change_user_role(self, uid: str, role: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        safe_roles = {'user', 'creator', 'seller', 'merchant'}
        if role not in safe_roles:
            return {'ok': False, 'error': f'Role must be one of: {", ".join(safe_roles)}'}
        return self._update_user_field(uid, {'role': role, 'userRole': role}, f'user_role_{role}', admin_uid, admin_email)

    # ─────────────────────── product quality ─────────────────────────────────

    def list_product_quality(self, limit: int = 50) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []

        def _add(data: Dict[str, Any], doc_id: str, issue: str) -> None:
            name = data.get('name') or data.get('title') or data.get('productName')
            items.append({
                'id': doc_id,
                'name': name,
                'store': data.get('store') or data.get('source'),
                'price': _to_float(data.get('price') or data.get('currentPrice') or 0),
                'imageUrl': data.get('imageUrl') or data.get('image') or data.get('thumbnail'),
                'affiliateUrl': data.get('affiliateUrl') or data.get('productUrl') or data.get('url'),
                'status': data.get('status'),
                'issue': issue,
                'countryCode': data.get('countryCode'),
                'qualityScore': data.get('qualityScore'),
                'trustStatus': data.get('trustStatus'),
                'qualityFlags': data.get('qualityFlags'),
                'mediaQuality': data.get('mediaQuality'),
                'linkHealth': data.get('linkHealth'),
                'priceConfidence': data.get('priceConfidence'),
                'qualityUpdatedAt': data.get('qualityUpdatedAt'),
            })

        per_issue = max(10, limit // 4)

        # Missing image
        try:
            for doc in db.collection('products').where('imageUrl', '==', '').limit(per_issue).stream():
                data = doc.to_dict() or {}
                _add(data, doc.id, 'missing_image')
        except Exception:
            pass

        # Missing URL / affiliate link
        try:
            for doc in db.collection('products').where('affiliateUrl', '==', '').limit(per_issue).stream():
                data = doc.to_dict() or {}
                _add(data, doc.id, 'missing_url')
        except Exception:
            pass

        # Needs review
        try:
            for doc in db.collection('products').where('status', '==', 'needs_market_review').limit(per_issue).stream():
                data = doc.to_dict() or {}
                _add(data, doc.id, 'needs_review')
        except Exception:
            pass

        # Hidden
        try:
            for doc in db.collection('products').where('status', '==', 'hidden').limit(per_issue).stream():
                data = doc.to_dict() or {}
                _add(data, doc.id, 'hidden')
        except Exception:
            pass

        seen_ids: set = set()
        unique: List[Dict[str, Any]] = []
        for item in items:
            if item['id'] not in seen_ids:
                seen_ids.add(item['id'])
                unique.append(item)
        unique = unique[:limit]
        return {'items': unique, 'total': len(unique)}

    def _moderate_product(
        self,
        product_id: str,
        updates: Dict[str, Any],
        action: str,
        admin_uid: str,
        admin_email: str,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        ref = db.collection('products').document(product_id)
        doc = ref.get()
        before_status = None
        if doc.exists:
            before_status = (doc.to_dict() or {}).get('status')
        updates['updatedAt'] = _now_iso()
        ref.set(updates, merge=True)
        self._write_admin_log(
            action=action,
            target_type='product',
            target_id=product_id,
            admin_uid=admin_uid,
            admin_email=admin_email,
            before_status=before_status,
            after_status=updates.get('status'),
            reason=reason,
        )
        return {'ok': True, 'id': product_id}

    def hide_product(self, product_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_product(product_id, {'status': 'hidden', 'isActive': False}, 'product_hide', admin_uid, admin_email, reason)

    def restore_product(self, product_id: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._moderate_product(product_id, {'status': 'active', 'isActive': True}, 'product_restore', admin_uid, admin_email)

    def mark_product_review(self, product_id: str, admin_uid: str, admin_email: str, reason: Optional[str] = None) -> Dict[str, Any]:
        return self._moderate_product(product_id, {'status': 'needs_market_review', 'adminIssue': reason}, 'product_mark_review', admin_uid, admin_email, reason)

    # ─────────────────────── duplicate review ────────────────────────────────

    def scan_product_duplicates(self, limit: int = 300, dry_run: bool = True, write: bool = False) -> Dict[str, Any]:
        from services.product_trust_service import group_duplicate_candidates

        summary: Dict[str, Any] = {
            'scanned': 0, 'groupsFound': 0, 'candidateProducts': 0,
            'wouldUpdate': 0, 'updated': 0, 'dryRun': dry_run,
        }
        try:
            docs = db.collection('products').limit(limit).stream()
        except Exception:
            return summary

        products: List[Dict[str, Any]] = []
        try:
            for doc in docs:
                try:
                    data = doc.to_dict() or {}
                    data['id'] = doc.id
                    products.append(data)
                    summary['scanned'] += 1
                except Exception:
                    continue
        except Exception:
            pass

        try:
            groups = group_duplicate_candidates(products)
        except Exception:
            groups = []
        summary['groupsFound'] = len(groups)

        candidate_ids: set = set()
        should_write = (not dry_run) and write

        for group in groups:
            group_id = group['groupId']
            reasons = group.get('duplicateReasons', [])
            score = group.get('highestScore', 0)

            for p in group.get('products', []):
                pid = str(p.get('id') or '')
                if not pid:
                    continue
                candidate_ids.add(pid)
                existing_dup_status = p.get('duplicateStatus')
                if existing_dup_status in {'dismissed', 'not_duplicate', 'master'}:
                    continue
                summary['wouldUpdate'] += 1
                if should_write:
                    try:
                        db.collection('products').document(pid).set({
                            'duplicateStatus': 'candidate',
                            'duplicateGroupId': group_id,
                            'duplicateReasons': reasons,
                            'duplicateScore': score,
                            'updatedAt': _now_iso(),
                        }, merge=True)
                        summary['updated'] += 1
                    except Exception:
                        pass

        summary['candidateProducts'] = len(candidate_ids)
        return summary

    def list_product_duplicates(self, status: str = 'candidate', limit: int = 50) -> Dict[str, Any]:
        groups_map: Dict[str, List[Dict[str, Any]]] = {}

        def _fetch(s: str) -> None:
            try:
                docs = db.collection('products').where('duplicateStatus', '==', s).limit(limit * 2).stream()
                for doc in docs:
                    data = doc.to_dict() or {}
                    data['id'] = doc.id
                    gid = data.get('duplicateGroupId') or ''
                    if not gid:
                        continue
                    if gid not in groups_map:
                        groups_map[gid] = []
                    if len(groups_map[gid]) < 10:
                        groups_map[gid].append(data)
            except Exception:
                pass

        if status == 'all':
            for s in ['candidate', 'master', 'duplicate', 'dismissed']:
                _fetch(s)
        else:
            _fetch(status or 'candidate')

        groups: List[Dict[str, Any]] = []
        for gid, products in groups_map.items():
            try:
                if len(products) < 1:
                    continue
                highest_score = max((p.get('duplicateScore') or 0) for p in products)
                reasons: set = set()
                for p in products:
                    for r in (p.get('duplicateReasons') or []):
                        if isinstance(r, str):
                            reasons.add(r)
                product_items = []
                for p in products:
                    try:
                        product_items.append(self._to_duplicate_product(p))
                    except Exception:
                        continue
                groups.append({
                    'groupId': gid,
                    'reasonSummary': ', '.join(sorted(reasons)),
                    'highestScore': int(highest_score),
                    'products': product_items,
                })
            except Exception:
                continue

        groups = groups[:limit]
        return {'groups': groups, 'total': len(groups)}

    def _to_duplicate_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        media = data.get('mediaQuality') or {}
        link = data.get('linkHealth') or {}
        return {
            'id': data.get('id') or '',
            'name': data.get('name') or data.get('title') or '',
            'imageUrl': data.get('imageUrl') or data.get('image') or '',
            'galleryCount': int(media.get('validImageCount') or 0),
            'price': _to_float(data.get('price') or data.get('currentPrice') or 0) or None,
            'currency': data.get('currency') or data.get('currencyCode') or '',
            'store': data.get('store') or data.get('source') or '',
            'primaryUrl': link.get('primaryUrl') or data.get('affiliateUrl') or data.get('productUrl') or '',
            'hasAffiliateUrl': bool(data.get('affiliateUrl')),
            'hasProductUrl': bool(data.get('productUrl')),
            'qualityScore': data.get('qualityScore'),
            'trustStatus': data.get('trustStatus'),
            'priceConfidence': data.get('priceConfidence'),
            'duplicateStatus': data.get('duplicateStatus'),
            'duplicateReasons': list(data.get('duplicateReasons') or []),
            'duplicateScore': int(data.get('duplicateScore') or 0),
            'status': data.get('status'),
            'updatedAt': _ts(data.get('updatedAt')),
        }

    def mark_duplicate_master(self, group_id: str, product_id: str, admin_uid: str, admin_email: str, note: Optional[str] = None) -> Dict[str, Any]:
        try:
            db.collection('products').document(product_id).set({
                'duplicateStatus': 'master',
                'duplicateGroupId': group_id,
                'updatedAt': _now_iso(),
            }, merge=True)
            self._write_admin_log('duplicate_mark_master', 'product', product_id, admin_uid, admin_email, note=f'group:{group_id} | {note or ""}')
            return {'ok': True, 'id': product_id}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def hide_duplicate_product(self, product_id: str, master_product_id: str, admin_uid: str, admin_email: str, note: Optional[str] = None) -> Dict[str, Any]:
        try:
            ref = db.collection('products').document(product_id)
            doc = ref.get()
            prev_status = (doc.to_dict() or {}).get('status') if doc.exists else None
            ref.set({
                'duplicateStatus': 'duplicate',
                'duplicateMasterId': master_product_id,
                'status': 'hidden',
                'isActive': False,
                'hiddenReason': 'duplicate',
                'previousStatus': prev_status,
                'updatedAt': _now_iso(),
            }, merge=True)
            self._write_admin_log('duplicate_hide', 'product', product_id, admin_uid, admin_email,
                                  before_status=prev_status, after_status='hidden',
                                  note=f'master:{master_product_id} | {note or ""}')
            return {'ok': True, 'id': product_id}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def dismiss_duplicate_product(self, product_id: str, admin_uid: str, admin_email: str, note: Optional[str] = None) -> Dict[str, Any]:
        try:
            db.collection('products').document(product_id).set({
                'duplicateStatus': 'dismissed',
                'updatedAt': _now_iso(),
            }, merge=True)
            self._write_admin_log('duplicate_dismiss', 'product', product_id, admin_uid, admin_email, note=note)
            return {'ok': True, 'id': product_id}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def restore_duplicate_product(self, product_id: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        try:
            ref = db.collection('products').document(product_id)
            doc = ref.get()
            data = doc.to_dict() or {}
            prev_status = data.get('previousStatus') or 'active'
            ref.set({
                'duplicateStatus': 'candidate',
                'status': prev_status,
                'isActive': prev_status == 'active',
                'hiddenReason': None,
                'updatedAt': _now_iso(),
            }, merge=True)
            self._write_admin_log('duplicate_restore', 'product', product_id, admin_uid, admin_email,
                                  before_status='hidden', after_status=prev_status)
            return {'ok': True, 'id': product_id}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def mark_product_safe(self, product_id: str, admin_uid: str, admin_email: str) -> Dict[str, Any]:
        return self._moderate_product(
            product_id,
            {'status': 'active', 'isActive': True, 'trustStatus': 'trusted', 'adminVerified': True},
            'product_mark_safe',
            admin_uid,
            admin_email,
        )

    def refresh_product_quality(self, product_id: str) -> Dict[str, Any]:
        from services.product_trust_service import build_quality_update
        ref = db.collection('products').document(product_id)
        doc = ref.get()
        if not doc.exists:
            return {'ok': False, 'error': 'Product not found'}
        product = doc.to_dict() or {}
        product['id'] = product_id
        update = build_quality_update(product)
        update['updatedAt'] = _now_iso()
        ref.set(update, merge=True)
        return {'ok': True, 'id': product_id, 'qualityScore': update['qualityScore'], 'trustStatus': update['trustStatus']}

    def scan_products_quality(self, limit: int = 100, dry_run: bool = True, write: bool = False) -> Dict[str, Any]:
        from services.product_trust_service import build_quality_update, product_fingerprint

        summary = {
            'scanned': 0, 'wouldUpdate': 0, 'updated': 0,
            'missingImage': 0, 'missingLink': 0, 'missingPrice': 0,
            'singleImageOnly': 0, 'duplicates': 0, 'quarantined': 0,
            'needsReview': 0, 'trusted': 0, 'dryRun': dry_run,
        }

        try:
            docs = db.collection('products').limit(limit).stream()
        except Exception:
            return summary

        fingerprints: Dict[str, str] = {}
        should_write = (not dry_run) and write

        for doc in docs:
            try:
                data = doc.to_dict() or {}
                data['id'] = doc.id
                summary['scanned'] += 1

                update = build_quality_update(data)
                flags: List[str] = update.get('qualityFlags', [])
                trust_status: str = update.get('trustStatus', '')
                flag_set = set(flags)

                # Duplicate detection by fingerprint
                fp = product_fingerprint(data)
                if fp in fingerprints:
                    if 'duplicate_candidate' not in flags:
                        flags.append('duplicate_candidate')
                        update['qualityFlags'] = flags
                    summary['duplicates'] += 1
                else:
                    fingerprints[fp] = doc.id

                # Counters
                if 'missing_image' in flag_set:
                    summary['missingImage'] += 1
                if 'missing_link' in flag_set:
                    summary['missingLink'] += 1
                if 'missing_price' in flag_set:
                    summary['missingPrice'] += 1
                if 'single_image_only' in flag_set:
                    summary['singleImageOnly'] += 1
                if trust_status == 'quarantined':
                    summary['quarantined'] += 1
                elif trust_status == 'needs_review':
                    summary['needsReview'] += 1
                elif trust_status == 'trusted':
                    summary['trusted'] += 1

                summary['wouldUpdate'] += 1

                if should_write:
                    update['updatedAt'] = _now_iso()
                    db.collection('products').document(doc.id).set(update, merge=True)
                    summary['updated'] += 1

            except Exception:
                continue

        return summary

    # ─────────────────────── import batches ──────────────────────────────────

    def _batch_to_dict(self, doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'batchId': data.get('batchId') or data.get('importBatchId') or doc_id,
            'source': data.get('source') or data.get('provider'),
            'sourceType': data.get('sourceType'),
            'store': data.get('store'),
            'startedAt': _ts(data.get('startedAt') or data.get('createdAt')),
            'finishedAt': _ts(data.get('finishedAt') or data.get('completedAt')),
            'status': data.get('status'),
            'dryRun': bool(data.get('dryRun')),
            'imported': int(data.get('imported') or data.get('itemsImported') or 0),
            'created': int(data.get('created') or 0),
            'updated': int(data.get('updated') or 0),
            'skipped': int(data.get('skipped') or 0),
            'failed': int(data.get('failed') or data.get('errors') or 0),
            'approved': int(data.get('approved') or 0),
            'needsReview': int(data.get('needsReview') or 0),
            'quarantined': int(data.get('quarantined') or 0),
            'duplicateCandidates': int(data.get('duplicateCandidates') or 0),
            'missingImage': int(data.get('missingImage') or 0),
            'missingLink': int(data.get('missingLink') or 0),
            'missingPrice': int(data.get('missingPrice') or 0),
            'missingCurrency': int(data.get('missingCurrency') or 0),
            'singleImageOnly': int(data.get('singleImageOnly') or 0),
            'noGallery': int(data.get('noGallery') or 0),
            'duplicateImages': int(data.get('duplicateImages') or 0),
            'qualityWarnings': int(data.get('qualityWarnings') or 0),
            'sourceTrustScore': data.get('sourceTrustScore') or data.get('sourceTrustScoreAfter'),
            'errors': list(data.get('errors') or []) if isinstance(data.get('errors'), list) else [],
            'warnings': list(data.get('warnings') or []) if isinstance(data.get('warnings'), list) else [],
            'durationMs': data.get('durationMs'),
            'createdBy': data.get('createdBy') or data.get('adminUid'),
        }

    def list_import_batches(self, limit: int = 50) -> Dict[str, Any]:
        batches: List[Dict[str, Any]] = []
        for coll in ('import_batches', 'import_logs'):
            try:
                docs = db.collection(coll).order_by('startedAt', direction='DESCENDING').limit(limit).stream()
                for doc in docs:
                    data = doc.to_dict() or {}
                    batches.append(self._batch_to_dict(doc.id, data))
                if batches:
                    break
            except Exception:
                try:
                    docs = db.collection(coll).limit(limit).stream()
                    for doc in docs:
                        data = doc.to_dict() or {}
                        batches.append(self._batch_to_dict(doc.id, data))
                    if batches:
                        break
                except Exception:
                    continue
        return {'batches': batches, 'total': len(batches)}

    def get_import_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        for coll in ('import_batches', 'import_logs'):
            try:
                doc = db.collection(coll).document(batch_id).get()
                if doc.exists:
                    return self._batch_to_dict(doc.id, doc.to_dict() or {})
            except Exception:
                continue
        return None

    def _resolve_batch_products(self, batch_id: str, limit: int = 500) -> List[str]:
        product_ids: List[str] = []
        try:
            docs = db.collection('products').where('importBatchId', '==', batch_id).limit(limit).stream()
            for doc in docs:
                product_ids.append(doc.id)
        except Exception:
            pass
        return product_ids

    def hide_import_batch_products(
        self,
        batch_id: str,
        admin_uid: str,
        admin_email: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        product_ids = self._resolve_batch_products(batch_id)
        hidden = 0
        for pid in product_ids:
            try:
                ref = db.collection('products').document(pid)
                doc = ref.get()
                prev = (doc.to_dict() or {}).get('status') if doc.exists else None
                if prev in {'rejected', 'banned'}:
                    continue
                ref.set({
                    'status': 'hidden',
                    'isActive': False,
                    'hiddenReason': 'import_batch_hidden',
                    'previousStatus': prev,
                    'updatedAt': _now_iso(),
                }, merge=True)
                hidden += 1
            except Exception:
                continue
        self._write_admin_log(
            'import_batch_hide_products',
            'import_batch',
            batch_id,
            admin_uid,
            admin_email,
            note=f'batchId:{batch_id} | hidden:{hidden} | {note or ""}',
        )
        return {'ok': True, 'batchId': batch_id, 'hidden': hidden, 'total': len(product_ids)}

    def mark_import_batch_review(
        self,
        batch_id: str,
        admin_uid: str,
        admin_email: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        product_ids = self._resolve_batch_products(batch_id)
        marked = 0
        for pid in product_ids:
            try:
                ref = db.collection('products').document(pid)
                doc = ref.get()
                data = doc.to_dict() or {} if doc.exists else {}
                if data.get('status') in {'rejected', 'banned', 'hidden'}:
                    continue
                ref.set({
                    'admissionStatus': 'needs_review',
                    'trustStatus': 'needs_review',
                    'updatedAt': _now_iso(),
                }, merge=True)
                marked += 1
            except Exception:
                continue
        self._write_admin_log(
            'import_batch_mark_review',
            'import_batch',
            batch_id,
            admin_uid,
            admin_email,
            note=f'batchId:{batch_id} | marked:{marked} | {note or ""}',
        )
        return {'ok': True, 'batchId': batch_id, 'marked': marked, 'total': len(product_ids)}

    def restore_import_batch_products(
        self,
        batch_id: str,
        admin_uid: str,
        admin_email: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        product_ids = self._resolve_batch_products(batch_id)
        restored = 0
        for pid in product_ids:
            try:
                ref = db.collection('products').document(pid)
                doc = ref.get()
                data = doc.to_dict() or {} if doc.exists else {}
                if data.get('status') in {'rejected', 'banned'}:
                    continue
                if data.get('hiddenReason') != 'import_batch_hidden':
                    continue
                prev = data.get('previousStatus') or 'active'
                ref.set({
                    'status': prev,
                    'isActive': prev == 'active',
                    'hiddenReason': None,
                    'updatedAt': _now_iso(),
                }, merge=True)
                restored += 1
            except Exception:
                continue
        self._write_admin_log(
            'import_batch_restore_products',
            'import_batch',
            batch_id,
            admin_uid,
            admin_email,
            note=f'batchId:{batch_id} | restored:{restored} | {note or ""}',
        )
        return {'ok': True, 'batchId': batch_id, 'restored': restored, 'total': len(product_ids)}

    # ─────────────────────── source trust ────────────────────────────────────

    def list_source_trust(self, limit: int = 50) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        try:
            docs = db.collection('source_trust').limit(limit).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                items.append({
                    'id': doc.id,
                    'source': data.get('source'),
                    'store': data.get('store'),
                    'domain': data.get('domain'),
                    'sourceTrustScore': int(
                        data.get('trustScore')
                        if data.get('trustScore') is not None
                        else data.get('sourceTrustScore') or 100
                    ),
                    'status': {
                        'strong': 'trusted',
                        'stable': 'ok',
                        'watch': 'watch',
                        'weak': 'risky',
                    }.get(
                        str(data.get('trustLabel') or '').lower(),
                        data.get('status') or 'ok',
                    ),
                    'totalImported': int(
                        data.get('totalProducts')
                        if data.get('totalProducts') is not None
                        else data.get('totalImported') or 0
                    ),
                    'totalFailed': int(data.get('totalFailed') or 0),
                    'totalUpdated': int(data.get('totalUpdated') or 0),
                    'totalDuplicates': int(
                        data.get('hiddenDuplicateCount')
                        if data.get('hiddenDuplicateCount') is not None
                        else data.get('totalDuplicates') or 0
                    ),
                    'totalMissingImage': int(
                        data.get('missingImageCount')
                        if data.get('missingImageCount') is not None
                        else data.get('totalMissingImage') or 0
                    ),
                    'totalMissingLink': int(
                        data.get('missingLinkCount')
                        if data.get('missingLinkCount') is not None
                        else data.get('totalMissingLink') or 0
                    ),
                    'totalMissingPrice': int(
                        data.get('missingPriceCount')
                        if data.get('missingPriceCount') is not None
                        else data.get('totalMissingPrice') or 0
                    ),
                    'totalQuarantined': int(
                        data.get('quarantinedCount')
                        if data.get('quarantinedCount') is not None
                        else data.get('totalQuarantined') or 0
                    ),
                    'totalNeedsReview': int(
                        data.get('needsReviewCount')
                        if data.get('needsReviewCount') is not None
                        else data.get('totalNeedsReview') or 0
                    ),
                    'successfulBatches': int(data.get('successfulBatches') or 0),
                    'failedBatches': int(data.get('failedBatches') or 0),
                    'lastImportAt': _ts(
                        data.get('lastImportedAt')
                        or data.get('lastImportAt')
                    ),
                    'lastSuccessfulImportAt': _ts(data.get('lastSuccessfulImportAt')),
                    'lastFailedImportAt': _ts(data.get('lastFailedImportAt')),
                    'reasons': list(data.get('reasons') or []),
                    'updatedAt': _ts(
                        data.get('recalibratedAt')
                        or data.get('updatedAt')
                    ),
                })
        except Exception:
            pass
        return {'items': items, 'total': len(items)}

    # ─────────────────────── system health ───────────────────────────────────

    def system_health(self) -> Dict[str, Any]:
        errors = self.system_errors(limit=25)
        scrape_failures = self.failed_scrapings(limit=25)
        ai_errors = self.recent_ai_queries(limit=20)

        import_logs: List[Dict[str, Any]] = []
        try:
            docs = db.collection('import_logs').order_by('createdAt', direction='DESCENDING').limit(20).stream()
            for doc in docs:
                data = doc.to_dict() or {}
                import_logs.append({
                    'id': doc.id,
                    'source': data.get('source') or data.get('provider'),
                    'status': data.get('status'),
                    'itemsImported': int(data.get('itemsImported') or data.get('count') or 0),
                    'errors': int(data.get('errors') or data.get('errorCount') or 0),
                    'createdAt': _ts(data.get('createdAt')),
                })
        except Exception:
            pass

        return {
            'systemErrors': errors,
            'importLogs': import_logs,
            'aiErrors': ai_errors,
            'failedScrapings': scrape_failures,
        }

    # ─────────────────────── audit logs ──────────────────────────────────────

    def list_admin_logs(self, limit: int = 50) -> Dict[str, Any]:
        logs: List[Dict[str, Any]] = []
        try:
            docs = (
                db.collection('admin_logs')
                .order_by('createdAt', direction='DESCENDING')
                .limit(limit)
                .stream()
            )
            for doc in docs:
                data = doc.to_dict() or {}
                logs.append({
                    'id': doc.id,
                    'adminUid': data.get('adminUid') or '',
                    'adminEmail': data.get('adminEmail') or '',
                    'action': data.get('action') or '',
                    'targetType': data.get('targetType') or '',
                    'targetId': data.get('targetId') or '',
                    'beforeStatus': data.get('beforeStatus'),
                    'afterStatus': data.get('afterStatus'),
                    'reason': data.get('reason'),
                    'note': data.get('note'),
                    'createdAt': _ts(data.get('createdAt')),
                })
        except Exception:
            pass
        return {'logs': logs, 'total': len(logs)}

    def _write_admin_log(
        self,
        action: str,
        target_type: str,
        target_id: str,
        admin_uid: str,
        admin_email: str,
        before_status: Optional[str] = None,
        after_status: Optional[str] = None,
        reason: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        try:
            db.collection('admin_logs').add({
                'adminUid': admin_uid,
                'adminEmail': admin_email,
                'action': action,
                'targetType': target_type,
                'targetId': target_id,
                'beforeStatus': before_status,
                'afterStatus': after_status,
                'reason': reason,
                'note': note,
                'createdAt': _now_iso(),
            })
        except Exception:
            pass
