from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware


def success_payload(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def error_payload(message: str, *, data: Any = None) -> dict[str, Any]:
    return {"success": False, "data": data, "error": message or "Unknown error"}


def wrap_json_response(status_code: int, body: Any) -> JSONResponse:
    if isinstance(body, dict) and {"success", "data", "error"} <= set(body.keys()):
        return JSONResponse(status_code=status_code, content=body)

    if status_code >= 400:
        message = None
        if isinstance(body, dict):
            message = (
                body.get("error")
                or body.get("safeMessage")
                or body.get("detail")
                or body.get("message")
            )
        return JSONResponse(
            status_code=status_code,
            content=error_payload(str(message or "Request failed"), data=body if isinstance(body, dict) else None),
        )

    return JSONResponse(status_code=status_code, content=success_payload(body))


_SKIP_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/api/ai",
)


class ApiEnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap JSON API responses in {success, data, error} without breaking monetization routes."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)

        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" not in content_type:
            return response
        if "ndjson" in content_type or "text/event-stream" in content_type:
            return response
        if getattr(response, "status_code", 200) == 204:
            return response

        body_bytes = b""
        if hasattr(response, "body_iterator"):
            chunks = [chunk async for chunk in response.body_iterator]
            body_bytes = b"".join(chunks)
        elif hasattr(response, "body"):
            body_bytes = response.body or b""

        if not body_bytes:
            wrapped = error_payload("Empty response") if response.status_code >= 400 else success_payload(None)
            return JSONResponse(status_code=response.status_code, content=wrapped, headers=dict(response.headers))

        try:
            decoded = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            return Response(content=body_bytes, status_code=response.status_code, headers=dict(response.headers))

        wrapped_response = wrap_json_response(response.status_code, decoded)
        for key, value in response.headers.items():
            if key.lower() not in {"content-length", "content-type"}:
                wrapped_response.headers[key] = value
        return wrapped_response
