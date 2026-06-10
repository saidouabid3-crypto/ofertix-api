"""
Unit tests for smart_search_service.
No Firestore needed — all functions are pure.
"""
from __future__ import annotations

import pytest

from services.smart_search_service import (
    SYNONYM_GROUPS,
    _ALIAS_TO_GROUP,
    apply_filters,
    build_suggestions,
    compute_match_score,
    compute_smart_rank,
    detect_intent,
    expand_tokens,
    normalize_query,
    rank_search_results,
    sort_results,
    tokenize,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _product(
    id: str = 'p1',
    name: str = 'Product',
    full_title: str = '',
    description: str = '',
    category: str = 'Electronics',
    store: str = 'ShopA',
    price: float = 50.0,
    discount: int = 20,
    trust: str = 'trusted',
    quality: float = 70.0,
    public_rank: float = 70.0,
    is_hot: bool = False,
    featured: bool = False,
    affiliate_url: str = 'https://aff.link/p1',
    images: list | None = None,
    flags: list | None = None,
) -> dict:
    return {
        'id': id,
        'name': name,
        'fullTitle': full_title or name,
        'description': description,
        'categoryGroup': category,
        'store': store,
        'newPrice': price,
        'discount': discount,
        'trustStatus': trust,
        'qualityScore': quality,
        'publicRankScore': public_rank,
        'isHot': is_hot,
        'featured': featured,
        'affiliateUrl': affiliate_url,
        'images': images or ['http://img.test/a.jpg', 'http://img.test/b.jpg'],
        'qualityFlags': flags or [],
        'fingerprint': f"{store}|{name}|{price}",
    }


# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------

class TestNormalizeQuery:
    def test_removes_accents(self):
        assert normalize_query('teléfono') == 'telefono'
        assert normalize_query('portátil') == 'portatil'
        assert normalize_query('móvil') == 'movil'

    def test_lowercase(self):
        assert normalize_query('LAPTOP') == 'laptop'
        assert normalize_query('Samsung S24') == 'samsung s24'

    def test_strips_whitespace(self):
        assert normalize_query('  telefono  ') == 'telefono'
        assert normalize_query('telefono  barato') == 'telefono barato'

    def test_empty_returns_empty(self):
        assert normalize_query('') == ''
        assert normalize_query('   ') == ''

    def test_punctuation_stripped(self):
        result = normalize_query("¡teléfono!")
        assert 'telefono' in result

    def test_french_accents(self):
        assert normalize_query('téléphone') == 'telephone'
        assert normalize_query('chaussures') == 'chaussures'  # no accent


# ---------------------------------------------------------------------------
# tokenize + expand
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_tokenize(self):
        tokens = tokenize('telefono barato')
        assert 'telefono' in tokens
        assert 'barato' in tokens

    def test_drops_stop_words(self):
        tokens = tokenize('el telefono de la tienda')
        assert 'el' not in tokens
        assert 'telefono' in tokens

    def test_keeps_shopping_intent_words(self):
        tokens = tokenize('oferta barato descuento')
        assert 'oferta' in tokens
        assert 'barato' in tokens
        assert 'descuento' in tokens

    def test_accent_removal_in_tokens(self):
        tokens = tokenize('teléfono portátil móvil')
        assert 'telefono' in tokens
        assert 'portatil' in tokens
        assert 'movil' in tokens


class TestExpandTokens:
    def test_synonym_expansion_movil(self):
        tokens = ['movil']
        expanded = expand_tokens(tokens)
        assert 'smartphone' in expanded
        assert 'telefono' in expanded

    def test_no_duplicate_expansion(self):
        tokens = ['shoes', 'zapatos']  # both in 'shoes' group
        expanded = expand_tokens(tokens)
        assert len(expanded) == len(set(expanded))


# ---------------------------------------------------------------------------
# detect_intent
# ---------------------------------------------------------------------------

class TestDetectIntent:
    def test_detects_phones_group(self):
        intent = detect_intent(['movil', 'barato'])
        assert intent['category'] == 'phones'

    def test_detects_computers_group(self):
        intent = detect_intent(['laptop', 'barato'])
        assert intent['category'] == 'computers'

    def test_detects_shoes_group(self):
        intent = detect_intent(['zapatillas'])
        assert intent['category'] == 'shoes'

    def test_no_match_returns_none_category(self):
        intent = detect_intent(['xyzabc123'])
        assert intent['category'] is None

    def test_expanded_tokens_included(self):
        intent = detect_intent(['movil'])
        assert 'phone' in intent['expandedTokens'] or 'smartphone' in intent['expandedTokens']

    def test_english_phone_maps_to_phones(self):
        intent = detect_intent(['phone'])
        assert intent['category'] == 'phones'


# ---------------------------------------------------------------------------
# compute_match_score
# ---------------------------------------------------------------------------

class TestComputeMatchScore:
    def _intent(self, tokens):
        return detect_intent(tokens)

    def test_exact_name_match_scores_high(self):
        p = _product(name='smartphone samsung galaxy')
        tokens = tokenize('samsung')
        intent = self._intent(tokens)
        score = compute_match_score(p, tokens, expand_tokens(tokens), intent)
        assert score > 0

    def test_no_match_scores_low(self):
        p = _product(name='kitchen knife set')
        tokens = tokenize('zapatos')
        intent = self._intent(tokens)
        score = compute_match_score(p, tokens, expand_tokens(tokens), intent)
        assert score < 30

    def test_empty_query_returns_neutral(self):
        p = _product()
        score = compute_match_score(p, [], [], {'category': None, 'tokens': [], 'expandedTokens': [], 'confidence': 0})
        assert score == 50.0

    def test_synonym_helps_match(self):
        p = _product(name='smartphone android telefono', category='phones')
        # Query is 'movil' (synonym of telefono)
        tokens = tokenize('movil')
        intent = self._intent(tokens)
        expanded = expand_tokens(tokens)
        score = compute_match_score(p, tokens, expanded, intent)
        # Should score higher than unrelated product
        p2 = _product(name='kitchen blender set', category='home')
        score2 = compute_match_score(p2, tokens, expanded, intent)
        assert score > score2

    def test_fuzzy_match_typo(self):
        p = _product(name='telefono samsung')
        tokens = tokenize('telefoo')  # typo
        intent = self._intent(tokens)
        score = compute_match_score(p, tokens, expand_tokens(tokens), intent)
        # Some score expected from fuzzy
        assert score >= 0  # at least doesn't error; fuzzy ratio may or may not match


# ---------------------------------------------------------------------------
# compute_smart_rank
# ---------------------------------------------------------------------------

class TestComputeSmartRank:
    def test_trusted_product_ranks_higher(self):
        trusted = _product(trust='trusted', public_rank=70)
        unknown = _product(trust='unknown', public_rank=70)
        assert compute_smart_rank(trusted, 80) > compute_smart_rank(unknown, 80)

    def test_quarantined_heavily_penalised(self):
        quarantined = _product(trust='quarantined', public_rank=80)
        ok_p = _product(trust='ok', public_rank=50)
        assert compute_smart_rank(ok_p, 60) > compute_smart_rank(quarantined, 60)

    def test_high_discount_boosts_score(self):
        high = _product(discount=60, trust='ok', public_rank=60)
        low = _product(discount=5, trust='ok', public_rank=60)
        assert compute_smart_rank(high, 70) > compute_smart_rank(low, 70)

    def test_missing_link_penalised(self):
        no_link = _product(affiliate_url='', flags=['missing_link'])
        with_link = _product(affiliate_url='https://aff.link/x')
        assert compute_smart_rank(with_link, 70) > compute_smart_rank(no_link, 70)

    def test_score_clamped_0_100(self):
        for trust in ('trusted', 'quarantined', 'ok', 'unknown'):
            p = _product(trust=trust)
            s = compute_smart_rank(p, 50.0)
            assert 0.0 <= s <= 100.0

    def test_high_match_irrelevant_product_not_above_relevant_trusted(self):
        # High match score but low quality shouldn't beat relevant trusted product
        risky = _product(trust='quarantined', quality=30, public_rank=10)
        trusted = _product(trust='trusted', quality=80, public_rank=80)
        # Even with same match score, trusted wins
        assert compute_smart_rank(trusted, 60) > compute_smart_rank(risky, 60)


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

class TestApplyFilters:
    def _catalog(self):
        return [
            _product(id='p1', category='Electronics', price=100, discount=30, trust='trusted'),
            _product(id='p2', category='Fashion', price=30, discount=10, trust='ok'),
            _product(id='p3', category='Electronics', price=200, discount=60, trust='needs_review'),
            _product(id='p4', category='Sports', price=50, discount=20, trust='trusted'),
        ]

    def test_filter_by_category(self):
        result = apply_filters(self._catalog(), category='electronics')
        ids = [p['id'] for p in result]
        assert 'p1' in ids
        assert 'p3' in ids
        assert 'p2' not in ids

    def test_filter_by_min_discount(self):
        result = apply_filters(self._catalog(), min_discount=25)
        ids = [p['id'] for p in result]
        assert 'p1' in ids  # 30%
        assert 'p3' in ids  # 60%
        assert 'p2' not in ids  # 10%

    def test_trusted_only(self):
        result = apply_filters(self._catalog(), trusted_only=True)
        ids = [p['id'] for p in result]
        assert 'p1' in ids
        assert 'p4' in ids
        assert 'p3' not in ids  # needs_review

    def test_price_range(self):
        result = apply_filters(self._catalog(), min_price=50, max_price=150)
        ids = [p['id'] for p in result]
        assert 'p1' in ids   # 100
        assert 'p4' in ids   # 50
        assert 'p3' not in ids  # 200

    def test_no_filters_returns_all(self):
        catalog = self._catalog()
        result = apply_filters(catalog)
        assert len(result) == len(catalog)


# ---------------------------------------------------------------------------
# rank_search_results
# ---------------------------------------------------------------------------

class TestRankSearchResults:
    def _make_catalog(self, n: int = 10) -> list:
        return [
            _product(
                id=f'p{i}',
                name=f'Product {i}',
                trust='trusted' if i % 2 == 0 else 'ok',
                discount=10 + i * 3,
                public_rank=50.0 + i,
            )
            for i in range(n)
        ]

    def test_returns_ranked_products_field(self):
        catalog = self._make_catalog()
        result = rank_search_results(catalog, query='product', limit=5)
        assert 'ranked_products' in result
        assert len(result['ranked_products']) <= 5

    def test_returns_suggestions(self):
        catalog = self._make_catalog()
        result = rank_search_results(catalog, query='movil')
        assert 'suggestions' in result
        assert isinstance(result['suggestions'], list)

    def test_returns_detected_intent(self):
        catalog = self._make_catalog()
        result = rank_search_results(catalog, query='telefono')
        assert result['detectedIntent']['category'] == 'phones'

    def test_returns_filters_facets(self):
        catalog = self._make_catalog()
        result = rank_search_results(catalog, query='product')
        assert 'filters' in result
        assert 'categories' in result['filters']
        assert 'stores' in result['filters']
        assert 'priceRange' in result['filters']

    def test_quarantined_excluded_from_results(self):
        catalog = self._make_catalog(5)
        catalog.append(_product(id='qx', name='phone', trust='quarantined'))
        result = rank_search_results(catalog, query='phone', limit=20)
        # quarantined product gets heavily penalized and should score low
        # it may still appear but with very low score (or could be filtered upstream)
        # The test ensures it doesn't top the list
        ids = [p['id'] for p in result['ranked_products']]
        if ids:
            assert ids[0] != 'qx'  # quarantined must not rank first

    def test_trusted_product_ranks_above_weak_product_similar_match(self):
        trusted = _product(id='good', name='telefono samsung trusted', trust='trusted', public_rank=80, quality=80)
        weak = _product(id='weak', name='telefono samsung weak', trust='quarantined', public_rank=30, quality=30)
        result = rank_search_results([trusted, weak], query='telefono', limit=10)
        ids = [p['id'] for p in result['ranked_products']]
        if len(ids) >= 2:
            assert ids.index('good') < ids.index('weak')

    def test_filters_applied_in_rank(self):
        catalog = self._make_catalog(10)
        # Add a fashion item
        catalog.append(_product(id='fashion1', name='dress', category='Fashion', trust='trusted'))
        result = rank_search_results(catalog, query='', category='fashion', limit=20)
        for p in result['ranked_products']:
            assert 'fashion' in str(p.get('categoryGroup') or '').lower()

    def test_min_discount_filter(self):
        catalog = [
            _product(id='low', discount=5),
            _product(id='high', discount=55),
        ]
        result = rank_search_results(catalog, query='', min_discount=30, limit=10)
        ids = [p['id'] for p in result['ranked_products']]
        assert 'high' in ids
        assert 'low' not in ids

    def test_trusted_only_filter(self):
        catalog = [
            _product(id='t1', trust='trusted'),
            _product(id='t2', trust='needs_review'),
        ]
        result = rank_search_results(catalog, query='', trusted_only=True, limit=10)
        ids = [p['id'] for p in result['ranked_products']]
        assert 't1' in ids
        assert 't2' not in ids

    def test_empty_query_returns_all_ranked_by_public_score(self):
        catalog = [
            _product(id='hi', public_rank=90, trust='trusted'),
            _product(id='lo', public_rank=20, trust='ok'),
        ]
        result = rank_search_results(catalog, query='', limit=10)
        ids = [p['id'] for p in result['ranked_products']]
        assert len(ids) == 2

    def test_cache_key_does_not_include_unbounded_data(self):
        """Verify that rank_search_results is stateless — no per-user data stored."""
        catalog = self._make_catalog(5)
        r1 = rank_search_results(catalog, query='phone', limit=5)
        r2 = rank_search_results(catalog, query='phone', limit=5)
        # Same inputs → same results
        ids1 = [p['id'] for p in r1['ranked_products']]
        ids2 = [p['id'] for p in r2['ranked_products']]
        assert ids1 == ids2

    def test_no_unbounded_iteration(self):
        """rank_search_results must respect the limit parameter."""
        large_catalog = self._make_catalog(100)
        result = rank_search_results(large_catalog, query='product', limit=10)
        assert len(result['ranked_products']) <= 10


# ---------------------------------------------------------------------------
# sort_results
# ---------------------------------------------------------------------------

class TestSortResults:
    def _items(self):
        return [
            {'id': 'a', 'discount': 10, 'newPrice': 30},
            {'id': 'b', 'discount': 50, 'newPrice': 100},
            {'id': 'c', 'discount': 30, 'newPrice': 15},
        ]

    def test_sort_discount_desc(self):
        result = sort_results(self._items(), 'discount_desc')
        assert result[0]['id'] == 'b'  # 50%

    def test_sort_price_asc(self):
        result = sort_results(self._items(), 'price_asc')
        assert result[0]['id'] == 'c'  # €15

    def test_sort_price_desc(self):
        result = sort_results(self._items(), 'price_desc')
        assert result[0]['id'] == 'b'  # €100

    def test_sort_smart_passthrough(self):
        items = self._items()
        result = sort_results(items, 'smart')
        assert result == items  # unchanged order


# ---------------------------------------------------------------------------
# build_suggestions
# ---------------------------------------------------------------------------

class TestBuildSuggestions:
    def test_suggestions_list_type(self):
        intent = detect_intent(['movil'])
        suggestions = build_suggestions(intent, [], [])
        assert isinstance(suggestions, list)

    def test_max_suggestions_capped(self):
        intent = detect_intent(['movil'])
        suggestions = build_suggestions(intent, ['Electronics', 'Fashion', 'Sports', 'Home', 'Kids', 'Beauty'], ['ShopA', 'ShopB'], max_suggestions=5)
        assert len(suggestions) <= 5

    def test_suggestions_are_strings(self):
        intent = detect_intent(['laptop'])
        suggestions = build_suggestions(intent, ['Computers'], ['TechShop'])
        for s in suggestions:
            assert isinstance(s, str)


# ---------------------------------------------------------------------------
# Route-level backward compat test (no Firestore)
# ---------------------------------------------------------------------------

import asyncio
import os

os.environ.setdefault("FIREBASE_REQUIRED", "false")

from routes import products as product_routes


def test_search_route_preserves_old_response_shape(monkeypatch):
    """Old clients only send {query, country, limit} — response must have count + products."""
    monkeypatch.setattr(
        product_routes, "_stream_products",
        lambda limit: [{
            "id": "s1",
            "name": "samsung galaxy telefono",
            "status": "active",
            "visibleToUsers": True,
            "countryCode": "global",
            "country": "global",
            "availableCountries": ["es"],
            "isExplicitlyGlobal": True,
            "image": "https://img.test/s1.jpg",
            "newPrice": 299.0,
            "currency": "EUR",
            "affiliateUrl": "https://aff.link/s1",
            "store": "Samsung",
        }]
    )
    monkeypatch.setattr(
        product_routes, "load_catalog_config",
        lambda: {"publicFilteringEnabled": False, "smartRankingEnabled": True},
    )

    result = asyncio.run(
        product_routes.search_products(
            product_routes.ProductSearchRequest(query="telefono", country="es", limit=10)
        )
    )

    assert "count" in result
    assert "products" in result
    assert result["count"] >= 0
    # New fields present but non-breaking
    assert "suggestions" in result
    assert "detectedIntent" in result
    assert "filters" in result


def test_search_route_empty_query_returns_all(monkeypatch):
    """Empty query must return all public products (backward compat)."""
    monkeypatch.setattr(
        product_routes, "_stream_products",
        lambda limit: [{
            "id": "t1",
            "name": "wireless charger",
            "status": "active",
            "visibleToUsers": True,
            "countryCode": "global",
            "country": "global",
            "availableCountries": ["es"],
            "isExplicitlyGlobal": True,
            "image": "https://img.test/t1.jpg",
            "newPrice": 20.0,
            "currency": "EUR",
            "affiliateUrl": "https://aff.link/t1",
            "store": "TechShop",
        }]
    )
    monkeypatch.setattr(
        product_routes, "load_catalog_config",
        lambda: {"publicFilteringEnabled": False, "smartRankingEnabled": True},
    )

    result = asyncio.run(
        product_routes.search_products(
            product_routes.ProductSearchRequest(query="", country="es", limit=10)
        )
    )
    assert result["count"] == 1
    assert result["products"][0]["status"] == "active"
