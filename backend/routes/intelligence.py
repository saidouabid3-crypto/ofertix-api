from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import require_admin
from core.firebase import db
from schemas.intelligence_schema import ProductClassifyRequest, ProductClassifyResponse
from services.product_intelligence_service import ProductIntelligenceService

router = APIRouter(prefix='/admin/intelligence', tags=['Admin Intelligence'])

@router.post('/classify-product', response_model=ProductClassifyResponse)
def classify_product(payload: ProductClassifyRequest, current_user: dict = Depends(require_admin)):
    service = ProductIntelligenceService(db)
    return {'product': service.classify(payload.product, strict=payload.strict)}
