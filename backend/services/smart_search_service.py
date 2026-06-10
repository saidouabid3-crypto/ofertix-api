"""
Ofertix Smart Search Service — Batch 14B

Pure ranking/scoring engine. Does not touch Firestore.
The route layer fetches candidates; this module scores, sorts, and enriches them.

Architecture: adapter-style. The scoring pipeline can be swapped for a real
search backend (Algolia, Typesense, Meilisearch) by replacing rank_search_results
while keeping the same input/output contract.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

# ─── Synonym groups ───────────────────────────────────────────────────────────

# Each entry: canonical_group_name → frozenset of aliases (all lowercase, accent-free)
SYNONYM_GROUPS: dict[str, frozenset[str]] = {
    'phones': frozenset({
        'telefono', 'movil', 'celular', 'smartphone', 'phone', 'mobile',
        'iphone', 'android', 'samsung', 'xiaomi', 'huawei', 'oppo', 'realme',
        # arabic
        'هاتف', 'جوال', 'موبايل',
        # french
        'telephone', 'portable',
    }),
    'computers': frozenset({
        'laptop', 'portatil', 'ordenador', 'computer', 'pc', 'macbook',
        'notebook', 'chromebook', 'computadora', 'computador',
        # french
        'ordinateur',
    }),
    'tablets': frozenset({
        'tablet', 'tableta', 'ipad', 'tablette',
        # arabic
        'لوحي',
    }),
    'fashion': frozenset({
        'ropa', 'clothing', 'clothes', 'moda', 'fashion', 'vestido', 'dress',
        'camiseta', 'shirt', 'tshirt', 't-shirt', 'pantalon', 'pants', 'jeans',
        'chaqueta', 'jacket', 'abrigo', 'coat', 'sudadera', 'hoodie', 'sweatshirt',
        'falda', 'skirt', 'blusa', 'blouse',
        # french
        'vetement', 'chemise', 'pantalon', 'veste',
        # arabic
        'ملابس', 'قميص',
    }),
    'shoes': frozenset({
        'zapatos', 'zapatillas', 'shoes', 'sneakers', 'botas', 'boots',
        'sandalias', 'sandals', 'tenis', 'nike', 'adidas', 'calzado',
        # french
        'chaussures', 'baskets',
        # arabic
        'حذاء', 'احذية',
    }),
    'bags': frozenset({
        'bolso', 'bolsa', 'handbag', 'bag', 'mochila', 'backpack',
        'cartera', 'wallet', 'maleta', 'suitcase', 'purse',
        # french
        'sac', 'sacoche',
        # arabic
        'حقيبة',
    }),
    'watches': frozenset({
        'reloj', 'watch', 'smartwatch', 'montre', 'relojes',
        # arabic
        'ساعة',
    }),
    'jewelry': frozenset({
        'jewelry', 'joyas', 'joyeria', 'collar', 'necklace', 'pulsera',
        'bracelet', 'anillo', 'ring', 'pendientes', 'earrings',
        # french
        'bijoux', 'collier', 'bracelet',
        # arabic
        'مجوهرات', 'خاتم',
    }),
    'home': frozenset({
        'casa', 'hogar', 'home', 'decor', 'decoracion', 'deco', 'furniture',
        'muebles', 'cocina', 'kitchen', 'baño', 'bathroom', 'living',
        'sofa', 'mesa', 'table', 'silla', 'chair', 'cama', 'bed', 'lampara',
        'lamp', 'alfombra', 'rug', 'cortinas', 'curtains',
        # french
        'maison', 'cuisine', 'meuble',
        # arabic
        'منزل', 'ديكور', 'مطبخ',
    }),
    'sports': frozenset({
        'sport', 'sports', 'deporte', 'deportes', 'fitness', 'gym',
        'entrenamiento', 'running', 'cycling', 'ciclismo', 'futbol',
        'football', 'basketball', 'tennis', 'tenis', 'yoga', 'hiking',
        # french
        'sport', 'sportif',
        # arabic
        'رياضة',
    }),
    'electronics': frozenset({
        'electronica', 'electronics', 'tech', 'gadget', 'gadgets', 'tecnologia',
        'auriculares', 'headphones', 'earbuds', 'airpods', 'altavoz', 'speaker',
        'camara', 'camera', 'tv', 'television', 'smart tv', 'monitor',
        'cargador', 'charger', 'bateria', 'battery', 'cable',
        # french
        'electronique', 'ecouteurs',
        # arabic
        'الكترونيات',
    }),
    'beauty': frozenset({
        'beauty', 'belleza', 'makeup', 'maquillaje', 'perfume', 'parfum',
        'skincare', 'crema', 'cream', 'serum', 'mascarilla', 'mask',
        'shampoo', 'champu', 'desodorante', 'deodorant',
        # french
        'beaute', 'cosmetique', 'soin',
        # arabic
        'جمال', 'عطر', 'مكياج',
    }),
    'kids': frozenset({
        'kids', 'baby', 'bebe', 'ninos', 'children', 'juguetes', 'toys',
        'infantil', 'puericultura', 'cuna', 'crib', 'carrito', 'stroller',
        # french
        'enfant', 'bebe', 'jouet',
        # arabic
        'اطفال', 'لعب',
    }),
    'automotive': frozenset({
        'car', 'coche', 'auto', 'vehiculo', 'vehicle', 'moto', 'motorcycle',
        'automovil', 'motor', 'tires', 'neumaticos', 'frenos', 'brakes',
        # french
        'voiture', 'automobile',
        # arabic
        'سيارة', 'دراجة',
    }),
    'gaming': frozenset({
        'gaming', 'gamer', 'playstation', 'ps4', 'ps5', 'xbox', 'nintendo',
        'switch', 'game', 'juego', 'videojuego', 'controller', 'mando',
        'pc gaming', 'steam',
        # arabic
        'العاب',
    }),
    'food': frozenset({
        'food', 'comida', 'supermercado', 'supermarket', 'grocery', 'alimentacion',
        'nutricion', 'snack', 'bebida', 'drink', 'cafe', 'coffee', 'te', 'tea',
        # french
        'nourriture', 'alimentation',
        # arabic
        'طعام', 'غذاء',
    }),
}

# Reverse index: alias → group_name
_ALIAS_TO_GROUP: dict[str, str] = {}
for _group, _aliases in SYNONYM_GROUPS.items():
    for _alias in _aliases:
        _ALIAS_TO_GROUP[_alias] = _group

# ─── Text normalisation ───────────────────────────────────────────────────────

_STOP_WORDS = frozenset({
    'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'en', 'para', 'con',
    'the', 'a', 'an', 'of', 'for', 'with', 'in', 'on', 'at', 'by',
    'le', 'la', 'les', 'un', 'une', 'des', 'du',
})

# Words that carry shopping intent — never strip
_SHOPPING_WORDS = frozenset({
    'barato', 'cheap', 'oferta', 'deal', 'descuento', 'discount',
    'nuevo', 'new', 'mejor', 'best', 'top', 'bueno', 'good',
    'calidad', 'quality', 'rapido', 'fast', 'original',
    'bon', 'moins', 'cher', 'promo', 'remise',
})


def normalize_query(q: str) -> str:
    """
    Lowercase → accent removal → strip punctuation → collapse whitespace.
    Preserves Arabic/CJK characters intact.
    """
    if not q:
        return ''
    # Accent removal (NFC → NFD → strip combining marks for Latin)
    nfd = unicodedata.normalize('NFD', q.lower().strip())
    no_accents = ''.join(
        c for c in nfd
        if unicodedata.category(c) != 'Mn' or unicodedata.name(c, '').startswith('ARABIC')
    )
    # Keep alphanumeric + Arabic/CJK, collapse the rest to space
    cleaned = re.sub(r'[^\w\s]', ' ', no_accents, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', cleaned).strip()


def tokenize(q: str) -> list[str]:
    """Normalize → split → drop empty stop words, keep shopping words."""
    norm = normalize_query(q)
    tokens = [t for t in norm.split() if len(t) >= 2]
    # Remove stop words unless they are shopping words
    return [t for t in tokens if t not in _STOP_WORDS or t in _SHOPPING_WORDS]


def expand_tokens(tokens: list[str]) -> list[str]:
    """Add synonym group aliases for recognized tokens."""
    expanded = list(tokens)
    seen_groups: set[str] = set()
    for token in tokens:
        group = _ALIAS_TO_GROUP.get(token)
        if group and group not in seen_groups:
            seen_groups.add(group)
            for alias in SYNONYM_GROUPS[group]:
                if alias not in expanded:
                    expanded.append(alias)
    return expanded


def detect_intent(tokens: list[str]) -> dict[str, Any]:
    """
    Find the best-matching synonym group from the query tokens.
    Returns: {group, tokens, expandedTokens, confidence}
    """
    group_hits: dict[str, int] = {}
    for token in tokens:
        group = _ALIAS_TO_GROUP.get(token)
        if group:
            group_hits[group] = group_hits.get(group, 0) + 1

    best_group = max(group_hits, key=lambda g: group_hits[g]) if group_hits else None
    confidence = group_hits.get(best_group, 0) / max(len(tokens), 1) if best_group else 0.0

    expanded = expand_tokens(tokens)

    return {
        'category': best_group,
        'tokens': tokens,
        'expandedTokens': expanded,
        'confidence': round(confidence, 2),
    }


# ─── Fuzzy matching ───────────────────────────────────────────────────────────

def _fuzzy_ratio(a: str, b: str) -> float:
    """SequenceMatcher ratio between two strings. Returns 0–1."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _best_fuzzy(query_token: str, product_tokens: list[str], threshold: float = 0.72) -> float:
    """Best fuzzy match score for query_token against any product token."""
    best = 0.0
    for pt in product_tokens:
        r = _fuzzy_ratio(query_token, pt)
        if r > best:
            best = r
    return best if best >= threshold else 0.0


