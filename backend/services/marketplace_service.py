from typing import Any, Dict, Optional
from repositories.marketplace_repository import MarketplaceRepository
from core.market_config import normalize_market, SUPPORTED_MARKETS
from utils.market_filter import item_available_for_country, normalize_item_market_fields

class MarketplaceService:
    def __init__(self):
        self.repo = MarketplaceRepository()

    def list_items(self, limit: int = 30, city: Optional[str] = None, category: Optional[str] = None, country: str = 'es'):
        market = normalize_market(country)
        items = self.repo.list_items(limit=limit * 3, city=city, category=category)
        filtered = [normalize_item_market_fields(i, market) for i in items if item_available_for_country(i, market)]
        return filtered[:limit]

    def create_item(self, payload: Dict[str, Any]):
        market = normalize_market(payload.get('sellerCountryCode') or payload.get('country') or 'es')
        payload['sellerCountryCode'] = market
        payload['country'] = market
        payload['countryCode'] = market
        payload['currency'] = payload.get('currency') or SUPPORTED_MARKETS[market]['currency']
        payload.setdefault('availableCountries', [market])
        payload.setdefault('shipsTo', [] if payload.get('pickupOnly', True) else [market])
        payload.setdefault('pickupOnly', True)
        return self.repo.create_item(payload)

    def get_item(self, item_id: str):
        return self.repo.get_item(item_id)
    def update_item(self, item_id: str, payload: Dict[str, Any]):
        return self.repo.update_item(item_id, payload)
    def delete_item(self, item_id: str):
        return self.repo.delete_item(item_id)
    def favorite_item(self, item_id: str, user_id: str):
        return self.repo.favorite_item(item_id, user_id)
    def report_item(self, item_id: str, user_id: str, reason: str):
        return self.repo.report_item(item_id, user_id, reason)
