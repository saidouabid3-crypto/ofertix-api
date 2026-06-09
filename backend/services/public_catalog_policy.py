from __future__ import annotations

import time
import re
from datetime import datetime, timezone
from typing import Any

from core.firebase import db

# ─── default config ───────────────────────────────────────────────────────────

_DEFAULT_CONFIG: dict[str, Any] = {
    'publicFilteringEnabled': False,
    'smartRankingEnabled': True,
    'hideQuarantined': False,
    'hideHiddenDuplicates': False,
    'hideRejected': False,
    'hideExplicitPublicInvisible': False,
    'hideMissingLink': False,
    'hideMissingImage': False,
    'hideMissingPrice': False,
    'hideNeedsReview': False,
    'demoteNeedsReview': True,
    'demoteLimitedInfo': True,
    'strictMode': False,
}

# simple 60-second in-process TTL cache
_config_cache: dict[str, Any] = {}
_config_cache_ts: float = 0.0
_CONFIG_TTL = 60.0

_QUARANTINED = {'quarantined', 'blocked', 'rejected', 'hidden'}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return default

    raw = re.sub(r'[^0-9,.\-]', '', str(value).strip())
    if not raw:
        return default
    if ',' in raw and '.' in raw:
        if raw.rfind(',') > raw.rfind('.'):
            raw = raw.replace('.', '').replace(',', '.')
        else:
            raw = raw.replace(',', '')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def load_catalog_config() -> dict[str, Any]:
    """
    Load app_config/catalog_governance from Firestore.
    Returns safe defaults if doc is missing or Firestore unavailable.
    Results are cached for 60 s to avoid per-request Firestore reads.
    """
    global _config_cache, _config_cache_ts
    if _config_cache and (time.monotonic() - _config_cache_ts) < _CONFIG_TTL:
        return dict(_config_cache)

    config = dict(_DEFAULT_CONFIG)
    try:
        doc = db.collection('app_config').document('catalog_governance').get()
        if doc.exists:
            data = doc.to_dict() or {}
            for k, default_v in _DEFAULT_CONFIG.items():
                raw = data.get(k)
                if raw is not None and isinstance(raw, type(default_v)):
                    config[k] = raw
    except Exception:
        pass

    _config_cache = dict(config)
    _config_cache_ts = time.monotonic()
    return config


def invalidate_config_cache() -> None:
    global _config_cache_ts
    _config_cache_ts = 0.0


# ─── ranking ──────────────────────────────────────────────────────────────────

