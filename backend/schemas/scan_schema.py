from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScanRequest(BaseModel):
    """Barcode / QR scan lookup request sent by the Flutter ScanService."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(default="", max_length=256)
    countryCode: str = Field(default="global", max_length=16)

    @field_validator("code")
    @classmethod
    def strip_code(cls, value: str) -> str:
        return value.strip()

    @field_validator("countryCode")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        cleaned = value.strip()
        return cleaned or "global"


class ScanResponse(BaseModel):
    """Scan lookup response.

    The key names (``products``, ``query``) match exactly what the Flutter
    ``ScanService._parseScanResponse`` reads, so products flow straight into
    ``Product.fromMap`` with zero serialization mismatch.
    """

    model_config = ConfigDict(extra="ignore")

    code: str = ""
    query: str = ""
    country: str = "global"
    currency: str = "EUR"
    count: int = 0
    products: list[dict[str, Any]] = Field(default_factory=list)
