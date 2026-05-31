"""Async-safe, request-scoped locale state for the Ofertix backend.

This module is the single source of truth for *who* the current request is, in
linguistic and monetary terms. It is populated once per request by
``core.middleware.locale_middleware.LocaleMiddleware`` and read anywhere
downstream (AI services, prompt engine, error handlers) without having to thread
a ``Request`` object through every call.

It uses :mod:`contextvars`, which is both thread-safe and ``asyncio``-task-safe:
each request/task sees its own value, and concurrent requests never bleed into
one another. This is the correct primitive for FastAPI, where many requests are
served concurrently on the same event loop.
"""

from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace

__all__ = [
    "LocaleState",
    "normalize_language",
    "normalize_country",
    "normalize_currency",
    "language_display_name",
    "is_rtl_language",
    "currency_for_country",
    "get_locale",
    "set_locale",
    "reset_locale",
    "build_locale_state",
    "AUTO_LANGUAGE",
    "SUPPORTED_LANGUAGES",
]

# Sentinel meaning "let the model detect the language from the user's own words".
# Used by the conversational AI search path, never by the structured Deal Brain.
AUTO_LANGUAGE = "auto"

# Canonical language codes the app ships translations for. Anything outside this
# set is normalized down to its closest supported code, or the default.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"en", "es", "fr", "ar", "de", "it", "pt", "nl", "tr"}
)

# The neutral default when no usable language is supplied. Spain-first product,
# overridable per deployment via DEFAULT_LOCALE.
DEFAULT_LANGUAGE: str = (os.getenv("DEFAULT_LOCALE", "es").strip().lower() or "es")
DEFAULT_COUNTRY: str = (os.getenv("DEFAULT_COUNTRY", "ES").strip().upper() or "ES")
DEFAULT_CURRENCY: str = (os.getenv("DEFAULT_CURRENCY", "EUR").strip().upper() or "EUR")

# Non-trivial mappings from non-canonical tags to a supported language.
# e.g. Moroccan Darija ("ary") is served as Arabic.
_LANGUAGE_ALIASES: dict[str, str] = {
    "ary": "ar",
    "arz": "ar",
    "darija": "ar",
    "cat": "es",  # Catalan UI strings are not shipped; fall back to Spanish.
    "ca": "es",
    "gl": "es",
    "eu": "es",
    "pt-br": "pt",
    "pt-pt": "pt",
    "en-gb": "en",
    "en-us": "en",
}

# Human-readable names injected into LLM prompts so the model is told, in plain
# language, exactly which language to write its human-facing strings in.
_LANGUAGE_DISPLAY_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "ar": "Arabic (العربية)",
    "de": "German (Deutsch)",
    "it": "Italian (Italiano)",
    "pt": "Portuguese (Português)",
    "nl": "Dutch (Nederlands)",
    "tr": "Turkish (Türkçe)",
}

_RTL_LANGUAGES: frozenset[str] = frozenset({"ar"})

# Compact country -> ISO 4217 currency map (mirrors routes/i18n.py). Used to
# derive a currency when the client sent a country but no currency.
_COUNTRY_CURRENCY: dict[str, str] = {
    "ES": "EUR", "FR": "EUR", "DE": "EUR", "IT": "EUR", "PT": "EUR",
    "NL": "EUR", "BE": "EUR", "IE": "EUR", "AT": "EUR", "FI": "EUR",
    "GB": "GBP", "US": "USD", "CA": "CAD", "MA": "MAD", "DZ": "DZD",
    "TN": "TND", "SA": "SAR", "AE": "AED", "QA": "QAR", "KW": "KWD",
    "EG": "EGP", "TR": "TRY", "BR": "BRL", "MX": "MXN",
}


def normalize_language(value: str | None, *, allow_auto: bool = False) -> str:
    """Reduce any locale-ish string to a supported, canonical language code.

    Handles dirty real-world input: ``"ar_MA"``, ``"ary"``, ``"es-419"``,
    ``"en-US"``, ``"GLOBAL"``, ``" PT "``, ``None``. Returns a code from
    :data:`SUPPORTED_LANGUAGES`, the :data:`AUTO_LANGUAGE` sentinel (only when
    ``allow_auto`` is set and the caller asked for auto-detection), or the
    configured default.
    """
    if value is None:
        return DEFAULT_LANGUAGE

    cleaned = value.strip().lower()
    if not cleaned:
        return DEFAULT_LANGUAGE

    if allow_auto and cleaned in {"auto", "automatic", "detect"}:
        return AUTO_LANGUAGE

    # "global" is a country/marketplace concept, never a language.
    if cleaned in {"global", "all", "*", "und", "zxx"}:
        return DEFAULT_LANGUAGE

    # Whole-string alias (catches "pt-br", "en-us", "ary", etc.).
    if cleaned in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[cleaned]

    # Primary subtag, e.g. "ar_MA" -> "ar", "es-419" -> "es".
    primary = cleaned.replace("_", "-").split("-", 1)[0]
    if primary in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[primary]
    if primary in SUPPORTED_LANGUAGES:
        return primary

    return DEFAULT_LANGUAGE