def compute_rank_score(
    product: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> float:
    """Compute a public-facing rank score 0–100 from trust/quality fields."""
    effective_config = {**_DEFAULT_CONFIG, **(config or {})}
    base = _number(product.get('catalogRankScore') or product.get('qualityScore'), 50)
    score = max(0.0, min(100.0, base))

    trust = str(product.get('trustStatus') or '').lower()
    flags = {str(f).lower() for f in (product.get('qualityFlags') or [])}
    src = _number(product.get('sourceTrustScoreAtImport'))
    quality = _number(product.get('qualityScore'))
    price = _number(product.get('newPrice') or product.get('price'))
    images = product.get('images') or []
    link = str(product.get('affiliateUrl') or product.get('productUrl') or '').strip()
    risk = str(product.get('riskLevel') or '').lower()
    admission = str(product.get('admissionStatus') or '').lower()

    if trust in ('trusted', 'ok'):
        score += 20
    if src >= 85:
        score += 10
    if quality >= 80:
        score += 10
    if price > 0:
        score += 5
    if isinstance(images, list) and len(images) > 1:
        score += 5
    if link.startswith('http'):
        score += 5

    if effective_config.get('demoteLimitedInfo', True):
        if flags & {'missing_price', 'suspicious_price', 'missing_currency'}:
            score -= 30
        if flags & {'missing_link', 'invalid_link'}:
            score -= 25
        if 'missing_image' in flags:
            score -= 20
    if 'duplicate_candidate' in flags:
        score -= 20
    if effective_config.get('demoteNeedsReview', True) and (
        trust == 'needs_review' or admission == 'needs_review'
    ):
        score -= 15
    if risk == 'medium':
        score -= 15
    if risk == 'high':
        score -= 30
    if trust in _QUARANTINED:
        score -= 50

    return round(max(0.0, min(100.0, score)), 2)


# ─── visibility decision ──────────────────────────────────────────────────────

def evaluate_public_product(
    product: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Decide whether a product should be shown in the public catalog.
    Returns {'visible': bool, 'hiddenReason': str|None, 'rankScore': float}.

    When publicFilteringEnabled=False all products are visible (safe default).
    """
    rank = compute_rank_score(product, config)
    base = {'visible': True, 'hiddenReason': None, 'rankScore': rank}

    if not config.get('publicFilteringEnabled', False):
        return base

    trust = str(product.get('trustStatus') or '').lower()
    admission = str(product.get('admissionStatus') or '').lower()
    price_conf = str(product.get('priceConfidence') or '').lower()
    flags = {str(f).lower() for f in (product.get('qualityFlags') or [])}
    dup_action = str(product.get('duplicateAction') or '').lower()
    dup_status = str(product.get('duplicateStatus') or '').lower()
    hidden_dup = product.get('hiddenAsDuplicate') is True

    def _hide(reason: str) -> dict[str, Any]:
        return {**base, 'visible': False, 'hiddenReason': reason}

    if config.get('hideExplicitPublicInvisible') and product.get('publicVisible') is False:
        return _hide('public_invisible')

    if config.get('hideQuarantined') and trust in {'quarantined', 'blocked'}:
        return _hide('quarantined')

    if config.get('hideRejected') and (trust == 'rejected' or admission == 'rejected'):
        return _hide('rejected')

    if config.get('hideHiddenDuplicates') and (
        dup_action == 'hidden'
        or dup_status in {'hidden_as_duplicate', 'hidden'}
        or hidden_dup
    ):
        return _hide('hidden_duplicate')

    if config.get('hideMissingLink') and flags & {'missing_link', 'invalid_link'}:
        return _hide('missing_link')

    if config.get('hideMissingImage') and 'missing_image' in flags:
        return _hide('missing_image')

    if config.get('hideMissingPrice') and (
        'missing_price' in flags
        or price_conf == 'missing'
        or _number(product.get('newPrice')) <= 0
    ):
        return _hide('missing_price')

    # needs_review only hidden when BOTH strictMode AND hideNeedsReview are true
    if (
        config.get('strictMode') and config.get('hideNeedsReview')
        and (trust == 'needs_review' or admission == 'needs_review')
    ):
        return _hide('needs_review_hidden_strict')

    return base


# ─── admin preview (read-only, no writes) ────────────────────────────────────

def public_catalog_preview(limit: int = 500) -> dict[str, Any]:
    """
    Dry-run scan: counts what the current config would show/hide.
    Never writes to Firestore. Safe to call from admin.
    """
    config = load_catalog_config()
    generated_at = datetime.now(timezone.utc).isoformat()

    counts: dict[str, int] = {
        'total': 0, 'visible': 0, 'hidden': 0,
        'trusted': 0, 'needsReview': 0, 'priceReview': 0,
        'missingLink': 0, 'missingImage': 0, 'missingPrice': 0,
        'hiddenDuplicate': 0, 'quarantined': 0, 'rejected': 0,
        'publicInvisible': 0, 'strictHiddenNeedsReview': 0,
    }
    hidden_by_reason: dict[str, int] = {}
    visible_samples: list[dict] = []
    hidden_samples: list[dict] = []

    try:
        docs = db.collection('products').limit(limit).stream()
    except Exception:
        return {
            'config': config,
            'totalProductsScanned': 0,
            'error': 'Unable to read products',
            'generatedAt': generated_at,
        }

    for doc in docs:
        try:
            data = doc.to_dict() or {}
            data['id'] = doc.id
            counts['total'] += 1

            trust = str(data.get('trustStatus') or '').lower()
            admission = str(data.get('admissionStatus') or '').lower()
            flags = {str(f).lower() for f in (data.get('qualityFlags') or [])}
            price = _number(data.get('newPrice'))
            price_conf = str(data.get('priceConfidence') or '').lower()
            store = str(data.get('store') or data.get('source') or '')[:40]

            # aggregate quality counters (independent of filtering state)
            if trust == 'trusted':
                counts['trusted'] += 1
            if trust == 'needs_review' or admission == 'needs_review':
                counts['needsReview'] += 1
            if trust == 'quarantined':
                counts['quarantined'] += 1
            if trust == 'rejected' or admission == 'rejected':
                counts['rejected'] += 1
            if data.get('publicVisible') is False:
                counts['publicInvisible'] += 1
            if flags & {'missing_price', 'suspicious_price', 'missing_currency'} or price <= 0 or price_conf == 'missing':
                counts['priceReview'] += 1
            if 'missing_price' in flags or price <= 0:
                counts['missingPrice'] += 1
            if flags & {'missing_link', 'invalid_link'}:
                counts['missingLink'] += 1
            if 'missing_image' in flags:
                counts['missingImage'] += 1
            if data.get('hiddenAsDuplicate') or str(data.get('duplicateAction') or '').lower() == 'hidden':
                counts['hiddenDuplicate'] += 1

            decision = evaluate_public_product(data, config)
            if decision['visible']:
                counts['visible'] += 1
                if len(visible_samples) < 10:
                    visible_samples.append({
                        'id': doc.id,
                        'name': str(data.get('name') or '')[:60],
                        'store': store,
                        'publicRankScore': decision['rankScore'],
                        'trustStatus': trust,
                        'admissionStatus': admission,
                        'priceConfidence': price_conf,
                        'hiddenReason': decision.get('hiddenReason'),
                    })
            else:
                counts['hidden'] += 1
                reason = decision.get('hiddenReason') or 'unknown'
                hidden_by_reason[reason] = hidden_by_reason.get(reason, 0) + 1
                if reason == 'needs_review_hidden_strict':
                    counts['strictHiddenNeedsReview'] += 1
                if len(hidden_samples) < 10:
                    hidden_samples.append({
                        'id': doc.id,
                        'name': str(data.get('name') or '')[:60],
                        'store': store,
                        'hiddenReason': reason,
                        'trustStatus': trust,
                        'admissionStatus': admission,
                        'qualityFlags': list(flags)[:5],
                    })
        except Exception:
            continue

    return {
        'config': config,
        'totalProductsScanned': counts['total'],
        'visibleCount': counts['visible'],
        'hiddenCount': counts['hidden'],
        'hiddenByReason': hidden_by_reason,
        'trustedCount': counts['trusted'],
        'needsReviewCount': counts['needsReview'],
        'quarantinedCount': counts['quarantined'],
        'rejectedCount': counts['rejected'],
        'publicInvisibleCount': counts['publicInvisible'],
        'priceReviewCount': counts['priceReview'],
        'missingPriceCount': counts['missingPrice'],
        'missingLinkCount': counts['missingLink'],
        'missingImageCount': counts['missingImage'],
        'hiddenDuplicateCount': counts['hiddenDuplicate'],
        'strictHiddenNeedsReviewCount': counts['strictHiddenNeedsReview'],
        'topVisibleSamples': visible_samples,
        'hiddenSamples': hidden_samples,
        'generatedAt': generated_at,
    }


# ─── config update ────────────────────────────────────────────────────────────

_ALLOWED_CONFIG_KEYS = set(_DEFAULT_CONFIG.keys())


def update_catalog_config(updates: dict[str, Any], admin_uid: str, admin_email: str) -> dict[str, Any]:
    """
    Write allowed keys to app_config/catalog_governance.
    Rejects unknown keys. Writes an admin log entry.
    """
    clean: dict[str, Any] = {}
    for k, v in updates.items():
        if k not in _ALLOWED_CONFIG_KEYS:
            continue
        expected = type(_DEFAULT_CONFIG[k])
        if isinstance(v, expected):
            clean[k] = v

    if not clean:
        return {'ok': False, 'error': 'No valid config keys provided'}

    try:
        from datetime import datetime, timezone
        clean['updatedAt'] = datetime.now(timezone.utc).isoformat()
        clean['updatedBy'] = admin_uid
        db.collection('app_config').document('catalog_governance').set(clean, merge=True)
        invalidate_config_cache()
        try:
            db.collection('admin_logs').add({
                'adminUid': admin_uid,
                'adminEmail': admin_email,
                'action': 'catalog_config_update',
                'targetType': 'catalog_config',
                'targetId': 'catalog_governance',
                'note': str(clean),
                'createdAt': datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        return {'ok': True, 'updated': list(clean.keys())}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
