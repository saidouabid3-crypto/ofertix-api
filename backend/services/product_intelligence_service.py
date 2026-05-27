from __future__ import annotations

from typing import Any

from services.category_intelligence_service import CategoryIntelligenceService
from services.product_quality_service import ProductQualityService
from services.store_recognition_service import StoreRecognitionService


class ProductIntelligenceService:
    def __init__(self, db: Any | None = None) -> None:
        self.store_service = StoreRecognitionService(db)
        self.category_service = CategoryIntelligenceService(db)
        self.quality_service = ProductQualityService()

    def classify(self, product: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
        data = dict(product)
        store = self.store_service.recognize(data)
        if store.store_name and not data.get('store'):
            data['store'] = store.store_name
        if store.domain:
            data['storeDomain'] = store.domain
        if store.country_code:
            data['countryCode'] = store.country_code
            data['country'] = store.country_code
            data['availableCountries'] = [store.country_code]
            data['marketConfidence'] = store.confidence
            data['marketInferenceReason'] = store.reason
        else:
            data['marketConfidence'] = store.confidence
            data['marketInferenceReason'] = store.reason
        if store.currency and not data.get('currency'):
            data['currency'] = store.currency
        category = self.category_service.classify(data)
        if category.category_id:
            data['category'] = category.category_id
            data['categoryId'] = category.category_id
        if category.subcategory_id:
            data['subcategory'] = category.subcategory_id
            data['subcategoryId'] = category.subcategory_id
        data['categoryConfidence'] = category.confidence
        data['categoryInferenceReason'] = category.reason
        quality = self.quality_service.evaluate(data)
        data['qualityScore'] = quality.score
        data['qualityIssues'] = quality.issues
        if strict and quality.status != 'active':
            data['status'] = quality.status
            data['adminIssue'] = ','.join(quality.issues)
            data['visibleToUsers'] = False
        else:
            data['status'] = data.get('status') or 'active'
            data['visibleToUsers'] = str(data.get('status','active')).lower() in {'active','approved','published'}
        return data
