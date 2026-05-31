"""Request-scoped locale middleware.

Extracts the locale signals emitted by the Flutter client (Phase 1) and binds a
normalized :class:`~core.locale_context.LocaleState` to a contextvar for the
lifetime of the request. Every downstream AI service and prompt builder reads
from that contextvar, so the user's active UI language drives every AI verdict,
insight, and assistant reply without any per-call plumbing.

The headers consumed (set by ``LocaleResolver`` on the client):
    - ``X-App-Locale``      authoritative app UI language (e.g. ``es``)
    - ``Accept-Language``   standard fallback (e.g. ``fr-CA,fr;q=0.9``)
    - ``X-App-Country``     shopping country (e.g. ``ES``)
    - ``X-App-Currency``    shopping currency (e.g. ``EUR``)

As an extra safety net for non-Flutter callers and deep links, query parameters
``lang``/``locale``, ``country`` and ``currency`` are also honored.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.locale_context import build_locale_state, reset_locale, set_locale

logger = logging.getLogger("ofertix.locale")


class LocaleMiddleware(BaseHTTPMiddleware):
    """Binds a normalized locale to the request contextvar.

    A token is always reset in ``finally`` so the contextvar can never leak
    across requests, even if the downstream handler raises.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        query = request.query_params

        state = build_locale_state(
            locale_header=request.headers.get("X-App-Locale"),
            accept_language=request.headers.get("Accept-Language"),
            country_header=request.headers.get("X-App-Country"),
            currency_header=request.headers.get("X-App-Currency"),
            query_language=query.get("locale") or query.get("lang"),
            query_country=query.get("country"),
            query_currency=query.get("currency"),
        )

        token = set_locale(state)
        try:
            response = await call_next(request)
        finally:
            reset_locale(token)

        # Echo the resolved locale so clients/proxies can verify negotiation.
        response.headers["Content-Language"] = state.language
        response.headers["X-Resolved-Locale"] = state.language
        return response
