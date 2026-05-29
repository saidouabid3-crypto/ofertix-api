from __future__ import annotations

import random
import time
from collections import defaultdict
from typing import Any

from core.firebase import db
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.product_standard import available_for_country, standardize_product


class HomeFeedService:
    """Backend-driven smart feed so Flutter displays one organized, low-cost response."""

    MAX_READS = 420

    def __init__(self, firestore_db: Any | None = None) -> None:
        self.db = firestore_db or db

    def build_home_feed(self, *, country: str = 'es', user_id: str | None = None, seed: str | None = None, limit: int = 24) -> dict[str, Any]:
        market = normalize_market(country)
        products = self._load_products(market)
        rng = random.Random(seed or f'{user_id or "guest"}-{int(time.time() // 900)}')
        products = self._dedupe(products)
        rng.shuffle(products)
        products.sort(key=self._rank_key, reverse=True)

        used: set[str] = set()
        hero = self._pick(products, used, 4, lambda p: p.get('dealScore', 0) >= 70 or p.get('aiVerdict') in {'buy_now', 'safe_deal'})
        hot = self._pick(products, used, 12, lambda p: p.get('discount', 0) >= 15 or p.get('isHot'))
        top_rated = self._pick(products, used, 12, lambda p: float(p.get('rating') or 0) >= 4.2 or int(p.get('reviewCount') or 0) >= 50)
        best_sellers = self._pick(products, used, 12, lambda p: int(p.get('soldCount') or p.get('sales') or 0) >= 50)
        under10 = self._pick(products, used, 10, lambda p: 0 < float(p.get('newPrice') or 0) <= 10)
        under25 = self._pick(products, used, 10, lambda p: 0 < float(p.get('newPrice') or 0) <= 25)
        recent = self._pick(products, used, 10, lambda p: True)
        surprise = self._pick_diverse(products, used, 12)
        global_online = self._pick(products, used, 14, lambda p: bool(p.get('isOnline', True)))
        recommended = self._pick_diverse(products, used, min(limit, 24))

        stores = self._top_facets(products, 'store')
        categories = self._top_facets(products, 'categoryGroup')

        hidden_risky = len([p for p in products if int(p.get('riskScore') or 0) >= 70])
        better_wait = len([p for p in products if p.get('aiVerdict') == 'wait'])
        strong = len([p for p in products if p.get('aiVerdict') in {'buy_now', 'safe_deal'}])

        return {
            'country': market,
            'currency': SUPPORTED_MARKETS.get(market, SUPPORTED_MARKETS['es'])['currency'],
            'algorithmVersion': 'ofertix-smart-feed-v1',
            'generatedAt': int(time.time()),
            'aiStatus': {
                'strongDeals': strong,
                'riskyDealsHidden': hidden_risky,
                'betterToWait': better_wait,
                'cheaperAlternativesFound': len(under25),
            },
            'sections': {
                'heroDeals': hero,
                'hotDeals': hot,
                'globalOnline': global_online,
                'topRated': top_rated,
                'bestSellers': best_sellers,
                'under10': under10,
                'under25': under25,
                'recentlyAdded': recent,
                'surpriseDeals': surprise,
                'recommended': recommended,
            },
            'stores': stores,
            'categories': categories,
            'products': products[:limit],
            'count': len(products),
        }

    def build_product_detail(self, product_id: str, *, country: str = 'es') -> dict[str, Any]:
        market = normalize_market(country)
        doc = self.db.collection('products').document(product_id).get()
        if not doc.exists:
            return {'ok': False, 'error': 'product_not_found'}
        product = standardize_product(doc.to_dict() or {}, document_id=doc.id, fallback_country=market)
        candidates = [p for p in self._load_products(market) if p.get('id') != product_id]
        used: set[str] = set()
        category = str(product.get('categoryGroup') or product.get('category') or '').lower()
        store = str(product.get('store') or '').lower()
        price = float(product.get('newPrice') or 0)
        similar = self._pick(candidates, used, 10, lambda p: category and category == str(p.get('categoryGroup') or p.get('category') or '').lower())
        same_store = self._pick(candidates, used, 10, lambda p: store and store == str(p.get('store') or '').lower())
        cheaper = self._pick(candidates, used, 10, lambda p: price > 0 and 0 < float(p.get('newPrice') or 0) < price)
        top_rated = self._pick(candidates, used, 10, lambda p: float(p.get('rating') or 0) >= 4.2 or int(p.get('trustScore') or 0) >= 75)
        bundle = self._bundle_for(product, candidates)
        return {
            'ok': True,
            'product': product,
            'aiVerdict': self._verdict_copy(product),
            'dealDNA': product.get('dealDNA') or {},
            'sections': {
                'similarProducts': similar,
                'sameStoreProducts': same_store,
                'cheaperAlternatives': cheaper,
                'topRatedAlternatives': top_rated,
                'bundleBuilder': bundle,
            },
        }

    def track_event(self, *, event_type: str, product_id: str, user_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            'eventType': event_type,
            'productId': product_id,
            'userId': user_id or 'anonymous',
            'payload': payload or {},
            'createdAt': int(time.time()),
        }
        self.db.collection('product_events').add(event)
        if event_type == 'offer_click':
            self.db.collection('products').document(product_id).update({'clicks': firestore_increment(1)})
        elif event_type == 'product_view':
            self.db.collection('products').document(product_id).update({'views': firestore_increment(1)})
        return {'ok': True}

    def _load_products(self, market: str) -> list[dict[str, Any]]:
        try:
            stream = self.db.collection('products').where('visibleToUsers', '==', True).limit(self.MAX_READS).stream()
        except Exception:
            stream = self.db.collection('products').limit(self.MAX_READS).stream()
        products: list[dict[str, Any]] = []
        for doc in stream:
            item = standardize_product(doc.to_dict() or {}, document_id=doc.id, fallback_country=market)
            if str(item.get('status', 'active')).lower() not in {'active', 'approved', 'published'}:
                continue
            if not available_for_country(item, market):
                continue
            if not item.get('image') or float(item.get('newPrice') or 0) <= 0:
                continue
            products.append(item)
        return products

    def _dedupe(self, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for p in products:
            key = str(p.get('fingerprint') or p.get('id'))
            if key not in best or self._rank_value(p) > self._rank_value(best[key]):
                best[key] = p
        return list(best.values())

    def _rank_value(self, p: dict[str, Any]) -> float:
        return float(p.get('dealScore') or 0) * 0.34 + float(p.get('trustScore') or 0) * 0.28 + float(p.get('qualityScore') or 0) * 0.22 - float(p.get('riskScore') or 0) * 0.16 + min(12, float(p.get('discount') or 0) / 4)

    def _rank_key(self, p: dict[str, Any]) -> tuple[float, int, int]:
        return (self._rank_value(p), int(p.get('reviewCount') or 0), int(p.get('soldCount') or 0))

    def _pick(self, products: list[dict[str, Any]], used: set[str], count: int, predicate) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in products:
            pid = str(p.get('id'))
            if pid in used or int(p.get('riskScore') or 0) >= 85:
                continue
            if predicate(p):
                out.append(p)
                used.add(pid)
                if len(out) >= count:
                    break
        return out

    def _pick_diverse(self, products: list[dict[str, Any]], used: set[str], count: int) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in products:
            if str(p.get('id')) not in used and int(p.get('riskScore') or 0) < 85:
                grouped[str(p.get('categoryGroup') or p.get('category') or 'General')].append(p)
        out: list[dict[str, Any]] = []
        while len(out) < count and grouped:
            for key in list(grouped.keys()):
                if not grouped[key]:
                    grouped.pop(key, None)
                    continue
                p = grouped[key].pop(0)
                pid = str(p.get('id'))
                if pid in used:
                    continue
                out.append(p)
                used.add(pid)
                if len(out) >= count:
                    break
        return out

    def _top_facets(self, products: list[dict[str, Any]], field: str, limit: int = 12) -> list[dict[str, Any]]:
        counts: dict[str, int] = defaultdict(int)
        best_discount: dict[str, int] = defaultdict(int)
        for p in products:
            name = str(p.get(field) or '').strip()
            if not name:
                continue
            counts[name] += 1
            best_discount[name] = max(best_discount[name], int(p.get('discount') or 0))
        ranked = sorted(counts.items(), key=lambda kv: (kv[1], best_discount[kv[0]]), reverse=True)[:limit]
        return [{'name': name, 'count': count, 'subtitle': f'{count} deals · up to {best_discount[name]}%'} for name, count in ranked]

    def _bundle_for(self, product: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        category = str(product.get('categoryGroup') or '').lower()
        accessory_words = ['case', 'charger', 'strap', 'protector', 'cable', 'cover', 'bag', 'adapter']
        out: list[dict[str, Any]] = []
        for p in candidates:
            text = f"{p.get('name','')} {p.get('description','')} {p.get('categoryGroup','')}".lower()
            if any(w in text for w in accessory_words) or (category and category in text):
                out.append(p)
            if len(out) >= 6:
                break
        return out

    def _verdict_copy(self, product: dict[str, Any]) -> dict[str, Any]:
        verdict = product.get('aiVerdict') or 'wait'
        messages = {
            'buy_now': 'Strong value: discount, trust and quality look good.',
            'safe_deal': 'Looks safe, but compare shipping and final store price.',
            'wait': 'Better to wait or compare alternatives before buying.',
            'risky': 'Risk detected: reviews, shipping, price or seller data may be weak.',
            'avoid': 'Avoid for now: high regret risk or weak product quality.',
        }
        return {
            'code': verdict,
            'label': product.get('aiVerdictLabel') or verdict.replace('_', ' ').title(),
            'message': messages.get(verdict, messages['wait']),
            'dealScore': product.get('dealScore', 0),
            'trustScore': product.get('trustScore', 0),
            'riskScore': product.get('riskScore', 0),
        }


def firestore_increment(amount: int):
    from google.cloud import firestore
    return firestore.Increment(amount)
