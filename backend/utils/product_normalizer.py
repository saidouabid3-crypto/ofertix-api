import hashlib
import re
from typing import Any

from utils.product_standard import (
    SUPPORTED_COUNTRIES,
    normalize_product,
    product_fingerprint,
    score_product,
)


def clean_text(value: Any, default: str = '') -> str:
    if value is None:
        return default
    return str(value).strip() or default


def clean_price(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).replace('€', '').replace('$', '').replace('EUR', '').replace('USD', '').strip()
    if ',' in raw and '.' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif ',' in raw:
        raw = raw.replace(',', '.')
    try:
        return float(raw)
    except Exception:
        return default


def clean_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(clean_price(value, default)))
    except Exception:
        return default


def normalize_country_list(countries: 'list[str] | str', fallback: str = 'global') -> list:
    if isinstance(countries, list):
        return [str(c).strip().lower() for c in countries if str(c).strip()]
    if isinstance(countries, str) and countries.strip():
        return [c.strip().lower() for c in re.split(r'[,|;]', countries) if c.strip()]
    return [fallback]


def stable_product_id(*parts: Any) -> str:
    raw = '|'.join(str(p).lower().strip() for p in parts if p)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def classify_category(item: dict) -> tuple:
    from core.elite_categories import classify_elite_category, map_to_elite_category
    cat, conf, reason = classify_elite_category(item)
    return map_to_elite_category(cat), conf, reason


__all__ = [
    'normalize_product',
    'score_product',
    'product_fingerprint',
    'SUPPORTED_COUNTRIES',
    'clean_text',
    'clean_price',
    'clean_int',
    'normalize_country_list',
    'stable_product_id',
    'classify_category',
]
