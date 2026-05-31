from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from core.firebase import db

logger = logging.getLogger(__name__)


def save_product(product: dict[str, Any]) -> str:
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Firestore is not configured. Check backend Firebase credentials.",
        )

    try:
        _, doc_ref = db.collection("products").add(product)
        return doc_ref.id
    except Exception as exc:
        logger.exception("Failed to save product: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save product") from exc
