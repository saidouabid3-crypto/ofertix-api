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
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger("ofertix.llm")

T = TypeVar("T")

Message = dict[str, str]


@dataclass(frozen=True)
class LLMCompletion:
    content: str
    provider: str
    model: str


class LLMTransportError(RuntimeError):
    """Raised when the configured provider cannot return a usable completion."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "LLM_TRANSPORT_ERROR",
        providers: list[str] | None = None,
        role: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.providers = providers or []
        self.role = role


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


class GeminiProvider(LLMProvider):
    name = "gemini"

    @property
    def api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "")

    def _endpoint(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def complete(
        self,
        *,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> str:
        prompt = "\n\n".join(
            f"{item.get('role', 'user').upper()}: {item.get('content', '')}"
            for item in messages
            if item.get("content")
        )
        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": generation_config,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._endpoint(), headers=self._headers(), json=body
            )
            response.raise_for_status()
            data = response.json()

        try:
            return str(data["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError(
                f"{self.name}: malformed completion payload"
            ) from exc


class LLMTransport:
    """Provider-agnostic completion transport with retry/backoff."""

    _SUPPORTED_PROVIDERS = ("groq", "openai", "gemini", "openrouter")

    def __init__(self) -> None:
        self._timeout = float(os.getenv("AI_HTTP_TIMEOUT_SECONDS", "40"))
        self._max_retries = int(os.getenv("AI_MAX_RETRIES", "2"))

    # --- provider resolution ---------------------------------------------

    def _provider(self, provider_name: str | None = None) -> LLMProvider:
        """Build a provider strategy for a normalized provider name."""
        choice = self._normalize_provider(provider_name or self.default_provider_name)

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
        if choice == "gemini":
            return GeminiProvider(
                model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
                timeout_seconds=self._timeout,
            )
        return OpenAIProvider(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout_seconds=self._timeout,
        )

    @property
    def default_provider_name(self) -> str:
        return self._normalize_provider(os.getenv("AI_PROVIDER", "groq"))

    @property
    def fallback_provider_name(self) -> str:
        return self._normalize_provider(os.getenv("AI_FALLBACK_PROVIDER", "openai"))

    @property
    def premium_provider_name(self) -> str:
        return self._normalize_provider(os.getenv("AI_PREMIUM_PROVIDER", self.fallback_provider_name))

    @property
    def vision_provider_name(self) -> str:
        return self._normalize_provider(os.getenv("AI_VISION_PROVIDER", "gemini"))

    def provider_names_for_role(
        self,
        *,
        preferred_provider: str | None = None,
        provider_role: str | None = None,
    ) -> list[str]:
        names: list[str] = []
        if preferred_provider:
            names.append(self._normalize_provider(preferred_provider))
        else:
            role = (provider_role or "fast").lower().strip()
            if role in {"premium", "deep", "analysis", "ask_before_buying"}:
                names.extend(
                    [
                        self.premium_provider_name,
                        self.fallback_provider_name,
                        self.default_provider_name,
                    ]
                )
            elif role in {"vision", "image", "multimodal", "visual_search", "scan"}:
                names.extend(
                    [
                        self.vision_provider_name,
                        self.fallback_provider_name,
                        self.default_provider_name,
                    ]
                )
            else:
                names.extend([self.default_provider_name, self.fallback_provider_name])

        for provider in self._SUPPORTED_PROVIDERS:
            if self._provider(provider).is_configured:
                names.append(provider)

        return self._unique_supported(names)

    def provider_status(self) -> dict[str, Any]:
        providers = {
            name: {
                "configured": self._provider(name).is_configured,
                "model": self._provider(name).model,
            }
            for name in self._SUPPORTED_PROVIDERS
        }
        return {
            "default": self.default_provider_name,
            "fallback": self.fallback_provider_name,
            "premium": self.premium_provider_name,
            "vision": self.vision_provider_name,
            "providers": providers,
        }

    def is_configured(
        self,
        preferred: str | None = None,
        *,
        provider_role: str | None = None,
    ) -> bool:
        return any(
            self._provider(name).is_configured
            for name in self.provider_names_for_role(
                preferred_provider=preferred,
                provider_role=provider_role,
            )
        )

    # --- public API -------------------------------------------------------

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        provider_role: str | None = None,
        history: list[Message] | None = None,
    ) -> str:
        """Return raw JSON text from the model (JSON mode enabled)."""
        completion = await self.complete_json_with_metadata(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider,
            provider_role=provider_role,
            history=history,
        )
        return completion.content

    async def complete_json_with_metadata(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        provider_role: str | None = None,
        history: list[Message] | None = None,
    ) -> LLMCompletion:
        """Return raw JSON text plus the provider/model that actually answered."""
        messages = self._assemble(system_prompt, user_content, history)
        return await self._run_completion(
            preferred_provider,
            provider_role=provider_role,
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
        provider_role: str | None = None,
    ) -> str:
        """Return free-form text from the model (JSON mode disabled)."""
        completion = await self.complete_text_with_metadata(
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
            preferred_provider=preferred_provider,
            provider_role=provider_role,
        )
        return completion.content

    async def complete_text_with_metadata(
        self,
        *,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.35,
        max_tokens: int | None = None,
        preferred_provider: str | None = None,
        provider_role: str | None = None,
    ) -> LLMCompletion:
        """Return free-form text plus the provider/model that actually answered."""
        messages = self._assemble(system_prompt, user_content, None)
        return await self._run_completion(
            preferred_provider,
            provider_role=provider_role,
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
        provider_role: str | None,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> str:
        completion = await self._run_completion(
            preferred_provider,
            provider_role=provider_role,
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            max_tokens=max_tokens,
        )
        return completion.content

    async def _run_completion(
        self,
        preferred_provider: str | None,
        *,
        provider_role: str | None,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        max_tokens: int | None,
    ) -> LLMCompletion:
        provider_names = self.provider_names_for_role(
            preferred_provider=preferred_provider,
            provider_role=provider_role,
        )
        errors: list[str] = []
        configured_seen = False

        for provider_name in provider_names:
            provider = self._provider(provider_name)
            if not provider.is_configured:
                errors.append(f"{provider.name}: API key is not configured")
                continue

            configured_seen = True

            async def operation(current_provider: LLMProvider = provider) -> str:
                return await current_provider.complete(
                    messages=messages,
                    temperature=temperature,
                    json_mode=json_mode,
                    max_tokens=max_tokens,
                )

            try:
                content = await self._retry(operation, attempts=self._max_retries)
                return LLMCompletion(
                    content=content,
                    provider=provider.name,
                    model=provider.model,
                )
            except LLMTransportError as exc:
                errors.append(f"{provider.name}: {exc}")
                logger.warning(
                    "LLM provider %s failed for role %s; trying fallback if any: %s",
                    provider.name,
                    provider_role or "fast",
                    exc,
                )

        role = provider_role or "fast"
        detail = "; ".join(errors) or "No supported providers were selected"
        if not configured_seen:
            raise LLMTransportError(
                f"No configured AI provider for role '{role}'. Tried: {', '.join(provider_names)}",
                code="AI_PROVIDER_NOT_CONFIGURED",
                providers=provider_names,
                role=role,
            )
        raise LLMTransportError(
            f"All configured AI providers failed for role '{role}': {detail}",
            code="AI_PROVIDER_FAILED",
            providers=provider_names,
            role=role,
        )

    def _normalize_provider(self, value: str | None) -> str:
        provider = (value or "groq").lower().strip().replace("-", "_")
        aliases = {
            "default": "groq",
            "fast": "groq",
            "premium": "openai",
            "deep": "openai",
            "vision": "gemini",
            "google": "gemini",
            "google_gemini": "gemini",
            "open_ai": "openai",
            "open_router": "openrouter",
        }
        return aliases.get(provider, provider)

    def _unique_supported(self, names: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for name in names:
            normalized = self._normalize_provider(name)
            if normalized not in self._SUPPORTED_PROVIDERS:
                logger.warning("Unsupported AI provider ignored: %s", name)
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

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
