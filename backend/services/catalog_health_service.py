from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from core.firebase import db


_ACTIVE_STATUSES = {'active', 'approved', 'published'}
_TRUSTED_STATUSES = {'trusted', 'ok'}
_NEEDS_REVIEW_STATUSES = {'needs_review', 'review'}
_REJECTED_STATUSES = {'rejected', 'banned'}
_QUARANTINED_STATUSES = {'quarantined', 'blocked'}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or '').strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    text = _text(value)
    return text or None


def _latest(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    if not candidate:
        return current
    if not current or candidate > current:
        return candidate
    return current


def normalize_source_key(value: Any) -> str:
    return re.sub(r'[^a-z0-9_\-.]', '_', _lower(value))[:60]


def _source_identity(data: Dict[str, Any]) -> Dict[str, str]:
    domain = _lower(data.get('domain') or data.get('sourceDomain'))
    store = _text(data.get('store') or data.get('merchant'))
    source = _lower(
        data.get('source')
        or data.get('provider')
        or data.get('sourceType')
    )
    key = normalize_source_key(domain or store or source)
    return {
        'sourceKey': key,
        'source': source,
        'store': store,
        'domain': domain,
    }


def _empty_metrics(identity: Dict[str, str]) -> Dict[str, Any]:
    return {
        **identity,
        'totalProducts': 0,
        'activeCount': 0,
        'needsReviewCount': 0,
        'missingPriceCount': 0,
        'missingImageCount': 0,
        'missingLinkCount': 0,
        'rejectedCount': 0,
        'quarantinedCount': 0,
        'hiddenDuplicateCount': 0,
        'trustedCount': 0,
        '_qualityTotal': 0.0,
        '_qualitySamples': 0,
        '_rankTotal': 0.0,
        '_rankSamples': 0,
        'lastImportBatchId': None,
        'lastImportedAt': None,
    }


def calculate_source_trust(metrics: Dict[str, Any]) -> Dict[str, Any]:
    total = max(0, int(metrics.get('totalProducts') or 0))
    denominator = max(1, total)

    def ratio(field: str) -> float:
        return min(1.0, max(0.0, int(metrics.get(field) or 0) / denominator))

    score = 100.0
    score -= min(25.0, ratio('needsReviewCount') * 50.0)
    score -= min(20.0, ratio('missingPriceCount') * 40.0)
    score -= min(15.0, ratio('missingImageCount') * 30.0)
    score -= min(25.0, ratio('missingLinkCount') * 50.0)
    score -= min(
        30.0,
        (ratio('rejectedCount') + ratio('quarantinedCount')) * 60.0,
    )
    score -= min(15.0, ratio('hiddenDuplicateCount') * 30.0)

    trusted_ratio = ratio('trustedCount')
    average_quality = _number(metrics.get('averageQualityScore'))
    if trusted_ratio >= 0.80:
        score += 5.0
    if average_quality >= 80:
        score += 5.0

    confidence = 'high'
    if total < 5:
        confidence = 'low'
        # Tiny sources stay informative without jumping to an extreme score.
        sample_weight = total / 10.0
        score = 75.0 + ((score - 75.0) * sample_weight)
    elif total < 20:
        confidence = 'medium'

    trust_score = int(round(max(0.0, min(100.0, score))))
    if trust_score >= 85:
        trust_label = 'strong'
    elif trust_score >= 65:
        trust_label = 'stable'
    elif trust_score >= 40:
        trust_label = 'watch'
    else:
        trust_label = 'weak'

    return {
        'trustScore': trust_score,
        'trustLabel': trust_label,
        'confidence': confidence,
    }


def _product_flags(product: Dict[str, Any]) -> set[str]:
    raw = product.get('qualityFlags') or []
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {_lower(flag) for flag in raw}


def _has_image(product: Dict[str, Any]) -> bool:
    if _text(
        product.get('mainImage')
        or product.get('image')
        or product.get('imageUrl')
        or product.get('image_url')
    ):
        return True
    images = product.get('images') or product.get('imageUrls') or []
    return isinstance(images, list) and any(_text(image) for image in images)


def _has_link(product: Dict[str, Any]) -> bool:
    return bool(
        _text(
            product.get('affiliateUrl')
            or product.get('productUrl')
            or product.get('url')
            or product.get('link')
        )
    )


def _is_hidden_duplicate(product: Dict[str, Any]) -> bool:
    return (
        product.get('hiddenAsDuplicate') is True
        or _lower(product.get('duplicateAction')) == 'hidden'
        or _lower(product.get('duplicateStatus'))
        in {'hidden', 'hidden_as_duplicate'}
    )


def _iter_docs(collection: Any) -> Iterable[Any]:
    try:
        return collection.stream()
    except Exception:
        return ()


def _load_source_metadata(db_client: Any) -> Dict[str, Dict[str, str]]:
    metadata: Dict[str, Dict[str, str]] = {}
    try:
        docs = _iter_docs(db_client.collection('source_trust'))
    except Exception:
        return metadata
    for doc in docs:
        try:
            data = doc.to_dict() or {}
            identity = _source_identity(data)
            key = normalize_source_key(doc.id) or identity['sourceKey']
            if key:
                metadata[key] = {**identity, 'sourceKey': key}
        except Exception:
            continue
    return metadata


def _load_batch_metadata(db_client: Any) -> Dict[str, Dict[str, Any]]:
    latest_by_source: Dict[str, Dict[str, Any]] = {}
    for collection_name in ('import_batches', 'import_logs'):
        try:
            docs = _iter_docs(db_client.collection(collection_name))
        except Exception:
            continue
        for doc in docs:
            try:
                data = doc.to_dict() or {}
                identity = _source_identity(data)
                key = identity['sourceKey']
                if not key:
                    continue
                imported_at = _timestamp(
                    data.get('finishedAt')
                    or data.get('lastImportedAt')
                    or data.get('startedAt')
                    or data.get('createdAt')
                )
                current = latest_by_source.get(key)
                if current and _latest(
                    current.get('lastImportedAt'),
                    imported_at,
                ) == current.get('lastImportedAt'):
                    continue
                latest_by_source[key] = {
                    'lastImportBatchId': (
                        data.get('importBatchId')
                        or data.get('batchId')
                        or doc.id
                    ),
                    'lastImportedAt': imported_at,
                    **identity,
                }
            except Exception:
                continue
    return latest_by_source


def collect_source_metrics(
    source_key: Optional[str] = None,
    *,
    db_client: Any = None,
) -> list[Dict[str, Any]]:
    client = db_client or db
    wanted_key = normalize_source_key(source_key) if source_key else None
    source_metadata = _load_source_metadata(client)
    batch_metadata = _load_batch_metadata(client)
    metrics_by_source: Dict[str, Dict[str, Any]] = {}

    try:
        product_docs = _iter_docs(client.collection('products'))
    except Exception:
        product_docs = ()

    for doc in product_docs:
        try:
            product = doc.to_dict() or {}
            identity = _source_identity(product)
            key = identity['sourceKey']
            if not key or (wanted_key and key != wanted_key):
                continue
            metadata = source_metadata.get(key) or batch_metadata.get(key) or {}
            metrics = metrics_by_source.setdefault(
                key,
                _empty_metrics({**identity, **metadata, 'sourceKey': key}),
            )
            metrics['totalProducts'] += 1

            status = _lower(product.get('status') or 'active')
            trust = _lower(product.get('trustStatus'))
            admission = _lower(product.get('admissionStatus'))
            flags = _product_flags(product)

            if (
                status in _ACTIVE_STATUSES
                and product.get('isActive') is not False
                and product.get('visibleToUsers') is not False
            ):
                metrics['activeCount'] += 1
            if trust in _NEEDS_REVIEW_STATUSES or admission in _NEEDS_REVIEW_STATUSES:
                metrics['needsReviewCount'] += 1
            if (
                'missing_price' in flags
                or _number(product.get('newPrice') or product.get('price')) <= 0
            ):
                metrics['missingPriceCount'] += 1
            if 'missing_image' in flags or not _has_image(product):
                metrics['missingImageCount'] += 1
            if flags & {'missing_link', 'invalid_link'} or not _has_link(product):
                metrics['missingLinkCount'] += 1
            if (
                trust in _REJECTED_STATUSES
                or admission in _REJECTED_STATUSES
                or status in _REJECTED_STATUSES
            ):
                metrics['rejectedCount'] += 1
            if (
                trust in _QUARANTINED_STATUSES
                or admission in _QUARANTINED_STATUSES
            ):
                metrics['quarantinedCount'] += 1
            if _is_hidden_duplicate(product):
                metrics['hiddenDuplicateCount'] += 1
            if trust in _TRUSTED_STATUSES:
                metrics['trustedCount'] += 1

            quality = product.get('qualityScore')
            if quality is not None:
                metrics['_qualityTotal'] += _number(quality)
                metrics['_qualitySamples'] += 1
            rank = (
                product.get('publicRankScore')
                if product.get('publicRankScore') is not None
                else product.get('catalogRankScore')
            )
            if rank is not None:
                metrics['_rankTotal'] += _number(rank)
                metrics['_rankSamples'] += 1

            metrics['lastImportedAt'] = _latest(
                metrics.get('lastImportedAt'),
                _timestamp(product.get('lastImportedAt')),
            )
            if product.get('importBatchId') and (
                metrics['lastImportedAt']
                == _timestamp(product.get('lastImportedAt'))
            ):
                metrics['lastImportBatchId'] = product.get('importBatchId')
        except Exception:
            continue

    results: list[Dict[str, Any]] = []
    for key, metrics in metrics_by_source.items():
        batch = batch_metadata.get(key) or {}
        if _latest(
            metrics.get('lastImportedAt'),
            batch.get('lastImportedAt'),
        ) == batch.get('lastImportedAt'):
            metrics['lastImportedAt'] = batch.get('lastImportedAt')
            metrics['lastImportBatchId'] = batch.get('lastImportBatchId')

        quality_samples = max(1, int(metrics.pop('_qualitySamples')))
        rank_samples = max(1, int(metrics.pop('_rankSamples')))
        metrics['averageQualityScore'] = round(
            metrics.pop('_qualityTotal') / quality_samples,
            2,
        )
        metrics['averagePublicRankScore'] = round(
            metrics.pop('_rankTotal') / rank_samples,
            2,
        )
        results.append({**metrics, **calculate_source_trust(metrics)})

    return sorted(results, key=lambda item: item['sourceKey'])


def _catalog_summary(
    source_results: list[Dict[str, Any]],
    *,
    db_client: Any,
) -> Dict[str, Any]:
    summary = {
        'totalProducts': 0,
        'trustedProducts': 0,
        'needsReviewProducts': 0,
        'missingPriceProducts': 0,
        'missingImageProducts': 0,
        'missingLinkProducts': 0,
        'hiddenDuplicates': 0,
        'rejectedProducts': 0,
        'quarantinedProducts': 0,
        'publicVisibleFalse': 0,
        'sourcesCount': len(source_results),
        'weakSourcesCount': 0,
        'watchSourcesCount': 0,
        'strongSourcesCount': 0,
        'averageTrustScore': 0.0,
        'generatedAt': _now_iso(),
    }
    if source_results:
        summary['averageTrustScore'] = round(
            sum(item['trustScore'] for item in source_results)
            / len(source_results),
            2,
        )
    for item in source_results:
        label = item['trustLabel']
        if label == 'weak':
            summary['weakSourcesCount'] += 1
        elif label == 'watch':
            summary['watchSourcesCount'] += 1
        elif label == 'strong':
            summary['strongSourcesCount'] += 1

    try:
        docs = _iter_docs(db_client.collection('products'))
    except Exception:
        docs = ()
    for doc in docs:
        try:
            product = doc.to_dict() or {}
            summary['totalProducts'] += 1
            trust = _lower(product.get('trustStatus'))
            admission = _lower(product.get('admissionStatus'))
            status = _lower(product.get('status'))
            flags = _product_flags(product)
            if trust in _TRUSTED_STATUSES:
                summary['trustedProducts'] += 1
            if trust in _NEEDS_REVIEW_STATUSES or admission in _NEEDS_REVIEW_STATUSES:
                summary['needsReviewProducts'] += 1
            if (
                'missing_price' in flags
                or _number(product.get('newPrice') or product.get('price')) <= 0
            ):
                summary['missingPriceProducts'] += 1
            if 'missing_image' in flags or not _has_image(product):
                summary['missingImageProducts'] += 1
            if flags & {'missing_link', 'invalid_link'} or not _has_link(product):
                summary['missingLinkProducts'] += 1
            if _is_hidden_duplicate(product):
                summary['hiddenDuplicates'] += 1
            if (
                trust in _REJECTED_STATUSES
                or admission in _REJECTED_STATUSES
                or status in _REJECTED_STATUSES
            ):
                summary['rejectedProducts'] += 1
            if (
                trust in _QUARANTINED_STATUSES
                or admission in _QUARANTINED_STATUSES
            ):
                summary['quarantinedProducts'] += 1
            if product.get('publicVisible') is False:
                summary['publicVisibleFalse'] += 1
        except Exception:
            continue
    return summary


def get_catalog_health(*, db_client: Any = None) -> Dict[str, Any]:
    client = db_client or db
    results = collect_source_metrics(db_client=client)
    summary = _catalog_summary(results, db_client=client)
    weak = sorted(results, key=lambda item: item['trustScore'])[:5]
    strong = sorted(
        results,
        key=lambda item: item['trustScore'],
        reverse=True,
    )[:5]
    return {
        'summary': summary,
        'topWeakSources': weak,
        'topStrongSources': strong,
    }


_WRITE_FIELDS = (
    'trustScore',
    'trustLabel',
    'confidence',
    'totalProducts',
    'activeCount',
    'needsReviewCount',
    'missingPriceCount',
    'missingImageCount',
    'missingLinkCount',
    'rejectedCount',
    'quarantinedCount',
    'hiddenDuplicateCount',
    'trustedCount',
    'averageQualityScore',
    'averagePublicRankScore',
    'lastImportBatchId',
    'lastImportedAt',
)


def recalibrate_source_trust(
    *,
    source_key: Optional[str] = None,
    dry_run: bool = True,
    admin_uid: str = '',
    db_client: Any = None,
) -> Dict[str, Any]:
    client = db_client or db
    results = collect_source_metrics(
        source_key=source_key,
        db_client=client,
    )
    updated = 0
    errors: list[Dict[str, str]] = []
    recalibrated_at = _now_iso()
    if not dry_run:
        for result in results:
            payload = {field: result.get(field) for field in _WRITE_FIELDS}
            payload['recalibratedAt'] = recalibrated_at
            payload['recalibratedBy'] = admin_uid
            try:
                client.collection('source_trust').document(
                    result['sourceKey'],
                ).set(payload, merge=True)
                updated += 1
            except Exception as exc:
                errors.append({
                    'sourceKey': result['sourceKey'],
                    'error': str(exc)[:160],
                })

    return {
        'recalibratedSources': len(results),
        'updatedSources': updated,
        'dryRun': dry_run,
        'results': results[:10],
        'errors': errors[:10],
        'generatedAt': recalibrated_at,
    }
