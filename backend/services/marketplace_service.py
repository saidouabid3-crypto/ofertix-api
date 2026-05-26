from typing import Any, Dict, List, Optional

from repositories.marketplace_repository import MarketplaceRepository


class MarketplaceService:
    def __init__(self) -> None:
        self.repo = MarketplaceRepository()

    def list_items(self, limit: int = 30, city: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.repo.list_items(limit=limit, city=city, category=category)

    def create_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        required = ["title", "price", "sellerId"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"Missing fields: {', '.join(missing)}")
        return self.repo.create_item(payload)

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_item(item_id)

    def update_item(self, item_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        protected = {"id", "createdAt"}
        clean_payload = {k: v for k, v in payload.items() if k not in protected}
        return self.repo.update_item(item_id, clean_payload)

    def delete_item(self, item_id: str) -> bool:
        return self.repo.delete_item(item_id)

    def favorite_item(self, item_id: str, user_id: str) -> Dict[str, Any]:
        return self.repo.favorite_item(item_id, user_id)

    def report_item(self, item_id: str, user_id: str, reason: str) -> Dict[str, Any]:
        return self.repo.report_item(item_id, user_id, reason)
