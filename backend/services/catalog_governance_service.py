from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.firebase import db

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
