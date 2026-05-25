from datetime import datetime
from typing import Optional
from uuid import uuid4

from core.firebase import db


class SmartReelRepository:
    COLLECTION = "smart_reels"

    def __init__(self):
        self.collection = db.collection(self.COLLECTION)

    def create(self, data: dict) -> dict:
        now = datetime.utcnow().isoformat()
        reel_id = f"reel_{uuid4().hex[:12]}"

        reel = {
            "id": reel_id,
            **data,
            "views": 0,
            "likes": 0,
            "clicks": 0,
            "saves": 0,
            "reports": 0,
            "created_at": now,
            "updated_at": now,
        }

        self.collection.document(reel_id).set(reel)
        return reel

    def list_feed(
        self,
        limit: int = 10,
        cursor: Optional[str] = None,
    ) -> tuple[list[dict], Optional[str], bool]:
        limit = max(1, min(limit, 20))

        query = (
            self.collection
            .where("status", "==", "approved")
            .order_by("created_at", direction="DESCENDING")
            .limit(limit + 1)
        )

        if cursor:
            cursor_doc = self.collection.document(cursor).get()
            if cursor_doc.exists:
                query = query.start_after(cursor_doc)

        docs = list(query.stream())

        has_more = len(docs) > limit
        docs_to_return = docs[:limit]

        items = []
        for doc in docs_to_return:
            data = doc.to_dict() or {}
            data["id"] = data.get("id") or doc.id
            items.append(data)

        next_cursor = items[-1]["id"] if has_more and items else None

        return items, next_cursor, has_more

    def get_by_id(self, reel_id: str) -> Optional[dict]:
        doc = self.collection.document(reel_id).get()

        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        data["id"] = data.get("id") or doc.id
        return data

    def increment(self, reel_id: str, field: str) -> Optional[dict]:
        allowed_fields = {"views", "likes", "clicks", "saves", "reports"}

        if field not in allowed_fields:
            return None

        doc_ref = self.collection.document(reel_id)
        doc = doc_ref.get()

        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        current_value = int(data.get(field, 0))
        new_value = current_value + 1

        doc_ref.update({
            field: new_value,
            "updated_at": datetime.utcnow().isoformat(),
        })

        data[field] = new_value
        data["id"] = data.get("id") or reel_id
        return data


smart_reel_repository = SmartReelRepository()