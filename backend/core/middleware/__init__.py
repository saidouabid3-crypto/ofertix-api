"""Custom ASGI/HTTP middleware for the Ofertix backend."""

from core.middleware.locale_middleware import LocaleMiddleware

__all__ = ["LocaleMiddleware"]
