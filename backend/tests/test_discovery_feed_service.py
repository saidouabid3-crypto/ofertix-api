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
    _is_usable,
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
    countries: list | None = None,
    source: str = 'manual',
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
        'countries': countries or [country],
        'source': source,
        'fingerprint': f"{store}|product-{id}|{price}",
    }


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
        # Use quality_score=50, link, no images (so neither hits 100 clamp)
        # trust='ok' so both get the +20, but big gets +15 more
        big = _product(id='d1', discount=60, trust='ok', quality_score=40,
                       images=['http://img.test/a.jpg', 'http://img.test/b.jpg'],
                       link='http://link.test')
        small = _product(id='d2', discount=10, trust='ok', quality_score=40,
                         images=['http://img.test/a.jpg', 'http://img.test/b.jpg'],
                         link='http://link.test')
        s_big = compute_discovery_score(big, day_seed=SEED, seen_ids=set())
        s_small = compute_discovery_score(small, day_seed=SEED, seen_ids=set())
        # big: 40+20+15+8+rotation(d1) vs small: 40+20+8+rotation(d2)
        # rotation diff at most 8, but big has +15 advantage → big > small
        assert s_big > s_small

    def test_seen_product_demoted(self):
        # qualityScore=40 leaves room: 40+20+8=68 unseen, 68-15=53 seen (gap=15>8 max rotation)
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
        # qualityScore=40, trust=ok, no extra bonuses → base ~68; rotation 0-8 varies per day
        p = _product(id='rotate-me', trust='ok', quality_score=40,
                     images=['a', 'b'], link='http://link.test', discount=10)
        scores = {
            compute_discovery_score(p, day_seed=f'2026-06-{d:02d}', seen_ids=set())
            for d in range(1, 10)
        }
        # 9 different day seeds → rotation_boost varies → at least 2 distinct scores
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
        p2['id'] = 'b'  # different id, same fingerprint
        result = _dedupe([p1, p2])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _apply_diversity
# ---------------------------------------------------------------------------

class TestApplyDiversity:
    def test_max_2_same_store_in_first_12_when_alternatives_exist(self):
        """When there are enough alternative-store products, first 12 caps same store at 2."""
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
        """When there are enough alternative-category products, first 12 caps same cat at 3."""
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
        """Small all-same-store catalog is returned fully (spec: fallback gracefully)."""
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
        """4 ShopA + 4 ShopB + 12 unique shops → first 12 has at most 2 from ShopA/B."""
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
# build_discovery_feed (with mocked Firestore + imports)
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
    Patches db, item_available_for_country, normalize_item_market_fields,
    and normalize_product AT the discovery_feed_service module level
    (where they were imported), so the patches actually take effect.
    """
    docs = [_make_doc(p) for p in CATALOG_30]
    with (
        patch('services.discovery_feed_service.db') as mock_db,
        patch(
            'services.discovery_feed_service.item_available_for_country',
            return_value=True,
        ),
        patch(
            'services.discovery_feed_service.normalize_item_market_fields',
            side_effect=lambda item, **kw: item,
        ),
        patch(
            'services.discovery_feed_service.normalize_product',
            side_effect=lambda item, **kw: item,
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
            assert pos > 0  # demoted — no longer first

    def test_quarantined_excluded(self, mock_firestore):
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
        # Catalog has 5 different stores — first 12 should have at most 2 per store
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