# ─── Match scoring ────────────────────────────────────────────────────────────

def _item_text_tokens(item: dict[str, Any]) -> list[str]:
    """Build a flat normalized token list from the product's searchable fields."""
    raw = ' '.join([
        str(item.get('name') or ''),
        str(item.get('fullTitle') or ''),
        str(item.get('description') or ''),
        str(item.get('categoryGroup') or item.get('category') or ''),
        str(item.get('store') or ''),
        str(item.get('source') or ''),
    ])
    return tokenize(raw)


def compute_match_score(
    item: dict[str, Any],
    query_tokens: list[str],
    expanded_tokens: list[str],
    intent: dict[str, Any],
) -> float:
    """
    Compute text-relevance score 0–100 for a product against the parsed query.
    Returns 50 (neutral) when query is empty so all products are treated equally.
    """
    if not query_tokens:
        return 50.0

    item_tokens = _item_text_tokens(item)
    item_text_full = normalize_query(' '.join([
        str(item.get('name') or ''),
        str(item.get('fullTitle') or ''),
        str(item.get('description') or ''),
        str(item.get('categoryGroup') or item.get('category') or ''),
        str(item.get('store') or ''),
    ]))
    item_name_text = normalize_query(str(item.get('name') or '') + ' ' + str(item.get('fullTitle') or ''))

    score = 0.0
    matched_tokens = 0

    for qt in query_tokens:
        # +40 exact token match in title/name
        if qt in item_name_text.split():
            score += 40
            matched_tokens += 1
            continue

        # +30 synonym / category intent match
        if qt in expanded_tokens:
            item_cat = normalize_query(str(item.get('categoryGroup') or item.get('category') or ''))
            intent_cat = intent.get('category') or ''
            if intent_cat and intent_cat in item_cat:
                score += 30
                matched_tokens += 1
                continue

        # +20 fuzzy match in name/title
        fuzzy = _best_fuzzy(qt, item_tokens[:30])
        if fuzzy >= 0.72:
            score += 20 * fuzzy
            matched_tokens += 1
            continue

        # +10 description match
        if qt in item_text_full:
            score += 10
            matched_tokens += 1
            continue

        # +10 prefix match
        if any(t.startswith(qt) for t in item_tokens):
            score += 10
            matched_tokens += 1

    # Scale by token coverage
    coverage = matched_tokens / len(query_tokens)
    score *= coverage

    return round(min(100.0, score), 2)


