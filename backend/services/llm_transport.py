"""Single LLM transport for the entire backend.

Previously, three services each hand-rolled their own HTTP call to an LLM
provider (``ai_engine_service`` -> OpenAI/OpenRouter, ``ai_service`` -> Groq).
That meant three copies of retry logic, timeout handling, JSON-mode plumbing,
and error semantics. This module collapses all of that into one async-first,
type-hinted transport using a small Strategy pattern over providers.

Callers supply messages; the transport handles provider selection, JSON mode,
exponential backoff with jitter, and raising a single typed error
(:class:`LLMTransportError`) on definitive failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger("ofertix.llm")

T = TypeVar("T")

Message = dict[str, str]


class LLMTransportError(RuntimeError):
    """Raised when the configured provider cannot return a usable completion."""


class LLMProvider(ABC):
    """A chat-completions provider strategy."""

    name: str = "base"

    def __init__(self, *, model: str, timeout_seconds: float) -> None:
        self.model = model
        self.timeout = httpx.Timeout(timeout_seconds)

    @property
    @abstractmethod
    def api_key(self) -> str:
        """The provider API key (empty string when unconfigured)."""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    @abstractmethod
    def _endpoint(self) -> str: ...

    @abstractmethod
    def _headers(self) -> dict[str, str]: ...

    async def complete(
        self,
        *,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": messages,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._endpoint(), headers=self._headers(), json=body
            )
            response.raise_for_status()
            data = response.json()

        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError(
                f"{self.name}: malformed completion payload"
            ) from exc


class OpenAIProvider(LLMProvider):
    name = "openai"

    @property
    def api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "")

    def _endpoint(self) -> str:
        return "https://api.openai.com/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class OpenRouterProvider(LLMProvider):
    name = "openrouter"

    @property
    def api_key(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "")

    def _endpoint(self) -> str:
        return "https://openrouter.ai/api/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "https://ofertix.app"),
            "X-Title": os.getenv("OPENROUTER_APP_NAME", "Ofertix"),
        }


class GroqProvider(LLMProvider):
    name = "groq"

    @property
    def api_key(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    def _endpoint(self) -> str:
        return "https://api.groq.com/openai/v1/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class LLMTransport:
    """Provider-agnostic completion transport with retry/backoff."""

    def __init__(self) -> None:
        self._timeout = float(os.getenv("AI_HTTP_TIMEOUT_SECONDS", "40"))
        self._max_retries = int(os.getenv("AI_MAX_RETRIES", "2"))

    # --- provider resolution ---------------------------------------------

    def _provider(self, preferred: str | None = None) -> LLMProvider:
        """Resolve the active provider.

        ``preferred`` lets a specific capability force a provider (the
        conversational search path historically used Groq); otherwise the
        global ``AI_PROVIDER`` env decides.
        """
        choice = (preferred or os.getenv("AI_PROVIDER", "openai")).lower().strip()

        if choice == "openrouter":
            return OpenRouterProvider(
                model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                timeout_seconds=self._timeout,
            )
        if choice == "groq":
            return GroqProvider(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                timeout_seconds=self._timeout,
            )
        return OpenAIProvider(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout_seconds=self._timeout,
        )

    def is_configured(self, preferred: str | None = None) -> bool:
        return self._provider(preferred).is_configured

    # --- public API -------------------------------------------------------

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        history: list[Message] | None = None,
    ) -> str:
        """Return raw JSON text from the model (JSON mode enabled)."""
        messages = self._assemble(system_prompt, user_content, history)
        return await self._run(
            preferred_provider,
            messages=messages,
            temperature=temperature,
            json_mode=True,
            max_tokens=max_tokens,
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.35,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
    ) -> str:
        """Return free-form text from the model (JSON mode disabled)."""
        messages = self._assemble(system_prompt, user_content, None)
        return await self._run(
            preferred_provider,
            messages=messages,
            temperature=temperature,
            json_mode=False,
            max_tokens=max_tokens,
        )

    # --- internals --------------------------------------------------------

    @staticmethod
    def _assemble(
        system_prompt: str,
        user_content: str,
        history: list[Message] | None,
    ) -> list[Message]:
        messages: list[Message] = [{"role": "system", "content": system_prompt}]
        for item in (history or [])[-10:]:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})
        return messages

    async def _run(
        self,
        preferred_provider: str | None,
        *,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> str:
        provider = self._provider(preferred_provider)
        if not provider.is_configured:
            raise LLMTransportError(f"{provider.name}: API key is not configured")

        async def operation() -> str:
            return await provider.complete(
                messages=messages,
                temperature=temperature,
                json_mode=json_mode,
                max_tokens=max_tokens,
            )

        return await self._retry(operation, attempts=self._max_retries)

    async def _retry(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        attempts: int = 2,
        base_delay: float = 0.55,
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                return await operation()
            except Exception as exc:  # noqa: BLE001 - re-raised as typed error below
                last_error = exc
                if attempt == attempts - 1:
                    break
                await asyncio.sleep(base_delay * (2**attempt) + random.uniform(0, 0.25))
        raise LLMTransportError(str(last_error)) from last_error


# Process-wide singleton.
llm_transport = LLMTransport()
