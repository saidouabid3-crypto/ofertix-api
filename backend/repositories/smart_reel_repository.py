from datetime import datetime
from typing import Optional
from uuid import uuid4


class SmartReelRepository:
    """
    نسخة قوية كبداية.
    دابا كتخزن in-memory باش نخدمو بسرعة.
    من بعد نربطوها مباشرة مع Firebase/Firestore بنفس interface بلا ما نكسر route ولا Flutter.
    """

    def __init__(self):
        self.reels = []

    def create(self, data: dict) -> dict:
        reel = {
            "id": f"reel_{uuid4().hex[:12]}",
            **data,
            "views": 0,
            "likes": 0,
            "clicks": 0,
            "saves": 0,
            "reports": 0,
            "created_at": datetime.utcnow(),
        }

        self.reels.insert(0, reel)
        return reel

    def list_feed(self, limit: int = 10, cursor: Optional[str] = None) -> tuple[list[dict], Optional[str], bool]:
        approved = [r for r in self.reels if r.get("status") == "approved"]

        start = 0
        if cursor:
            for index, reel in enumerate(approved):
                if reel["id"] == cursor:
                    start = index + 1
                    break

        items = approved[start:start + limit]
        has_more = start + limit < len(approved)
        next_cursor = items[-1]["id"] if has_more and items else None

        return items, next_cursor, has_more

    def get_by_id(self, reel_id: str) -> Optional[dict]:
        for reel in self.reels:
            if reel["id"] == reel_id:
                return reel
        return None

    def increment(self, reel_id: str, field: str) -> Optional[dict]:
        reel = self.get_by_id(reel_id)
        if not reel:
            return None

        reel[field] = int(reel.get(field, 0)) + 1
        return reel


smart_reel_repository = SmartReelRepository()