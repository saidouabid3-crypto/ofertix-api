from services.catalog_health_service import (
    calculate_source_trust,
    get_catalog_health,
    recalibrate_source_trust,
)


def _metrics(**updates):
    base = {
        'totalProducts': 100,
        'activeCount': 100,
        'needsReviewCount': 0,
        'missingPriceCount': 0,
        'missingImageCount': 0,
        'missingLinkCount': 0,
        'rejectedCount': 0,
        'quarantinedCount': 0,
        'hiddenDuplicateCount': 0,
        'trustedCount': 90,
        'averageQualityScore': 85,
        'averagePublicRankScore': 80,
    }
    return {**base, **updates}


def test_quality_ratios_reduce_source_trust():
    healthy = calculate_source_trust(_metrics())
    degraded = calculate_source_trust(
        _metrics(
            needsReviewCount=70,
            missingPriceCount=50,
            missingLinkCount=60,
            trustedCount=10,
            averageQualityScore=45,
        )
    )

    assert healthy['trustScore'] > degraded['trustScore']
    assert degraded['trustLabel'] in {'watch', 'weak'}


def test_small_source_avoids_extreme_score_and_has_low_confidence():
    result = calculate_source_trust(
        _metrics(
            totalProducts=1,
            activeCount=0,
            needsReviewCount=1,
            missingPriceCount=1,
            missingImageCount=1,
            missingLinkCount=1,
            rejectedCount=1,
            trustedCount=0,
            averageQualityScore=0,
        )
    )

    assert result['confidence'] == 'low'
    assert 55 <= result['trustScore'] <= 75


class FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class FakeDocumentRef:
    def __init__(self, writes, collection_name, doc_id):
        self._writes = writes
        self._collection_name = collection_name
        self._doc_id = doc_id

    def set(self, payload, merge=False):
        self._writes.append(
            (self._collection_name, self._doc_id, payload, merge)
        )


class FakeCollection:
    def __init__(self, name, data, writes):
        self._name = name
        self._data = data
        self._writes = writes

    def stream(self):
        return iter(self._data.get(self._name, []))

    def document(self, doc_id):
        return FakeDocumentRef(
            self._writes,
            self._name,
            doc_id,
        )


class FakeDb:
    def __init__(self):
        self.writes = []
        self.data = {
            'products': [
                FakeDoc(
                    'p1',
                    {
                        'name': 'Good product',
                        'store': 'Store A',
                        'source': 'impact',
                        'status': 'active',
                        'newPrice': 25,
                        'image': 'https://example.com/image.jpg',
                        'affiliateUrl': 'https://example.com/deal',
                        'trustStatus': 'trusted',
                        'admissionStatus': 'approved',
                        'qualityScore': 90,
                        'catalogRankScore': 88,
                        'publicVisible': True,
                        'importBatchId': 'batch-1',
                        'lastImportedAt': '2026-06-08T10:00:00+00:00',
                    },
                ),
                FakeDoc(
                    'p2',
                    {
                        'name': 'Review product',
                        'store': 'Store A',
                        'source': 'impact',
                        'status': 'active',
                        'newPrice': 0,
                        'trustStatus': 'needs_review',
                        'admissionStatus': 'needs_review',
                        'qualityFlags': [
                            'missing_price',
                            'missing_image',
                            'missing_link',
                        ],
                        'qualityScore': 20,
                        'catalogRankScore': 15,
                        'publicVisible': False,
                    },
                ),
                FakeDoc(
                    'p3',
                    {
                        'name': 'Product without source metadata',
                        'status': 'active',
                        'newPrice': 15,
                        'image': 'https://example.com/image-3.jpg',
                        'affiliateUrl': 'https://example.com/deal-3',
                        'trustStatus': 'trusted',
                        'admissionStatus': 'approved',
                        'qualityScore': 82,
                        'catalogRankScore': 80,
                        'publicVisible': True,
                    },
                ),
            ],
            'import_batches': [
                FakeDoc(
                    'batch-1',
                    {
                        'importBatchId': 'batch-1',
                        'store': 'Store A',
                        'source': 'impact',
                        'finishedAt': '2026-06-08T10:00:00+00:00',
                    },
                ),
            ],
            'import_logs': [],
            'source_trust': [
                FakeDoc(
                    'store_a',
                    {
                        'store': 'Store A',
                        'source': 'impact',
                        'sourceTrustScore': 100,
                    },
                ),
            ],
        }

    def collection(self, name):
        return FakeCollection(name, self.data, self.writes)


def test_dry_run_does_not_write_and_result_structure_is_stable():
    fake_db = FakeDb()

    result = recalibrate_source_trust(
        dry_run=True,
        admin_uid='admin-1',
        db_client=fake_db,
    )

    assert fake_db.writes == []
    assert result['dryRun'] is True
    assert result['recalibratedSources'] == 1
    assert result['updatedSources'] == 0
    assert {
        'sourceKey',
        'trustScore',
        'trustLabel',
        'confidence',
        'totalProducts',
        'averageQualityScore',
        'averagePublicRankScore',
    }.issubset(result['results'][0])


def test_apply_writes_only_source_trust_documents():
    fake_db = FakeDb()

    result = recalibrate_source_trust(
        dry_run=False,
        admin_uid='admin-1',
        db_client=fake_db,
    )

    assert result['updatedSources'] == 1
    assert len(fake_db.writes) == 1
    collection, doc_id, payload, merge = fake_db.writes[0]
    assert collection == 'source_trust'
    assert doc_id == 'store_a'
    assert merge is True
    assert payload['recalibratedBy'] == 'admin-1'
    assert 'sourceTrustScoreAtImport' not in payload


def test_catalog_health_summary_shape():
    fake_db = FakeDb()

    health = get_catalog_health(db_client=fake_db)

    assert {
        'summary',
        'topWeakSources',
        'topStrongSources',
    } == set(health)
    assert health['summary']['totalProducts'] == 3
    assert health['summary']['trustedProducts'] == 2
    assert health['summary']['publicVisibleFalse'] == 1
    assert health['summary']['sourcesCount'] == 1
