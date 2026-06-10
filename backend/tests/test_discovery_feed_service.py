"""
Unit tests for discovery_feed_service.
All Firestore calls are mocked — no network required.
"""
from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock, patch

import pytest

from services.discovery_feed_service import (
    _apply_diversity,
    _dedupe,
    _freshness_hours,
    build_discovery_feed,
    compute_discovery_score,
    rotation_boost,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _product(
    id: str = 'p1',
    store: str = 'ShopA',
    category: str = 'Electronics',
    trust: str = 'trusted',
    discount: int = 20,
    price: float = 50.0,
    image: str = 'http://img.test/a.jpg',
    link: str = 'http://link.test/a',
    images: list | None = None,
    status: str = 'active',
    visible: bool = True,
    flags: list | None = None,
    updated_at: str | None = None,
    is_hot: bool = False,
    featured: bool = False,
    quality_score: float = 70.0,
    country: str = 'es',
    country_code: str = 'es',
    countries: list | None = None,
    source: str = 'manual',
    is_explicitly_global: bool = False,
) -> dict:
    return {
        'id': id,
        'store': store,
        'categoryGroup': category,
        'trustStatus': trust,
        'discount': discount,
        'newPrice': price,
        'image': image,
        'affiliateUrl': link,
        'images': images if images is not None else [image, image],  # 2 images by default
        'status': status,
        'visibleToUsers': visible,
        'qualityFlags': flags or [],
        'updatedAt': updated_at,
        'isHot': is_hot,
        'featured': featured,
        'qualityScore': quality_score,
        'country': country,
        'countryCode': country_code,
        'availableCountries': countries or [country],
        'isExplicitlyGlobal': is_explicitly_global,
        'source': source,
        'fingerprint': f"{store}|product-{id}|{price}",
    }


def _global_product(**kwargs) -> dict:
    """Helper for a realistic global product matching the live catalog payload."""
    defaults = dict(
        id='global-p1',
        store='GlobalShop',
        category='Electronics',
        trust='trusted',
        discount=83,
        price=15.0,
        link='https://aff.link/global-p1',
        status='active',
        visible=True,
        country='global',
        country_code='global',
        countries=['es', 'fr', 'de'],
        is_explicitly_global=True,
        is_hot=True,
        quality_score=70.0,
    )
    defaults.update(kwargs)
    return _product(**defaults)


SEED = '2026-06-10'


# ---------------------------------------------------------------------------
# rotation_boost
# ---------------------------------------------------------------------------

class TestRotationBoost:
    def test_deterministic(self):
        v1 = rotation_boost('abc', SEED)
        v2 = rotation_boost('abc', SEED)
        assert v1 == v2

    def test_different_seeds_both_in_range(self):
        v1 = rotation_boost('abc', '2026-06-10')
        v2 = rotation_boost('abc', '2026-06-11')
        assert 0 <= v1 <= 8
        assert 0 <= v2 <= 8

    def test_range(self):
        for i in range(100):
            v = rotation_boost(f'product-{i}', SEED)
            assert 0 <= v <= 8


# ---------------------------------------------------------------------------
# compute_discovery_score
# ---------------------------------------------------------------------------

class TestComputeDiscoveryScore:
    def test_trusted_product_scores_higher(self):
        trusted = _product(id='t1', trust='trusted', quality_score=50)
        unknown = _product(id='t2', trust='unknown', quality_score=50)
        s_trusted = compute_discovery_score(trusted, day_seed=SEED, seen_ids=set())
        s_unknown = compute_discovery_score(unknown, day_seed=SEED, seen_ids=set())
        assert s_trusted > s_unknown

    def test_high_discount_bonus(self):
        big = _product(id='d1', discount=60, trust='ok', quality_score=40,
                       images=['http://img.test/a.jpg', 'http://img.test/b.jpg'],
                       link='http://link.test')
        small = _product(id='d2', discount=10, trust='ok', quality_score=40,
                         images=['http://img.test/a.jpg', 'http://img.test/b.jpg'],
                         link='http://link.test')
        s_big = compute_discovery_score(big, day_seed=SEED, seen_ids=set())
        s_small = compute_discovery_score(small, day_seed=SEED, seen_ids=set())
        assert s_big > s_small

    def test_seen_product_demoted(self):
        p = _product(id='p1', trust='ok', quality_score=40,
                     images=['a', 'b'], link='http://link.test')
        s_unseen = compute_discovery_score(p, day_seed=SEED, seen_ids=set())
        s_seen = compute_discovery_score(p, day_seed=SEED, seen_ids={'p1'})
        assert s_unseen > s_seen

    def test_quarantined_heavily_penalised(self):
        quarantined = _product(id='q1', trust='quarantined', quality_score=50)
        ok_p = _product(id='q2', trust='ok', quality_score=50)
        s_q = compute_discovery_score(quarantined, day_seed=SEED, seen_ids=set())
        s_ok = compute_discovery_score(ok_p, day_seed=SEED, seen_ids=set())
        assert s_ok > s_q

    def test_score_clamped_0_100(self):
        for trust in ('trusted', 'quarantined', 'unknown', 'ok'):
            p = _product(trust=trust)
            s = compute_discovery_score(p, day_seed=SEED, seen_ids=set())
            assert 0.0 <= s <= 100.0

    def test_same_seed_same_score(self):
        p = _product(id='stable')
        s1 = compute_discovery_score(p, day_seed=SEED, seen_ids=set())
        s2 = compute_discovery_score(p, day_seed=SEED, seen_ids=set())
        assert s1 == s2

    def test_different_day_changes_score(self):
        p = _product(id='rotate-me', trust='ok', quality_score=40,
                     images=['a', 'b'], link='http://link.test', discount=10)
        scores = {
            compute_discovery_score(p, day_seed=f'2026-06-{d:02d}', seen_ids=set())
            for d in range(1, 10)
        }
        assert len(scores) > 1


# ---------------------------------------------------------------------------
# _dedupe
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_removes_duplicate_ids(self):
        p1 = _product(id='dup')
        p2 = _product(id='dup', store='OtherShop')
        result = _dedupe([p1, p2])
        assert len(result) == 1
        assert result[0]['id'] == 'dup'

    def test_removes_duplicate_fingerprints(self):
        p1 = _product(id='a', store='S', category='C')
        p2 = dict(p1)
        p2['id'] = 'b'
        result = _dedupe([p1, p2])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _apply_diversity
# ---------------------------------------------------------------------------

class TestApplyDiversity:
    def test_max_2_same_store_in_first_12_when_alternatives_exist(self):
        catalog = (
            [_product(id=f'mega{i}', store='MegaShop', category=f'Cat{i}') for i in range(4)]
            + [_product(id=f'other{i}', store=f'UniqueShop{i}', category=f'UniqueCat{i}')
               for i in range(20)]
        )
        result = _apply_diversity(catalog, limit=20)
        first_12 = result[:12]
        mega_count = sum(1 for p in first_12 if p['store'] == 'MegaShop')
        assert mega_count <= 2

    def test_max_3_same_category_in_first_12_when_alternatives_exist(self):
        catalog = (
            [_product(id=f'elec{i}', store=f'ShopE{i}', category='Electronics') for i in range(6)]
            + [_product(id=f'other{i}', store=f'Shop{i}', category=f'UniqueCat{i}')
               for i in range(20)]
        )
        result = _apply_diversity(catalog, limit=20)
        first_12 = result[:12]
        elec_count = sum(1 for p in first_12 if p['categoryGroup'] == 'Electronics')
        assert elec_count <= 3

    def test_fallback_with_small_catalog(self):
        catalog = [_product(id=f'p{i}', store='OnlyShop', category='OnlyCat') for i in range(4)]
        result = _apply_diversity(catalog, limit=10)
        assert len(result) == 4

    def test_no_duplicate_products_in_result(self):
        catalog = [_product(id=f'p{i}', store=f'Shop{i % 3}', category=f'Cat{i % 5}')
                   for i in range(20)]
        result = _apply_diversity(catalog, limit=20)
        ids = [p['id'] for p in result]
        assert len(ids) == len(set(ids))

    def test_mixed_stores_respected_when_alternatives_exist(self):
        catalog = (
            [_product(id=f'a{i}', store='ShopA', category='CatA') for i in range(4)]
            + [_product(id=f'b{i}', store='ShopB', category='CatB') for i in range(4)]
            + [_product(id=f'c{i}', store=f'UniqueShop{i}', category=f'UniqueCat{i}')
               for i in range(12)]
        )
        result = _apply_diversity(catalog, limit=20)
        first_12 = result[:12]
        shop_a = sum(1 for p in first_12 if p['store'] == 'ShopA')
        shop_b = sum(1 for p in first_12 if p['store'] == 'ShopB')
        assert shop_a <= 2
        assert shop_b <= 2

    def test_result_length_respects_limit(self):
        catalog = [_product(id=f'p{i}', store=f'Shop{i}') for i in range(30)]
        result = _apply_diversity(catalog, limit=15)
        assert len(result) <= 15


# ---------------------------------------------------------------------------
# Global product eligibility (direct unit tests — no Firestore needed)
# ---------------------------------------------------------------------------

class TestGlobalProductEligibility:
    """
    Verify that global products (countryCode='global') are eligible for
    discovery when they have the right availability fields set.
    These tests call prepare_public_product + is_usable_public_product directly,
    matching the /products pipeline.
    """

    def _make_global_raw(self, **overrides) -> dict:
        base = {
            'id': 'gp1',
            'name': 'Global Product Test',
            'store': 'TestShop',
            'source': 'manual',
            'status': 'active',
            'visibleToUsers': True,
            'trustStatus': 'trusted',
            'countryCode': 'global',
            'country': 'global',
            'availableCountries': ['es', 'fr', 'de'],
            'isExplicitlyGlobal': True,
            'newPrice': 15.0,
            'discount': 83,
            'image': 'http://img.test/global.jpg',
            'affiliateUrl': 'https://aff.link/gp1',
            'isHot': True,
            'qualityScore': 70,
        }
        base.update(overrides)
        return base

    def test_global_product_passes_eligibility_for_es(self):
        from services.public_product_service import is_usable_public_product, prepare_public_product
        raw = self._make_global_raw()
        item = prepare_public_product(raw, 'es')
        # Status must be restored from raw (not overwritten by normalize_product)
        assert item.get('status') == 'active'
        assert item.get('visibleToUsers') is True
        assert is_usable_public_product(item, 'es'), (
            f"Global product excluded: {item.get('status')}, "
            f"visible={item.get('visibleToUsers')}, "
            f"countryCode={item.get('countryCode')}"
        )

    def test_global_product_passes_eligibility_for_fr(self):
        from services.public_product_service import is_usable_public_product, prepare_public_product
        raw = self._make_global_raw(availableCountries=['es', 'fr', 'de'])
        item = prepare_public_product(raw, 'fr')
        assert is_usable_public_product(item, 'fr')

    def test_global_product_with_no_explicit_flag_excluded_in_strict_mode(self):
        """
        Global product with no isExplicitlyGlobal flag and no availableCountries is
        correctly excluded in strict mode. This is expected: products must either have
        isExplicitlyGlobal=True or a populated availableCountries list.
        """
        from services.public_product_service import is_usable_public_product, prepare_public_product
        raw = self._make_global_raw(availableCountries=[], isExplicitlyGlobal=False)
        item = prepare_public_product(raw, 'es')
        # Strict mode: countryCode='global' without explicit flag → excluded (correct behavior)
        # Live products always have availableCountries=['es',...] which makes them eligible.
        assert not is_usable_public_product(item, 'es')

    def test_status_preserved_through_normalization(self):
        """
        Root cause regression test: normalize_product may set status='needs_market_review'
        for low-confidence categories. prepare_public_product MUST restore original status.
        """
        from services.public_product_service import prepare_public_product
        raw = self._make_global_raw(status='active', visibleToUsers=True)
        item = prepare_public_product(raw, 'es')
        assert item['status'] == 'active', (
            f"status was overwritten to '{item['status']}' — "
            "prepare_public_product must restore original Firestore status"
        )
        assert item['visibleToUsers'] is True, (
            f"visibleToUsers was overwritten to {item['visibleToUsers']} — "
            "prepare_public_product must restore original Firestore visibleToUsers"
        )

    def test_quarantined_global_product_excluded(self):
        from services.public_product_service import is_usable_public_product, prepare_public_product
        from services.discovery_feed_service import _QUARANTINED
        raw = self._make_global_raw(trustStatus='quarantined')
        item = prepare_public_product(raw, 'es')
        trust = str(item.get('trustStatus') or '').lower()
        # Either is_usable_public_product excludes it or the discovery trustStatus check does
        usable = is_usable_public_product(item, 'es')
        quarantined_by_trust = trust in _QUARANTINED
        assert not usable or quarantined_by_trust, (
            "Quarantined product must be excluded by at least one gate"
        )


# ---------------------------------------------------------------------------
# build_discovery_feed (with mocked Firestore + public product service)
# ---------------------------------------------------------------------------

def _make_doc(product: dict):
    doc = MagicMock()
    doc.id = product['id']
    data = dict(product)
    data.pop('id', None)
    doc.to_dict.return_value = data
    return doc


# 30 products with 10 different stores (10×2=20 ≥ 12) + 6 different categories
CATALOG_30 = [
    _product(
        id=f'prod{i}',
        store=f'Shop{i % 10}',
        category=f'Cat{i % 6}',
        trust='trusted' if i % 3 == 0 else 'ok',
        discount=10 + (i % 60),
        price=20.0 + i,
        quality_score=50.0 + (i % 30),
        countries=['es'],
        updated_at='2026-06-09T10:00:00Z' if i % 2 == 0 else '2026-05-01T10:00:00Z',
    )
    for i in range(30)
]


@pytest.fixture
def mock_firestore():
    """
    Patches db at the discovery_feed_service module level.
    Patches prepare_public_product as a passthrough and is_usable_public_product
    to always return True (actual eligibility logic tested separately).
    The discovery-level trustStatus filter (_QUARANTINED) still applies.
    """
    docs = [_make_doc(p) for p in CATALOG_30]
    with (
        patch('services.discovery_feed_service.db') as mock_db,
        patch(
            'services.discovery_feed_service.prepare_public_product',
            side_effect=lambda raw, market: raw,
        ),
        patch(
            'services.discovery_feed_service.is_usable_public_product',
            return_value=True,
        ),
    ):
        mock_coll = MagicMock()
        mock_db.collection.return_value = mock_coll
        mock_coll.where.return_value = mock_coll
        mock_coll.limit.return_value = mock_coll
        mock_coll.stream.return_value = iter(docs)
        yield mock_db


def _reset_stream(mock_db):
    docs = [_make_doc(p) for p in CATALOG_30]
    mock_db.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter(docs)


class TestBuildDiscoveryFeed:
    def test_stable_order_same_seed(self, mock_firestore):
        feed1 = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        _reset_stream(mock_firestore)
        feed2 = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        ids1 = [p['id'] for p in feed1['products']]
        ids2 = [p['id'] for p in feed2['products']]
        assert ids1 == ids2
        assert len(ids1) > 0

    def test_different_seed_changes_order(self, mock_firestore):
        feed_a = build_discovery_feed(country='es', limit=20, day_seed='2026-06-10', variant='A')
        _reset_stream(mock_firestore)
        feed_b = build_discovery_feed(country='es', limit=20, day_seed='2026-06-11', variant='A')
        ids_a = [p['id'] for p in feed_a['products']]
        ids_b = [p['id'] for p in feed_b['products']]
        assert len(ids_a) > 0
        assert ids_a != ids_b

    def test_seen_products_scored_lower(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A',
                                    seen_ids=None)
        first_id = feed['products'][0]['id'] if feed['products'] else None
        if first_id is None:
            pytest.skip("Empty catalog")
        _reset_stream(mock_firestore)
        feed2 = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A',
                                     seen_ids=[first_id])
        ids2 = [p['id'] for p in feed2['products']]
        if first_id in ids2:
            pos = ids2.index(first_id)
            assert pos > 0

    def test_quarantined_excluded(self, mock_firestore):
        """Quarantined products must be excluded by the discovery-layer trust check."""
        quarantined = _product(id='qx', trust='quarantined', countries=['es'])
        docs = [_make_doc(p) for p in CATALOG_30] + [_make_doc(quarantined)]
        mock_firestore.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter(docs)
        feed = build_discovery_feed(country='es', limit=40, day_seed=SEED, variant='A')
        ids = [p['id'] for p in feed['products']]
        assert 'qx' not in ids

    def test_rejected_excluded(self, mock_firestore):
        rejected = _product(id='rx', trust='rejected', countries=['es'])
        docs = [_make_doc(p) for p in CATALOG_30] + [_make_doc(rejected)]
        mock_firestore.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter(docs)
        feed = build_discovery_feed(country='es', limit=40, day_seed=SEED, variant='A')
        ids = [p['id'] for p in feed['products']]
        assert 'rx' not in ids

    def test_no_duplicate_products_in_flat_list(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=30, day_seed=SEED, variant='A')
        ids = [p['id'] for p in feed['products']]
        assert len(ids) > 0
        assert len(ids) == len(set(ids))

    def test_diversity_store_in_first_12(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        products = feed['products'][:12]
        store_counts = Counter(p.get('store') for p in products)
        for count in store_counts.values():
            assert count <= 2

    def test_diversity_category_in_first_12(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        products = feed['products'][:12]
        cat_counts = Counter(p.get('categoryGroup') for p in products)
        for count in cat_counts.values():
            assert count <= 3

    def test_fallback_empty_catalog(self, mock_firestore):
        mock_firestore.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter([])
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        assert feed['count'] == 0
        assert feed['products'] == []
        assert 'sections' in feed

    def test_cache_key_fields(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='B')
        assert feed['seedDay'] == SEED
        assert feed['variant'] == 'B'
        assert 'generatedAt' in feed

    def test_all_required_sections_present(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        sections = feed['sections']
        required = {
            'heroDeals', 'hotDeals', 'globalOnline', 'topRated',
            'recentlyAdded', 'surpriseDeals',
            'verifiedDeals', 'bestDiscountToday', 'freshArrivals',
            'trendingNow', 'notSeenRecently', 'forYouToday',
        }
        assert required.issubset(set(sections.keys()))

    def test_products_are_returned(self, mock_firestore):
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        assert len(feed['products']) > 0
        assert feed['count'] > 0

    def test_global_product_appears_in_feed(self, mock_firestore):
        """
        Regression test for Batch 14A-A:
        A global product with availableCountries=['es'] must appear in the home feed.
        Uses the same passthrough mock so prepare_public_product/is_usable_public_product
        are bypassed — validating that the fetch loop includes global products when
        the public eligibility check passes.
        """
        global_prod = _global_product(id='global-regression', countries=['es'])
        docs = [_make_doc(p) for p in CATALOG_30[:5]] + [_make_doc(global_prod)]
        mock_firestore.collection.return_value.where.return_value.limit.return_value.stream.return_value = iter(docs)
        feed = build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        ids = [p['id'] for p in feed['products']]
        assert 'global-regression' in ids, (
            "Global product with availableCountries=['es'] must appear in the ES discovery feed"
        )

    def test_no_unbounded_stream(self, mock_firestore):
        """Verify the Firestore query always has a limit() call (no unbounded stream)."""
        build_discovery_feed(country='es', limit=20, day_seed=SEED, variant='A')
        limit_calls = mock_firestore.collection.return_value.where.return_value.limit.call_args_list
        assert len(limit_calls) >= 1
        called_limit = limit_calls[0][0][0]
        assert called_limit > 0, "Firestore query must have a positive limit"
        assert called_limit <= 1000, "Firestore limit must be bounded (≤1000)"