def normalize_country(value: str | None) -> str | None:
    """Return a clean 2-letter uppercase ISO country code, or ``None``.

    ``"GLOBAL"``, empty, or malformed values resolve to ``None`` so callers can
    apply their own marketplace-wide defaults.
    """
    if value is None:
        return None
    cleaned = value.strip().upper().replace("_", "-").split("-", 1)[0]
    if len(cleaned) != 2 or not cleaned.isalpha():
        return None
    if cleaned in {"XX", "ZZ"}:
        return None
    return cleaned


def normalize_currency(value: str | None) -> str | None:
    """Return a clean 3-letter uppercase ISO 4217 code, or ``None``."""
    if value is None:
        return None
    cleaned = value.strip().upper()
    if len(cleaned) != 3 or not cleaned.isalpha():
        return None
    return cleaned


def currency_for_country(country: str | None) -> str | None:
    """Best-effort currency for a country code (or ``None`` if unknown)."""
    if not country:
        return None
    return _COUNTRY_CURRENCY.get(country.upper())


def language_display_name(language: str) -> str:
    """Human-readable language name for prompt injection."""
    return _LANGUAGE_DISPLAY_NAMES.get(language, _LANGUAGE_DISPLAY_NAMES["en"])


def is_rtl_language(language: str) -> bool:
    return language in _RTL_LANGUAGES


@dataclass(frozen=True, slots=True)
class LocaleState:
    """Immutable, request-scoped locale context."""

    language: str = DEFAULT_LANGUAGE
    country: str | None = None
    currency: str | None = None
    # The original, unsanitized X-App-Locale value, kept for diagnostics/logging.
    raw_language: str = ""

    @property
    def effective_country(self) -> str:
        return self.country or DEFAULT_COUNTRY

    @property
    def effective_currency(self) -> str:
        return (
            self.currency
            or currency_for_country(self.country)
            or DEFAULT_CURRENCY
        )

    @property
    def display_name(self) -> str:
        return language_display_name(self.language)

    @property
    def is_rtl(self) -> bool:
        return is_rtl_language(self.language)

    @property
    def is_auto(self) -> bool:
        return self.language == AUTO_LANGUAGE

    def merged_with(
        self,
        *,
        language: str | None = None,
        country: str | None = None,
        currency: str | None = None,
        allow_auto: bool = False,
    ) -> "LocaleState":
        """Return a copy where any provided override takes precedence.

        Used to let an explicit request-body value (e.g. ``user.language``)
        override the header-derived context for a single call.
        """
        next_language = self.language
        if language is not None and language.strip():
            next_language = normalize_language(language, allow_auto=allow_auto)

        next_country = country if (country := normalize_country(country)) else self.country
        next_currency = (
            normalized
            if (normalized := normalize_currency(currency))
            else self.currency
        )

        return replace(
            self,
            language=next_language,
            country=next_country,
            currency=next_currency,
        )

    @classmethod
    def default(cls) -> "LocaleState":
        return cls()


def build_locale_state(
    *,
    locale_header: str | None,
    accept_language: str | None,
    country_header: str | None,
    currency_header: str | None,
    query_language: str | None = None,
    query_country: str | None = None,
    query_currency: str | None = None,
    allow_auto: bool = False,
) -> LocaleState:
    """Assemble a :class:`LocaleState` from all available request signals.

    Precedence for language: explicit ``X-App-Locale`` > query param >
    ``Accept-Language`` > default. ``Accept-Language`` may carry a quality list
    (``"fr-CA,fr;q=0.9,en;q=0.8"``); only the first tag is considered.
    """
    raw_language = (locale_header or query_language or accept_language or "").strip()

    language = DEFAULT_LANGUAGE
    if locale_header and locale_header.strip():
        language = normalize_language(locale_header, allow_auto=allow_auto)
    elif query_language and query_language.strip():
        language = normalize_language(query_language, allow_auto=allow_auto)
    elif accept_language and accept_language.strip():
        first_tag = accept_language.split(",", 1)[0].split(";", 1)[0]
        language = normalize_language(first_tag, allow_auto=allow_auto)

    country = normalize_country(country_header) or normalize_country(query_country)
    currency = normalize_currency(currency_header) or normalize_currency(query_currency)

    return LocaleState(
        language=language,
        country=country,
        currency=currency,
        raw_language=raw_language,
    )


# --- The actual contextvar -------------------------------------------------

_LOCALE_CTX: ContextVar[LocaleState] = ContextVar(
    "ofertix_request_locale",
    default=LocaleState.default(),
)


def get_locale() -> LocaleState:
    """Return the locale state for the current request/task."""
    return _LOCALE_CTX.get()


def set_locale(state: LocaleState) -> Token[LocaleState]:
    """Bind a locale state to the current request/task. Returns a reset token."""
    return _LOCALE_CTX.set(state)


def reset_locale(token: Token[LocaleState]) -> None:
    """Restore the previous locale state using the token from :func:`set_locale`."""
    _LOCALE_CTX.reset(token)
