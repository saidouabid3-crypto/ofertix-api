from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class ProductClassifyRequest(BaseModel):
    product: dict[str, Any] = Field(default_factory=dict)
    strict: bool = True

class ProductClassifyResponse(BaseModel):
    product: dict[str, Any]
