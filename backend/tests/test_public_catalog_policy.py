from services.public_catalog_policy import (
    _DEFAULT_CONFIG,
    compute_rank_score,
    evaluate_public_product,
    public_catalog_preview,
)


def _config(**updates):
    return {**_DEFAULT_CONFIG, **updates}


def _needs_review_product():
    return {
        'name': 'Review product',
        'newPrice': 25,
        'trustStatus': 'needs_review',
        'admissionStatus': 'needs_review',
        'qualityFlags': [],
    }


def test_filtering_disabled_never_hides_product():
    product = {
        **_needs_review_product(),
        'qualityFlags': ['missing_link', 'missing_image', 'missing_price'],
        'publicVisible': False,
    }

    decision = evaluate_public_product(
        product,
        _config(
            publicFilteringEnabled=False,
            strictMode=True,
            hideNeedsReview=True,
            hideMissingLink=True,
            hideMissingImage=True,
            hideMissingPrice=True,
            hideExplicitPublicInvisible=True,
        ),
    )

    assert decision['visible'] is True
    assert decision['hiddenReason'] is None


def test_strict_mode_alone_does_not_hide_needs_review():
    decision = evaluate_public_product(
        _needs_review_product(),
        _config(publicFilteringEnabled=True, strictMode=True),
    )

    assert decision['visible'] is True


def test_hide_needs_review_alone_does_not_hide_needs_review():
    decision = evaluate_public_product(
        _needs_review_product(),
        _config(publicFilteringEnabled=True, hideNeedsReview=True),
    )

    assert decision['visible'] is True


def test_strict_mode_and_hide_needs_review_hide_with_explicit_reason():
    decision = evaluate_public_product(
        _needs_review_product(),
        _config(
            publicFilteringEnabled=True,
            strictMode=True,
            hideNeedsReview=True,
        ),
    )

    assert decision['visible'] is False
    assert decision['hiddenReason'] == 'needs_review_hidden_strict'


def test_safe_defaults_keep_all_hide_flags_disabled():
    assert _DEFAULT_CONFIG['publicFilteringEnabled'] is False
    assert _DEFAULT_CONFIG['hideQuarantined'] is False
    assert _DEFAULT_CONFIG['hideHiddenDuplicates'] is False
    assert _DEFAULT_CONFIG['hideRejected'] is False
    assert _DEFAULT_CONFIG['hideExplicitPublicInvisible'] is False
    assert _DEFAULT_CONFIG['hideMissingLink'] is False
    assert _DEFAULT_CONFIG['hideMissingImage'] is False
    assert _DEFAULT_CONFIG['hideMissingPrice'] is False
    assert _DEFAULT_CONFIG['hideNeedsReview'] is False


def test_needs_review_demotion_can_be_disabled():
    product = _needs_review_product()

    demoted = compute_rank_score(product, _config(demoteNeedsReview=True))
    not_demoted = compute_rank_score(
        product,
        _config(demoteNeedsReview=False),
    )

    assert not_demoted - demoted == 15


def test_limited_info_demotion_can_be_disabled():
    product = {
        'newPrice': 25,
        'qualityFlags': ['missing_link', 'missing_image'],
    }

    demoted = compute_rank_score(product, _config(demoteLimitedInfo=True))
    not_demoted = compute_rank_score(
        product,
        _config(demoteLimitedInfo=False),
    )

    assert not_demoted - demoted == 45


def test_preview_exposes_metrics_reasons_and_bounded_samples(monkeypatch):
    class FakeDoc:
        def __init__(self, doc_id, data):
            self.id = doc_id
            self._data = data

        def to_dict(self):
            return self._data

    class FakeCollection:
        def __init__(self, docs):
            self._docs = docs

        def limit(self, _limit):
            return self

        def stream(self):
            return iter(self._docs)

    class FakeDb:
        def __init__(self, docs):
            self._docs = docs

        def collection(self, name):
            assert name == 'products'
            return FakeCollection(self._docs)

    docs = [
        FakeDoc(
            'visible-1',
            {
                'name': 'Trusted product',
                'store': 'Store A',
                'newPrice': 50,
                'trustStatus': 'trusted',
                'admissionStatus': 'approved',
                'priceConfidence': 'high',
                'qualityFlags': [],
            },
        ),
        FakeDoc(
            'hidden-1',
            {
                'name': 'Review product',
                'store': 'Store B',
                'newPrice': 25,
                'trustStatus': 'needs_review',
                'admissionStatus': 'needs_review',
                'priceConfidence': 'missing',
                'qualityFlags': ['missing_price', 'missing_image'],
            },
        ),
    ]
    config = _config(
        publicFilteringEnabled=True,
        strictMode=True,
        hideNeedsReview=True,
    )

    monkeypatch.setattr(
        'services.public_catalog_policy.load_catalog_config',
        lambda: config,
    )
    monkeypatch.setattr(
        'services.public_catalog_policy.db',
        FakeDb(docs),
    )

    preview = public_catalog_preview()

    assert preview['totalProductsScanned'] == 2
    assert preview['visibleCount'] == 1
    assert preview['hiddenCount'] == 1
    assert preview['strictHiddenNeedsReviewCount'] == 1
    assert preview['missingPriceCount'] == 1
    assert preview['missingImageCount'] == 1
    assert preview['hiddenByReason'] == {
        'needs_review_hidden_strict': 1,
    }
    assert preview['topVisibleSamples'][0]['publicRankScore'] >= 0
    assert preview['hiddenSamples'][0]['hiddenReason'] == (
        'needs_review_hidden_strict'
    )
    assert len(preview['topVisibleSamples']) <= 10
    assert len(preview['hiddenSamples']) <= 10