# ─── Smart ranking score ──────────────────────────────────────────────────────

def _number(val: Any, default: float = 0.0) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        return default
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default


_QUARANTINED = frozenset({'quarantined', 'blocked', 'rejected', 'hidden'})


def compute_smart_rank(item: dict[str, Any], match_score: float) -> float:
    """
    Combine match_score with catalog quality signals into a final 0–100 rank.
    """
    public_rank = _number(item.get('publicRankScore') or item.get('catalogRankScore'), 50)
    quality = _number(item.get('qualityScore'), 50)
    discount = _number(item.get('discount'))
    trust = str(item.get('trustStatus') or '').lower()
    flags = {str(f).lower() for f in (item.get('qualityFlags') or [])}
    link = str(item.get('affiliateUrl') or item.get('productUrl') or '').strip()
    images = item.get('images') or []

    discount_score = min(discount, 90)

    score = (
        match_score * 0.45
        + public_rank * 0.20
        + quality * 0.10
        + discount_score * 0.10
    )

    # Bonuses
    if trust in ('trusted', 'ok'):
        score += 10
    if link.startswith('http'):
        score += 8
    if discount >= 50:
        score += 6
    if item.get('isHot'):
        score += 5
    if item.get('featured'):
        score += 4

    # Penalties
    if flags & {'missing_link', 'invalid_link'}:
        score -= 25
    if flags & {'missing_price', 'suspicious_price', 'missing_currency'}:
        score -= 20
    if isinstance(images, list) and len(images) <= 1:
        score -= 15
    if 'duplicate_candidate' in flags:
        score -= 15
    if trust in _QUARANTINED:
        score -= 30
    if not (item.get('categoryGroup') or item.get('category')):
        score -= 10

    return round(max(0.0, min(100.0, score)), 2)


