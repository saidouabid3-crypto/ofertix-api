from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(slots=True)
class CachedRate:
    rate: float
    expires_at: datetime


class CurrencyService:
    """
    High-availability currency converter.

    Primary source:
      - Frankfurter API

    Production hardening:
      - 6-hour TTL cache
      - per-pair async lock to prevent thundering herd
      - exponential-backoff retries
      - local fallback rates if upstream is down
    """

    FRANKFURTER_URL = "https://api.frankfurter.app/latest"

    FALLBACK_TO_EUR = {
        "EUR": 1.0,
        "USD": 0.92,
        "GBP": 1.17,
        "MAD": 0.092,
        "CNY": 0.13,
        "JPY": 0.0061,
        "CAD": 0.67,
        "AUD": 0.61,
        "CHF": 1.05,
        "BRL": 0.16,
        "MXN": 0.046,
        "TRY": 0.026,
        "INR": 0.011,
        "SEK": 0.089,
        "NOK": 0.086,
        "DKK": 0.134,
        "PLN": 0.234,
    }

    def __init__(self, timeout_seconds: float = 6.0, ttl_hours: int = 6) -> None:
        self._cache: dict[tuple[str, str], CachedRate] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._timeout = httpx.Timeout(timeout_seconds)
        self._ttl = timedelta(hours=ttl_hours)

    async def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        if amount <= 0:
            return 0.0

        from_currency = self._normalize_currency(from_currency)
        to_currency = self._normalize_currency(to_currency)

        if from_currency == to_currency:
            return round(amount, 2)

        rate = await self.get_rate(from_currency, to_currency)
        return round(amount * rate, 2)

    async def get_rate(self, from_currency: str, to_currency: str) -> float:
        key = (self._normalize_currency(from_currency), self._normalize_currency(to_currency))
        cached = self._cache.get(key)
        now = datetime.now(timezone.utc)

        if cached and cached.expires_at > now:
            return cached.rate

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            now = datetime.now(timezone.utc)
            if cached and cached.expires_at > now:
                return cached.rate

            try:
                rate = await self._retry(lambda: self._fetch_frankfurter_rate(key[0], key[1]))
            except Exception as exc:
                logger.warning("Currency API failed for %s->%s; using fallback: %s", key[0], key[1], exc)
                rate = self._fallback_rate(key[0], key[1])

            self._cache[key] = CachedRate(rate=rate, expires_at=now + self._ttl)
            return rate

    async def _fetch_frankfurter_rate(self, from_currency: str, to_currency: str) -> float:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                self.FRANKFURTER_URL,
                params={"from": from_currency, "to": to_currency},
                headers={"Accept": "application/json", "User-Agent": "OfertixCurrencyService/1.0"},
            )
            response.raise_for_status()
            data = response.json()

        rate = (data.get("rates") or {}).get(to_currency)
        if not isinstance(rate, (int, float)) or rate <= 0:
            raise ValueError(f"Invalid exchange rate {from_currency}->{to_currency}")
        return float(rate)

    def _fallback_rate(self, from_currency: str, to_currency: str) -> float:
        from_to_eur = self.FALLBACK_TO_EUR.get(from_currency)
        to_to_eur = self.FALLBACK_TO_EUR.get(to_currency)

        if not from_to_eur or not to_to_eur:
            logger.warning("Unknown fallback currency pair %s->%s; neutral rate used", from_currency, to_currency)
            return 1.0

        return from_to_eur / to_to_eur

    async def _retry(
        self,
        operation: Callable[[], Awaitable[T]],
        attempts: int = 3,
        base_delay: float = 0.35,
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await operation()
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.15)
                await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    def _normalize_currency(self, value: str) -> str:
        normalized = (value or "EUR").strip().upper()
        return normalized if len(normalized) == 3 else "EUR"


currency_service = CurrencyService()
