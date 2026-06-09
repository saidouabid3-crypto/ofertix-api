from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.firebase import db

# ─── governed import session ──────────────────────────────────────────────────


class GovernedImportSession:
    """
    Context object for a single governed import run.

    Usage:
        session = GovernedImportSession('impact', 'DHgate', dry_run=False)
        session.start()
        for product in products:
            gov_fields = session.process_product(product)
            product.update(gov_fields)
            # ... write product to Firestore ...
        result = session.finalize()
    """

    def __init__(
        self,
        source: str,
        store: str,
        source_type: str = 'feed',
        dry_run: bool = False,
        admin_uid: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        self.source = (source or '').lower().strip()
        self.store = store or source or ''
        self.source_type = source_type
        self.dry_run = dry_run
        self.admin_uid = admin_uid

        ts = datetime.now(timezone.utc)
        self.batch_id = batch_id or f'{self.source}_{int(ts.timestamp())}'
        self.started_at = ts.isoformat()

        self._config: Dict[str, Any] = dict(_DEFAULT_CONFIG)
        self._source_trust_score_before: int = 100
        self._source_trust_status_before: str = 'ok'
        self._fingerprints: Dict[str, str] = {}

        # counters
        self.imported = 0
        self.created = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0
        self.approved = 0
        self.needs_review = 0
        self.quarantined = 0
        self.duplicate_candidates = 0
        self.missing_image = 0
        self.missing_link = 0
        self.missing_price = 0
        self.missing_currency = 0
        self.single_image_only = 0
        self.no_gallery = 0
        self.duplicate_images_count = 0
        self.invalid_link = 0
        self.weak_description = 0
        self.quality_warnings = 0
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def start(self) -> 'GovernedImportSession':
        try:
            self._config = get_catalog_governance_config()
        except Exception:
            pass

        _trust_doc_id = re.sub(r'[^a-z0-9_\-.]', '_', (self.store or self.source).lower())[:60]
        try:
            snap = db.collection('source_trust').document(_trust_doc_id).get()
            if snap.exists:
                data = snap.to_dict() or {}
                self._source_trust_score_before = int(
                    data.get('trustScore')
                    if data.get('trustScore') is not None
                    else data.get('sourceTrustScore', 100)
                )
                calibrated_label = str(data.get('trustLabel') or '').lower()
                self._source_trust_status_before = {
                    'strong': 'trusted',
                    'stable': 'ok',
                    'watch': 'watch',
                    'weak': 'risky',
                }.get(calibrated_label, str(data.get('status', 'ok')))
        except Exception:
            pass

        if not self.dry_run:
            try:
                db.collection('import_batches').document(self.batch_id).set({
                    'importBatchId': self.batch_id,
                    'source': self.source,
                    'sourceType': self.source_type,
                    'store': self.store,
                    'startedAt': self.started_at,
                    'status': 'running',
                    'dryRun': False,
                    'sourceTrustScoreBefore': self._source_trust_score_before,
                    'createdBy': self.admin_uid,
                    'updatedAt': self.started_at,
                })
            except Exception as exc:
                self.errors.append(f'batch_start: {str(exc)[:80]}')

        return self

    def process_product(self, product: dict) -> Dict[str, Any]:
        """
        Run Product Trust Engine + admission gate on a normalized product.
        Returns governance fields to merge into the product before saving.
        Counter attributes are updated in place.
        """
        from services.product_trust_service import build_quality_update, product_fingerprint as _fp

        now = datetime.now(timezone.utc).isoformat()

        try:
            trust = build_quality_update(product)
        except Exception as exc:
            self.failed += 1
            self.errors.append(f'trust: {str(exc)[:60]}')
            return {
                'importBatchId': self.batch_id,
                'lastImportedAt': now,
                'admissionStatus': 'needs_review',
                'publicVisible': False,
            }

        flags: List[str] = list(trust.get('qualityFlags') or [])
        flag_set = set(flags)

        if 'missing_image' in flag_set:
            self.missing_image += 1
        if 'missing_link' in flag_set:
            self.missing_link += 1
        if 'missing_price' in flag_set:
            self.missing_price += 1
        if 'missing_currency' in flag_set:
            self.missing_currency += 1
        if 'single_image_only' in flag_set:
            self.single_image_only += 1
        if 'no_gallery' in flag_set:
            self.no_gallery += 1
        if 'duplicate_images' in flag_set:
            self.duplicate_images_count += 1
        if 'invalid_link' in flag_set:
            self.invalid_link += 1
        if 'weak_description' in flag_set:
            self.weak_description += 1

        # Within-batch duplicate detection
        try:
            fp = _fp(product)
        except Exception:
            fp = ''

        if fp:
            if fp in self._fingerprints:
                self.duplicate_candidates += 1
                if 'duplicate_candidate' not in flag_set:
                    flags.append('duplicate_candidate')
                    flag_set.add('duplicate_candidate')
                    trust['qualityFlags'] = flags
            else:
                self._fingerprints[fp] = product.get('id') or ''

        # Admission gate
        try:
            admission = decide_product_admission(
                product,
                trust,
                self._source_trust_score_before,
                self._source_trust_status_before,
                self._config,
            )
        except Exception:
            admission = {
                'admissionStatus': 'needs_review',
                'publicVisible': False,
                'reasons': ['admission_error'],
                'recommendedAction': 'review',
                'catalogRankScore': 0,
                'riskLevel': 'high',
                'sourceTrustScoreAtImport': self._source_trust_score_before,
            }

        admission_status: str = admission.get('admissionStatus', 'needs_review')

        if admission_status == 'approved':
            self.approved += 1
        elif admission_status == 'quarantined':
            self.quarantined += 1
        else:
            self.needs_review += 1
            if admission_status not in {'duplicate_candidate'}:
                self.quality_warnings += 1

        # Identity
        try:
            identity = build_product_identity(product)
        except Exception:
            identity = {}

        self.imported += 1

        gov: Dict[str, Any] = {
            'importBatchId': self.batch_id,
            'lastImportedAt': now,
            'firstImportedAt': now,
            'sourceKey': identity.get('sourceKey', ''),
            'identityType': identity.get('identityType', ''),
            'admissionStatus': admission_status,
            'publicVisible': admission.get('publicVisible', True),
            'riskLevel': admission.get('riskLevel', 'medium'),
            'catalogRankScore': admission.get('catalogRankScore', 0),
            'qualityReasons': admission.get('reasons', []),
            'sourceTrustScoreAtImport': self._source_trust_score_before,
        }
        if fp:
            gov['productFingerprint'] = fp
            gov['duplicateFingerprint'] = fp

        gov.update(trust)
        return gov

    def finalize(
        self,
        extra_errors: Optional[List[str]] = None,
        extra_warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        try:
            started_dt = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
            duration_ms = int((now - started_dt).total_seconds() * 1000)
        except Exception:
            duration_ms = 0

        now_iso = now.isoformat()

        if extra_errors:
            self.errors.extend(extra_errors)
        if extra_warnings:
            self.warnings.extend(extra_warnings)

        has_errors = bool(self.errors) or self.failed > 0
        has_warnings = self.quality_warnings > 0 or self.needs_review > 0 or self.quarantined > 0 or bool(self.warnings)

        if has_errors and self.imported == 0:
            status = 'failed'
        elif has_warnings:
            status = 'completed_with_warnings'
        else:
            status = 'completed'

        counters: Dict[str, Any] = {
            'imported': self.imported,
            'created': self.created,
            'updated': self.updated,
            'skipped': self.skipped,
            'failed': self.failed,
            'approved': self.approved,
            'needsReview': self.needs_review,
            'quarantined': self.quarantined,
            'duplicateCandidates': self.duplicate_candidates,
            'missingImage': self.missing_image,
            'missingLink': self.missing_link,
            'missingPrice': self.missing_price,
            'missingCurrency': self.missing_currency,
            'singleImageOnly': self.single_image_only,
            'noGallery': self.no_gallery,
            'duplicateImages': self.duplicate_images_count,
            'invalidLink': self.invalid_link,
            'weakDescription': self.weak_description,
            'qualityWarnings': self.quality_warnings,
        }

        source_trust_result: Dict[str, Any] = {}
        if not self.dry_run:
            try:
                source_trust_result = update_source_trust(
                    source=self.source,
                    store=self.store,
                    domain='',
                    batch_stats={**counters, 'status': status},
                )
            except Exception:
                pass

        score_after = source_trust_result.get('sourceTrustScore', self._source_trust_score_before)
        trust_status_after = source_trust_result.get('status', self._source_trust_status_before)

        batch_doc: Dict[str, Any] = {
            'importBatchId': self.batch_id,
            'source': self.source,
            'sourceType': self.source_type,
            'store': self.store,
            'startedAt': self.started_at,
            'finishedAt': now_iso,
            'status': status,
            'dryRun': self.dry_run,
            'sourceTrustScoreBefore': self._source_trust_score_before,
            'sourceTrustScoreAfter': score_after,
            'sourceTrustStatus': trust_status_after,
            'errors': self.errors[:20],
            'warnings': self.warnings[:20],
            'durationMs': duration_ms,
            'createdBy': self.admin_uid,
            'updatedAt': now_iso,
            **counters,
        }

        if not self.dry_run:
            try:
                db.collection('import_batches').document(self.batch_id).set(batch_doc, merge=True)
            except Exception:
                pass

        return {
            'batchId': self.batch_id,
            'status': status,
            'dryRun': self.dry_run,
            'counters': counters,
            'sourceTrustScoreBefore': self._source_trust_score_before,
            'sourceTrustScoreAfter': score_after,
            'durationMs': duration_ms,
        }

# ─── defaults ────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG: Dict[str, Any] = {
    'qualityGateEnabled': True,
    'publicFilteringEnabled': False,
    'hideQuarantinedFromPublic': True,
    'hideDuplicateProductsFromPublic': False,
    'blockRiskySources': False,
    'autoMarkNeedsReview': True,
    'autoQuarantineCriticalProducts': True,
    'minPublicQualityScore': 40,
    'sourceTrustGateEnabled': True,
    'importDryRunDefault': True,
}

_LINK_AFFILIATE = ['affiliateUrl', 'affiliate_url', 'affiliateURL']
_LINK_PRODUCT = ['productUrl', 'product_url', 'productURL']
_LINK_OTHER = ['sourceUrl', 'source_url', 'originalUrl', 'link', 'url']
_NAME_FIELDS = ['name', 'title', 'productName', 'fullTitle']
_STORE_FIELDS = ['store', 'storeName', 'merchant', 'merchantName', 'source']
_PRICE_FIELDS = ['price', 'currentPrice', 'salePrice']

# ─── config ───────────────────────────────────────────────────────────────────


def get_catalog_governance_config() -> Dict[str, Any]:
    config = dict(_DEFAULT_CONFIG)
    try:
        doc = db.collection('app_config').document('catalog_governance').get()
        if doc.exists:
            stored = doc.to_dict() or {}
            for key, default in _DEFAULT_CONFIG.items():
                if key in stored:
                    config[key] = stored[key]
    except Exception:
        pass
    return config


# ─── product identity ─────────────────────────────────────────────────────────


def _first(product: dict, fields: List[str]) -> str:
    for f in fields:
        val = product.get(f)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ''


def build_product_identity(product: dict) -> Dict[str, Any]:
    source = str(product.get('source') or '').strip().lower()
    source_product_id = str(product.get('sourceProductId') or product.get('source_product_id') or '').strip()
    if source and source_product_id:
        key = f'{source}::{source_product_id}'
        return {'sourceKey': key, 'source': source, 'sourceProductId': source_product_id, 'identityType': 'source_id'}

    affiliate = _first(product, _LINK_AFFILIATE)
    if affiliate:
        norm = re.sub(r'https?://', '', affiliate).split('?')[0].rstrip('/')
        key = hashlib.md5(norm.encode()).hexdigest()
        return {'sourceKey': f'aff::{key}', 'source': source, 'primaryUrl': affiliate, 'identityType': 'affiliate_url'}

    product_url = _first(product, _LINK_PRODUCT)
    if product_url:
        norm = re.sub(r'https?://', '', product_url).split('?')[0].rstrip('/')
        key = hashlib.md5(norm.encode()).hexdigest()
        return {'sourceKey': f'pu::{key}', 'source': source, 'primaryUrl': product_url, 'identityType': 'product_url'}

    fingerprint = str(product.get('productFingerprint') or product.get('duplicateFingerprint') or '').strip()
    if fingerprint:
        return {'sourceKey': f'fp::{fingerprint}', 'source': source, 'identityType': 'fingerprint'}

    name = _first(product, _NAME_FIELDS).lower()[:50]
    store = _first(product, _STORE_FIELDS).lower()[:20]
    price_raw = next((product.get(f) for f in _PRICE_FIELDS if product.get(f) is not None), '')
    raw = f'{re.sub(r"[^a-z0-9]", "", name)}|{store}|{price_raw}'
    key = hashlib.md5(raw.encode()).hexdigest()
    return {'sourceKey': f'tsp::{key}', 'source': source, 'identityType': 'title_store_price'}


# ─── source trust score ───────────────────────────────────────────────────────


def compute_source_trust_score(stats: Dict[str, Any]) -> int:
    score = 100
    total = max(1, int(stats.get('totalImported', 0)))

    def _ratio(key: str) -> float:
        return int(stats.get(key, 0)) / total

    missing_image_ratio = _ratio('totalMissingImage')
    missing_link_ratio = _ratio('totalMissingLink')
    missing_price_ratio = _ratio('totalMissingPrice')
    duplicate_ratio = _ratio('totalDuplicates')
    quarantine_ratio = _ratio('totalQuarantined')
    failed_batches = int(stats.get('failedBatches', 0))
    total_batches = max(1, int(stats.get('successfulBatches', 0)) + failed_batches)
    failed_batch_ratio = failed_batches / total_batches

    if missing_image_ratio > 0.5:
        score -= 20
    elif missing_image_ratio > 0.25:
        score -= 10

    if missing_link_ratio > 0.3:
        score -= 20
    elif missing_link_ratio > 0.1:
        score -= 10

    if missing_price_ratio > 0.3:
        score -= 15
    elif missing_price_ratio > 0.1:
        score -= 7

    if duplicate_ratio > 0.4:
        score -= 15
    elif duplicate_ratio > 0.2:
        score -= 7

    if quarantine_ratio > 0.3:
        score -= 15
    elif quarantine_ratio > 0.1:
        score -= 7

    if failed_batch_ratio > 0.5:
        score -= 15
    elif failed_batch_ratio > 0.25:
        score -= 7

    return max(0, min(100, score))


def _source_trust_status(score: int, manually_blocked: bool = False) -> str:
    if manually_blocked or score < 30:
        return 'blocked'
    if score < 50:
        return 'risky'
    if score < 70:
        return 'watch'
    if score < 85:
        return 'ok'
    return 'trusted'


def update_source_trust(
    source: str,
    store: str,
    domain: str,
    batch_stats: Dict[str, Any],
) -> Dict[str, Any]:
    if not source:
        return {}
    doc_id = re.sub(r'[^a-z0-9_\-.]', '_', (domain or store or source).lower().strip())[:60]
    if not doc_id:
        return {}

    now = datetime.now(timezone.utc).isoformat()
    ref = db.collection('source_trust').document(doc_id)

    try:
        snap = ref.get()
        existing: Dict[str, Any] = snap.to_dict() or {} if snap.exists else {}
    except Exception:
        existing = {}

    def _add(field: str) -> int:
        return int(existing.get(field, 0)) + int(batch_stats.get(field, 0))

    batch_ok = batch_stats.get('status') in {'completed', 'completed_with_warnings'}

    updated = {
        'source': source,
        'store': store or existing.get('store', ''),
        'domain': domain or existing.get('domain', ''),
        'totalImported': _add('imported'),
        'totalFailed': _add('failed'),
        'totalUpdated': _add('updated'),
        'totalDuplicates': _add('duplicateCandidates'),
        'totalMissingImage': _add('missingImage'),
        'totalMissingLink': _add('missingLink'),
        'totalMissingPrice': _add('missingPrice'),
        'totalQuarantined': _add('quarantined'),
        'totalNeedsReview': _add('needsReview'),
        'successfulBatches': int(existing.get('successfulBatches', 0)) + (1 if batch_ok else 0),
        'failedBatches': int(existing.get('failedBatches', 0)) + (0 if batch_ok else 1),
        'lastImportAt': now,
        'updatedAt': now,
    }

    if batch_ok:
        updated['lastSuccessfulImportAt'] = now
    else:
        updated['lastFailedImportAt'] = now

    score = compute_source_trust_score(updated)
    manually_blocked = bool(existing.get('manuallyBlocked'))
    status = _source_trust_status(score, manually_blocked)
    reasons: List[str] = list(existing.get('reasons') or [])

    updated['sourceTrustScore'] = score
    updated['status'] = status
    updated['reasons'] = reasons

    try:
        ref.set(updated, merge=True)
    except Exception:
        pass

    return {'docId': doc_id, 'sourceTrustScore': score, 'status': status}


# ─── product admission gate ───────────────────────────────────────────────────


def decide_product_admission(
    product: dict,
    trust_analysis: Dict[str, Any],
    source_trust_score: int,
    source_trust_status: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if config is None:
        config = _DEFAULT_CONFIG

    flags: List[str] = trust_analysis.get('qualityFlags') or []
    flag_set = set(flags)
    trust_status: str = trust_analysis.get('trustStatus') or 'needs_review'
    quality_score: int = int(trust_analysis.get('qualityScore') or 0)
    price_confidence: str = trust_analysis.get('priceConfidence') or 'missing'
    reasons: List[str] = []
    admission_status: str = 'approved'
    recommended_action: str = 'publish'
    public_visible: bool = True

    # price 0 / missing / suspicious: never auto-approve
    if price_confidence == 'missing' or 'missing_price' in flag_set:
        reasons.append('missing_price')
        admission_status = 'quarantined' if config.get('autoQuarantineCriticalProducts') else 'needs_review'
        recommended_action = 'quarantine' if admission_status == 'quarantined' else 'review'
        public_visible = False

    # missing image + missing link → quarantine
    if 'missing_image' in flag_set and 'missing_link' in flag_set:
        reasons.append('missing_image_and_link')
        admission_status = 'quarantined'
        recommended_action = 'quarantine'
        public_visible = False

    # duplicate candidate
    if trust_status == 'quarantined' and 'duplicate_candidate' in flag_set:
        reasons.append('duplicate_candidate')
        admission_status = 'duplicate_candidate'
        recommended_action = 'review'
        public_visible = False

    # risky/blocked source
    if source_trust_status in {'risky', 'blocked'}:
        reasons.append(f'source_trust_{source_trust_status}')
        if admission_status == 'approved':
            admission_status = 'needs_review' if source_trust_status == 'risky' else 'quarantined'
            recommended_action = 'review' if admission_status == 'needs_review' else 'quarantine'
            public_visible = admission_status == 'approved'

    # trust engine quarantine
    if trust_status == 'quarantined' and admission_status not in {'quarantined', 'duplicate_candidate'}:
        reasons.append('quality_quarantined')
        admission_status = 'quarantined'
        recommended_action = 'quarantine'
        public_visible = False

    # trust engine needs_review
    if trust_status == 'needs_review' and admission_status == 'approved':
        reasons.append('quality_needs_review')
        admission_status = 'needs_review'
        recommended_action = 'review'

    # compute risk level
    if admission_status == 'quarantined':
        risk_level = 'critical'
    elif admission_status in {'needs_review', 'duplicate_candidate'}:
        risk_level = 'high' if quality_score < 50 else 'medium'
    elif trust_status in {'trusted', 'ok'} and source_trust_score >= 70:
        risk_level = 'low'
    else:
        risk_level = 'medium'

    catalog_rank_score = max(0, int(quality_score * 0.6 + source_trust_score * 0.4))

    return {
        'admissionStatus': admission_status,
        'publicVisible': public_visible,
        'reasons': reasons,
        'recommendedAction': recommended_action,
        'catalogRankScore': catalog_rank_score,
        'riskLevel': risk_level,
        'sourceTrustScoreAtImport': source_trust_score,
    }
