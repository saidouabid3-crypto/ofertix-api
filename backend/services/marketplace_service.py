from typing import Any, Dict, List, Optional

from repositories.marketplace_repository import MarketplaceRepository
from utils.country_intelligence import normalize_country, normalize_country_list


class MarketplaceService:
    def __init__(self) -> None:
        self.repo = MarketplaceRepository()

    def list_items(
        self,
        limit: int = 30,
        country: str = 'es',
        city: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.repo.list_items(limit=limit, country=country, city=city, category=category)

    def create_item(self, payload: Dict[str, Any], current_user: Dict[str, Any]) -> Dict[str, Any]:
        required = ['title', 'price']
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"Missing fields: {', '.join(missing)}")

        country = normalize_country(
            payload.get('country')
            or payload.get('countryCode')
            or payload.get('sellerCountryCode')
            or 'global'
        )
        ships_to = normalize_country_list(payload.get('shipsTo') or payload.get('ships_to'))
        available = normalize_country_list(payload.get('availableCountries') or payload.get('available_countries'))
        if country != 'global' and country not in available:
            available.append(country)

        clean = {
            **payload,
            'sellerId': current_user['uid'],
            'sellerEmail': current_user.get('email', ''),
            'sellerCountryCode': country,
            'country': country,
            'countryCode': country,
            'availableCountries': available,
            'shipsTo': ships_to,
            'pickupOnly': bool(payload.get('pickupOnly') or payload.get('pickup_only')),
            'status': payload.get('status') or 'active',
            'isActive': payload.get('isActive', True),
        }
        return self.repo.create_item(clean)

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_item(item_id)

    def update_item(self, item_id: str, payload: Dict[str, Any], current_user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        item = self.repo.get_item(item_id)
        if not item or item.get('sellerId') != current_user['uid']:
            return None
        protected = {'id', 'createdAt', 'sellerId', 'sellerEmail'}
        clean_payload = {k: v for k, v in payload.items() if k not in protected}
        return self.repo.update_item(item_id, clean_payload)

    def delete_item(self, item_id: str, current_user: Dict[str, Any]) -> bool:
        item = self.repo.get_item(item_id)
        if not item or item.get('sellerId') != current_user['uid']:
            return False
        return self.repo.delete_item(item_id)

    def favorite_item(self, item_id: str, user_id: str) -> Dict[str, Any]:
        return self.repo.favorite_item(item_id, user_id)

    def report_item(self, item_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        return self.repo.report_item(item_id, user_id, reason)