# ─── Filters ─────────────────────────────────────────────────────────────────

def apply_filters(
    items: list[dict[str, Any]],
    *,
    category: str = '',
    store: str = '',
    min_price: float | None = None,
    max_price: float | None = None,
    min_discount: int | None = None,
    trusted_only: bool = False,
) -> list[dict[str, Any]]:
    """Apply optional post-ranking filters. All filters are optional and safe."""
    out = []
    cat_lc = category.strip().lower()
    store_lc = store.strip().lower()

    for item in items:
        if cat_lc:
            item_cat = str(item.get('categoryGroup') or item.get('category') or '').lower()
            if cat_lc not in item_cat:
                continue
        if store_lc:
            item_store = str(item.get('store') or item.get('source') or '').lower()
            if store_lc not in item_store:
                continue
        if min_price is not None:
            if _number(item.get('newPrice') or item.get('price')) < min_price:
                continue
        if max_price is not None:
            if _number(item.get('newPrice') or item.get('price')) > max_price:
                continue
        if min_discount is not None:
            if _number(item.get('discount')) < min_discount:
                continue
        if trusted_only:
            if str(item.get('trustStatus') or '').lower() not in ('trusted', 'ok'):
                continue
        out.append(item)
    return out


# ─── Sort ─────────────────────────────────────────────────────────────────────

def sort_results(
    items: list[dict[str, Any]],
    sort_mode: str = 'smart',
) -> list[dict[str, Any]]:
    if sort_mode == 'discount_desc':
        return sorted(items, key=lambda p: _number(p.get('discount')), reverse=True)
    if sort_mode == 'price_asc':
        return sorted(items, key=lambda p: _number(p.get('newPrice') or p.get('price')))
    if sort_mode == 'price_desc':
        return sorted(items, key=lambda p: _number(p.get('newPrice') or p.get('price')), reverse=True)
    if sort_mode == 'newest':
        return sorted(items, key=lambda p: str(p.get('updatedAt') or ''), reverse=True)
    if sort_mode == 'trusted':
        def _trust_key(p: dict) -> int:
            t = str(p.get('trustStatus') or '').lower()
            return 0 if t == 'trusted' else (1 if t == 'ok' else 2)
        return sorted(items, key=_trust_key)
    # default: smart (by smartSearchScore already applied)
    return items


# ─── Suggestions ─────────────────────────────────────────────────────────────

