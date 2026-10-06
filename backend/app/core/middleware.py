"""ASGI middleware: request context, timing, security headers, rate limiting."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core import observability
from app.core.config import settings
from app.core.context import new_request_context
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.ratelimit import enforce_rate_limit, limit_for_request

logger = get_logger(__name__)

_EXEMPT_FROM_RATE_LIMIT = {"/health", "/ready", "/metrics", "/openapi.json", "/docs", "/redoc"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Binds a request id, logs the completed request with latency, and adds
    correlation/security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming_id = request.headers.get("x-request-id", "")
        ctx = new_request_context(incoming_id if _looks_like_request_id(incoming_id) else None)
        ctx.route = request.url.path
        ctx.method = request.method
        ctx.ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else None
        )
        request.state.request_id = ctx.request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except AppError as exc:  # handled by exception handlers, but keep the id consistent
            raise exc
        duration = time.perf_counter() - start

        route_label = _route_label(request)
        observability.HTTP_REQUESTS.labels(
            method=request.method, route=route_label, status=str(response.status_code)
        ).inc()
        observability.HTTP_LATENCY.labels(method=request.method, route=route_label).observe(
            duration
        )

        response.headers["X-Request-ID"] = ctx.request_id
        response.headers["X-Process-Time"] = f"{duration:.4f}"
        _apply_security_headers(response)

        if request.url.path not in _EXEMPT_FROM_RATE_LIMIT:
            logger.info(
                "request_completed",
                extra={
                    "extra_fields": {
                        "status": response.status_code,
                        "duration_ms": round(duration * 1000, 2),
                        "route": route_label,
                        "method": request.method,
                    }
                },
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies the default limit for the route class. Routes that need a
    different limit declare it explicitly via the `enforce_rate_limit`
    dependency, which raises before the handler runs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _EXEMPT_FROM_RATE_LIMIT or not settings.rate_limit_enabled:
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        try:
            headers = enforce_rate_limit(request, limit_for_request(request))
        except AppError as exc:
            from app.main import app_error_handler  # local import avoids a cycle

            return await app_error_handler(request, exc)
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        return response


def _apply_security_headers(response: Response) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(self), microphone=()"
    )
    response.headers.setdefault("Cache-Control", "no-store")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    # Collapse identifiers so metrics stay low-cardinality.
    parts = []
    for part in path.split("/"):
        parts.append("{id}" if _looks_like_id(part) else part)
    return "/".join(parts)


def _looks_like_id(part: str) -> bool:
    if len(part) == 36 and part.count("-") == 4:
        return True  # uuid
    return part.isdigit() and len(part) >= 4


def _looks_like_request_id(value: str) -> bool:
    cleaned = value.strip()
    return 8 <= len(cleaned) <= 64 and all(c.isalnum() or c in "-_" for c in cleaned)


def new_request_id() -> str:
    return uuid.uuid4().hex
