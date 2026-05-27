from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class SetupStatusResponse(BaseModel):
    ok: bool = True
    missingEnv: list[str] = Field(default_factory=list)
    configuredEnv: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