def build_suggestions(
    intent: dict[str, Any],
    result_categories: list[str],
    result_stores: list[str],
    max_suggestions: int = 8,
) -> list[str]:
    """
    Build query suggestion chips from synonym group + result facets.
    Never invents products — only names from synonym map and observed catalog facets.
    """
    suggestions: list[str] = []
    seen: set[str] = set()

    # 1. Synonyms from the detected intent group
    group = intent.get('category')
    if group and group in SYNONYM_GROUPS:
        # Pick a few human-friendly aliases from the group
        nice_aliases = [
            a for a in SYNONYM_GROUPS[group]
            if len(a) >= 4 and a.isascii() and a not in intent.get('tokens', [])
        ][:4]
        for a in nice_aliases:
            if a not in seen:
                seen.add(a)
                suggestions.append(a)

    # 2. Related groups (adjacent groups that share keywords)
    for token in intent.get('tokens', []):
        for group_name, aliases in SYNONYM_GROUPS.items():
            if group_name == group:
                continue
            if token in aliases and group_name not in seen:
                seen.add(group_name)
                suggestions.append(group_name)
            if len(suggestions) >= max_suggestions:
                break

    # 3. Top observed categories from results (real catalog values)
    for cat in result_categories[:3]:
        cat_norm = cat.strip().lower()
        if cat_norm and cat_norm not in seen:
            seen.add(cat_norm)
            suggestions.append(cat)

    # 4. Top observed stores from results
    for store in result_stores[:2]:
        store_norm = store.strip().lower()
        if store_norm and store_norm not in seen:
            seen.add(store_norm)
            suggestions.append(store)

    return suggestions[:max_suggestions]


# ─── Main entry point ─────────────────────────────────────────────────────────

def rank_search_results(
    candidates: list[dict[str, Any]],
    *,
    query: str = '',
    category: str = '',
    store: str = '',
    min_price: float | None = None,
    max_price: float | None = None,
    min_discount: int | None = None,
    trusted_only: bool = False,
    sort_mode: str = 'smart',
    limit: int = 40,
) -> dict[str, Any]:
    """
    Score, filter, sort and enrich a list of pre-fetched public product candidates.

    Input:  list of products that already passed public eligibility checks.
    Output: {
        ranked_products: list[dict],
        suggestions: list[str],
        detectedIntent: dict,
        filters: { categories: [...], stores: [...], priceRange: {...} }
    }
    """
    tokens = tokenize(query)
    intent = detect_intent(tokens)
    expanded = intent.get('expandedTokens') or tokens

    # Score each candidate
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in candidates:
        match = compute_match_score(item, tokens, expanded, intent)
        rank = compute_smart_rank(item, match)
        item = dict(item)
        item['smartSearchScore'] = rank
        item['searchMatchScore'] = match
        scored.append((rank, item))

    # Sort by smart rank (descending)
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [item for _, item in scored]

    # Apply filters (post-scoring so we can still access all products for facets)
    filtered = apply_filters(
        ranked,
        category=category,
        store=store,
        min_price=min_price,
        max_price=max_price,
        min_discount=min_discount,
        trusted_only=trusted_only,
    )

    # Re-sort after filtering (sort_mode may override smart order)
    if sort_mode != 'smart':
        filtered = sort_results(filtered, sort_mode)

    # Paginate
    result_page = filtered[:limit]

    # Facets from the full result set (before pagination)
    cats_seen: dict[str, int] = {}
    stores_seen: dict[str, int] = {}
    prices: list[float] = []

    for item in filtered:
        cat = str(item.get('categoryGroup') or item.get('category') or '').strip()
        if cat and cat.lower() not in ('general', ''):
            cats_seen[cat] = cats_seen.get(cat, 0) + 1
        st = str(item.get('store') or '').strip()
        if st:
            stores_seen[st] = stores_seen.get(st, 0) + 1
        price = _number(item.get('newPrice') or item.get('price'))
        if price > 0:
            prices.append(price)

    top_categories = sorted(cats_seen, key=lambda c: cats_seen[c], reverse=True)[:10]
    top_stores = sorted(stores_seen, key=lambda s: stores_seen[s], reverse=True)[:10]

    suggestions = build_suggestions(intent, top_categories, top_stores)

    return {
        'ranked_products': result_page,
        'suggestions': suggestions,
        'detectedIntent': intent,
        'filters': {
            'categories': [{'name': c, 'count': cats_seen[c]} for c in top_categories],
            'stores': [{'name': s, 'count': stores_seen[s]} for s in top_stores],
            'priceRange': {
                'min': round(min(prices), 2) if prices else None,
                'max': round(max(prices), 2) if prices else None,
            },
        },
    }
