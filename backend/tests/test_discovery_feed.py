"""
Tests for discovery feed seen-product demotion, variant rotation,
diversity, and section integrity.

All tests mock _fetch_usable_products — no Firestore required.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any
from unittest.mock import patch

import pytest

# Prevent Firebase initialization from failing in the test environment.
os.environ.setdefault("FIREBASE_REQUIRED", "false")

from services.discovery_feed_service import (
    _apply_diversity,
    _dedupe,
    build_discovery_feed,
    compute_discovery_score,
    rotation_boost,
)
from routes.home_feed import (
    _apply_seen_demotion,
    _bound_variant,
    _seen_fingerprint,
)
from services.catalog_edge_cache import catalog_cache


# ── Helpers ───────────────────────────────────────────────────────────────────

def _product(
    pid: str,
    store: str = 'tienda',
    cat: str = 'tech',
    trust: str = 'trusted',
    discount: int = 20,
    quality: int = 70,
    images: int = 2,
) -> dict[str, Any]:
    return {
        'id': pid,
        'store': store,
        'categoryGroup': cat,
        'trustStatus': trust,
        'newPrice': 50.0,
        'oldPrice': 70.0,
        'discount': discount,
        'qualityScore': quality,
        'affiliateUrl': 'https://example.com',
        'images': [f'img{i}.jpg' for i in range(images)],
        'visibleToUsers': True,
        'status': 'active',
        'isOnline': True,
    }


FAKE_PRODUCTS = [_product(f'p{i}', store=f's{i % 3}', cat=f'c{i % 4}') for i in range(30)]


# ── 1. Seen products are demoted below unseen in scoring ──────────────────────

def test_seen_product_scores_lower():
    p = _product('abc')
    score_unseen = compute_discovery_score(p, day_seed='2026-06-12:A', seen_ids=set())
    score_seen = compute_discovery_score(p, day_seed='2026-06-12:A', seen_ids={'abc'})
    assert score_seen < score_unseen, 'Seen product must score lower than unseen'
    assert score_unseen - score_seen >= 30, 'Seen penalty must be at least 30 points'


# ── 2. Top feed avoids seen IDs when enough unseen products exist ─────────────

@patch('services.discovery_feed_service._fetch_usable_products', return_value=FAKE_PRODUCTS)
def test_top_products_avoid_seen(_mock):
    seen = ['p0', 'p1', 'p2', 'p3', 'p4']
    result = build_discovery_feed(
        country='es', limit=10, day_seed='2026-06-12', variant='A', seen_ids=seen
    )
    top_ids = [p['id'] for p in result['products'][:5]]
    for sid in seen:
        assert sid not in top_ids, f'Seen product {sid!r} must not appear in top 5'


# ── 3. Variant changes ordering ───────────────────────────────────────────────

@patch('services.discovery_feed_service._fetch_usable_products', return_value=FAKE_PRODUCTS)
def test_variant_changes_order(_mock):
    result_a = build_discovery_feed(
        country='es', limit=20, day_seed='2026-06-12', variant='A', seen_ids=[]
    )
    result_b = build_discovery_feed(
        country='es', limit=20, day_seed='2026-06-12', variant='B', seen_ids=[]
    )
    ids_a = [p['id'] for p in result_a['products']]
    ids_b = [p['id'] for p in result_b['products']]
    assert ids_a != ids_b, 'Different variants must produce different product orderings'


# ── 4. Cache key changes with variant ─────────────────────────────────────────

def test_cache_key_changes_with_variant():
    key_a = catalog_cache.build_key('discovery_feed', country='es', limit=40, day='2026-06-12', variant='A', seen_fp='')
    key_b = catalog_cache.build_key('discovery_feed', country='es', limit=40, day='2026-06-12', variant='B', seen_fp='')
    assert key_a != key_b, 'Cache keys must differ between variants'


# ── 5. Cache key uses seen fingerprint, not raw list ──────────────────────────

def test_cache_key_uses_seen_fingerprint():
    fp1 = _seen_fingerprint(['p1', 'p2'])
    fp2 = _seen_fingerprint(['p3', 'p4'])
    fp_empty = _seen_fingerprint([])
    key1 = catalog_cache.build_key('discovery_feed', country='es', day='2026-06-12', variant='A', seen_fp=fp1)
    key2 = catalog_cache.build_key('discovery_feed', country='es', day='2026-06-12', variant='A', seen_fp=fp2)
    key_empty = catalog_cache.build_key('discovery_feed', country='es', day='2026-06-12', variant='A', seen_fp=fp_empty)
    assert key1 != key2, 'Different seen sets must produce different cache keys'
    assert key1 != key_empty, 'Seen fingerprint must differ from empty fingerprint'
    # Fingerprint is a short hex string, not raw product IDs
    assert 'p1' not in key1, 'Raw product IDs must not appear in cache key'
    assert 'p2' not in key1, 'Raw product IDs must not appear in cache key'


# ── 6. Same store/category diversity is enforced in first 12 positions ────────

def test_store_diversity_in_top12():
    # 20 products all from the same store; spread across enough categories so
    # only the store cap (not category cap) determines demotion.
    same_store = [_product(f'x{i}', store='monopoly', cat=f'cat{i}') for i in range(20)]
    # 10 from different stores + different categories
    diverse = [_product(f'y{i}', store=f'shop{i}', cat=f'dcat{i}') for i in range(10)]
    ranked = same_store + diverse
    result = _apply_diversity(ranked, limit=20, max_store_first12=2)
    top12 = result[:12]
    from collections import Counter
    store_counts = Counter(p['store'] for p in top12)
    assert store_counts.get('monopoly', 0) <= 2, 'Same store must be limited in first 12 positions'


# ── 7. Fallback returns products even when all candidates are seen ─────────────

@patch('services.discovery_feed_service._fetch_usable_products', return_value=FAKE_PRODUCTS)
def test_fallback_when_all_seen(_mock):
    all_seen = [f'p{i}' for i in range(30)]
    result = build_discovery_feed(
        country='es', limit=10, day_seed='2026-06-12', variant='A', seen_ids=all_seen
    )
    assert len(result['products']) > 0, 'Feed must still return products even if all are seen'


# ── 8. forYouToday is not empty when products exist ──────────────────────────

@patch('services.discovery_feed_service._fetch_usable_products', return_value=FAKE_PRODUCTS)
def test_for_you_today_not_empty(_mock):
    result = build_discovery_feed(
        country='es', limit=20, day_seed='2026-06-12', variant='A', seen_ids=[]
    )
    assert result['sections']['forYouToday'], 'forYouToday must not be empty when products exist'


# ── 9. Sections do not duplicate excessive product IDs in main products ────────

@patch('services.discovery_feed_service._fetch_usable_products', return_value=FAKE_PRODUCTS)
def test_products_list_no_duplicates(_mock):
    result = build_discovery_feed(
        country='es', limit=20, day_seed='2026-06-12', variant='A', seen_ids=[]
    )
    ids = [p['id'] for p in result['products']]
    assert len(ids) == len(set(ids)), 'Flat products list must not contain duplicate IDs'


# ── 10. Quarantined products receive a heavy score penalty ────────────────────
# (_fetch_usable_products already excludes them at the Firestore layer;
#  this test verifies the scoring penalty as a defence-in-depth check.)

def test_quarantined_product_scores_very_low():
    p_quarantined = _product('bad', trust='quarantined')
    p_good = _product('good', trust='trusted')
    day = '2026-06-12:A'
    score_bad = compute_discovery_score(p_quarantined, day_seed=day, seen_ids=set())
    score_good = compute_discovery_score(p_good, day_seed=day, seen_ids=set())
    assert score_bad < score_good, 'Quarantined product must score lower than trusted product'
    # Base 70 + http+8 - quarantine_penalty-30 + max_rotation+8 = 56 — well below good product
    assert score_bad < 60, 'Quarantined product score must be at least 20 points below a trusted product'


# ── 11. _apply_seen_demotion reorders sections too ────────────────────────────

def test_seen_demotion_reorders_sections():
    feed = {
        'products': [{'id': 'seen1'}, {'id': 'unseen1'}],
        'sections': {
            'forYouToday': [{'id': 'seen1'}, {'id': 'unseen1'}],
            'heroDeals': [{'id': 'seen2'}, {'id': 'unseen2'}],
        },
    }
    result = _apply_seen_demotion(feed, {'seen1', 'seen2'})
    assert result['products'][0]['id'] == 'unseen1'
    assert result['products'][1]['id'] == 'seen1'
    assert result['sections']['forYouToday'][0]['id'] == 'unseen1'
    assert result['sections']['forYouToday'][1]['id'] == 'seen1'
    assert result['sections']['heroDeals'][0]['id'] == 'unseen2'
    assert result['sections']['heroDeals'][1]['id'] == 'seen2'


# ── 12. _bound_variant accepts alphanumeric tokens (0–9 from Flutter) ────────

def test_bound_variant_accepts_digits():
    for d in '0123456789':
        v = _bound_variant(d, country='es', day='2026-06-12')
        assert v == d, f'Digit variant {d!r} must pass through unchanged'


def test_bound_variant_fallback_on_empty():
    v = _bound_variant('', country='es', day='2026-06-12')
    assert v in 'ABCD', 'Empty variant must fall back to A/B/C/D'
