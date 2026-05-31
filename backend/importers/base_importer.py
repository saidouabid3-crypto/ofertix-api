from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseImporter(ABC):
    @abstractmethod
    async def fetch_products(self) -> list[dict[str, Any]]:
        raise NotImplementedError
