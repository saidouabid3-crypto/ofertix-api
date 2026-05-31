from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials, firestore

load_dotenv()

logger = logging.getLogger(__name__)


def _load_credentials() -> credentials.Certificate | None:
    """
    Load Firebase credentials from secure production sources.

    Supported env vars:
    - FIREBASE_CREDENTIALS: full JSON service account string.
    - FIREBASE_CREDENTIALS_JSON: full JSON service account string.
    - FIREBASE_KEY_PATH: local service account path, defaults to firebase_key.json.

    This module intentionally avoids printing secret values.
    """
    raw_json = os.getenv("FIREBASE_CREDENTIALS") or os.getenv("FIREBASE_CREDENTIALS_JSON")
    if raw_json:
        try:
            parsed: dict[str, Any] = json.loads(raw_json)
            return credentials.Certificate(parsed)
        except json.JSONDecodeError as exc:
            logger.error("Invalid Firebase credentials JSON in environment: %s", exc)
            raise RuntimeError("Invalid Firebase credentials JSON") from exc

    key_path = Path(os.getenv("FIREBASE_KEY_PATH", "firebase_key.json"))
    if key_path.exists():
        return credentials.Certificate(str(key_path))

    if os.getenv("FIREBASE_REQUIRED", "true").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError(
            "Firebase credentials were not found. Set FIREBASE_CREDENTIALS_JSON "
            "or FIREBASE_KEY_PATH in Render environment variables."
        )

    logger.warning(
        "Firebase credentials were not found and FIREBASE_REQUIRED is false. "
        "Firestore-dependent routes will fail until credentials are configured."
    )
    return None


def _initialize_firebase() -> firestore.Client | None:
    if not firebase_admin._apps:
        cred = _load_credentials()
        if cred is None:
            return None
        firebase_admin.initialize_app(cred)

    return firestore.client()


db = _initialize_firebase()
