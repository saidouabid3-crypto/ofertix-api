from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ProductQualityResult:
    status: str
    score: int
    issues: list[str]


class ProductQualityService:
    BAD_TEXT = {'', 'string', 'test', 'demo', 'placeholder', 'coming soon', 'soon', 'fake'}

    def evaluate(self, product: dict[str, Any]) -> ProductQualityResult:
        issues: list[str] = []
        score = 100
        title = str(product.get('title') or product.get('name') or '').strip()
        image = str(product.get('image') or product.get('imageUrl') or product.get('mainImage') or '').strip()
        link = str(product.get('affiliateUrl') or product.get('productUrl') or product.get('url') or product.get('link') or '').strip()
        price = self._price(product.get('price') or product.get('currentPrice') or product.get('newPrice'))
        country = str(product.get('countryCode') or product.get('country') or '').lower().strip()
        category = str(product.get('categoryId') or product.get('category') or '').lower().strip()
        store = str(product.get('store') or product.get('storeName') or product.get('source') or '').strip()
        if title.lower() in self.BAD_TEXT or len(title) < 4:
            issues.append('missing_or_bad_title'); score -= 25
        if image and not image.startswith('http'):
            issues.append('invalid_image_url'); score -= 10
        if not image:
            issues.append('missing_image'); score -= 10
        if price <= 0:
            issues.append('missing_or_invalid_price'); score -= 20
        if link and not link.startswith('http'):
            issues.append('invalid_link'); score -= 10
        if not country or country in {'global','unknown','null'}:
            issues.append('missing_market'); score -= 20
        if not category or category in {'global','unknown','other','general','null'}:
            issues.append('missing_category'); score -= 15
        if not store:
            issues.append('missing_store'); score -= 10
        low_title = title.lower()
        if any(bad in low_title for bad in ['test product','demo product','placeholder']):
            issues.append('demo_or_placeholder_product'); score -= 50
        score = max(0, min(100, score))
        if 'missing_market' in issues:
            return ProductQualityResult('needs_market_review', score, issues)
        if 'missing_category' in issues:
            return ProductQualityResult('needs_category_review', score, issues)
        if score < 70:
            return ProductQualityResult('needs_quality_review', score, issues)
        return ProductQualityResult('active', score, issues)

    @staticmethod
    def _price(value: Any) -> float:
        try:
            raw = str(value or '0').replace('€','').replace('$','').replace(',', '.').strip()
            return float(raw)
        except Exception:
            return 0.0
