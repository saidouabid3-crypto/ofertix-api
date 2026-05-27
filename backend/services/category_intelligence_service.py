from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class CategoryResult:
    category_id: str | None
    subcategory_id: str | None
    confidence: float
    reason: str


DEFAULT_CATEGORY_RULES: list[dict[str, Any]] = [
    {'category':'electronics','subcategory':'phones','keywords':['iphone','samsung galaxy','smartphone','mobile phone','telefono','teléfono','xiaomi','redmi','realme','oppo','oneplus','pixel','huawei']},
    {'category':'electronics','subcategory':'laptops','keywords':['laptop','portatil','portátil','macbook','thinkpad','notebook','chromebook']},
    {'category':'electronics','subcategory':'headphones','keywords':['airpods','headphones','auriculares','earbuds','sony wh','jbl','beats']},
    {'category':'electronics','subcategory':'gaming','keywords':['playstation','ps5','xbox','nintendo','gaming','gamer','controller']},
    {'category':'home_kitchen','subcategory':'kitchen_appliances','keywords':['air fryer','freidora','robot cocina','batidora','cafetera','microondas','horno','lavadora','lavavajillas']},
    {'category':'home_kitchen','subcategory':'furniture','keywords':['sofa','sofá','mesa','silla','armario','mueble','estantería','colchón']},
    {'category':'fashion','subcategory':'shoes','keywords':['zapatillas','sneakers','shoes','nike','adidas','puma','new balance']},
    {'category':'fashion','subcategory':'clothing','keywords':['camiseta','chaqueta','pantalon','pantalón','dress','jacket','hoodie','abrigo']},
    {'category':'beauty_health','subcategory':'personal_care','keywords':['perfume','skincare','crema','serum','champu','champú','afeitadora','depiladora']},
    {'category':'supermarket','subcategory':'household','keywords':['detergente','pañales','comida','aceite','leche','limpieza','hogar']},
    {'category':'sports','subcategory':'fitness','keywords':['fitness','gym','mancuernas','running','bicicleta','cycling','football','fútbol']},
    {'category':'kids_baby','subcategory':'toys','keywords':['toy','juguete','lego','bebé','bebe','baby','carrito bebé']},
    {'category':'cars_moto','subcategory':'accessories','keywords':['coche','car','moto','neumatico','neumático','dashcam','aceite motor']},
    {'category':'digital','subcategory':'software','keywords':['software','subscription','suscripción','vpn','gift card','licencia','license']},
]


class CategoryIntelligenceService:
    def __init__(self, db: Any | None = None) -> None:
        self.db = db

    def classify(self, product: dict[str, Any]) -> CategoryResult:
        explicit_category = self._clean_slug(product.get('category') or product.get('categoryId'))
        explicit_subcategory = self._clean_slug(product.get('subcategory') or product.get('subcategoryId'))
        if explicit_category and explicit_category not in {'global','unknown','other','general','null'}:
            return CategoryResult(explicit_category, explicit_subcategory, 0.95, 'explicit_category')
        blob = self._blob(product)
        result = self._classify_with_rules(blob, self._load_db_rules(), 'category_rules_config')
        if result.confidence > 0:
            return result
        return self._classify_with_rules(blob, DEFAULT_CATEGORY_RULES, 'default_keyword_rules')

    def _load_db_rules(self) -> list[dict[str, Any]]:
        if self.db is None:
            return []
        try:
            docs = self.db.collection('category_rules').where('enabled', '==', True).limit(1000).stream()
            rules = []
            for doc in docs:
                data = doc.to_dict() or {}
                rules.append({'category': data.get('categoryId') or data.get('category') or doc.id, 'subcategory': data.get('subcategoryId') or data.get('subcategory'), 'keywords': data.get('keywords') or []})
            return rules
        except Exception:
            return []

    @staticmethod
    def _blob(product: dict[str, Any]) -> str:
        keys = ['title','name','description','brand','storeCategory','categoryName','sourceCategory','keywords','tags']
        values = []
        for key in keys:
            value = product.get(key)
            if isinstance(value, list):
                values.extend(str(x) for x in value)
            else:
                values.append(str(value or ''))
        return ' '.join(values).lower()

    @staticmethod
    def _clean_slug(value: Any) -> str | None:
        raw = str(value or '').lower().strip()
        if not raw:
            return None
        raw = re.sub(r'[^a-z0-9_ -]+', '', raw)
        raw = re.sub(r'[\s-]+', '_', raw)
        return raw or None

    def _classify_with_rules(self, blob: str, rules: list[dict[str, Any]], source: str) -> CategoryResult:
        best: tuple[str, str | None, int, str] | None = None
        for rule in rules:
            category = self._clean_slug(rule.get('category'))
            subcategory = self._clean_slug(rule.get('subcategory'))
            keywords = rule.get('keywords') or []
            if isinstance(keywords, str):
                keywords = [keywords]
            score = 0
            matched = ''
            for keyword in keywords:
                kw = str(keyword or '').lower().strip()
                if not kw:
                    continue
                if kw in blob:
                    score += 3 if ' ' in kw else 1
                    matched = kw
            if score and (best is None or score > best[2]):
                best = (category or 'other', subcategory, score, matched)
        if best:
            category, subcategory, score, matched = best
            confidence = min(0.92, 0.60 + (score * 0.06))
            return CategoryResult(category, subcategory, confidence, f'{source}:{matched}')
        return CategoryResult(None, None, 0.0, 'missing_reliable_category_signal')
