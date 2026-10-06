"""Rate limiting.

Fixed-window counters in Redis (shared across API replicas), with an in-process
fallback from app.core.cache when Redis is down. Limits are applied per route
class, keyed by authenticated user id where available, otherwise by client IP
(with X-Forwarded-For honoured only for the first hop, since the app always runs
behind Nginx/ALB).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.core.cache import get_cache
from app.core.config import settings
from app.core.errors import RateLimitedError


@dataclass(frozen=True, slots=True)
class Limit:
    limit: int
    window_seconds: int
    name: str


# Route-class limits. Values are deliberately conservative for credential
# flows and generous for read paths.
LIMITS = {
    "auth_otp": Limit(limit=5, window_seconds=900, name="auth_otp"),
    "auth_login": Limit(limit=10, window_seconds=900, name="auth_login"),
    "auth_register": Limit(limit=5, window_seconds=3600, name="auth_register"),
    "auth_refresh": Limit(limit=60, window_seconds=3600, name="auth_refresh"),
    "write": Limit(limit=120, window_seconds=3600, name="write"),
    "ai": Limit(limit=30, window_seconds=3600, name="ai"),
    "upload": Limit(limit=40, window_seconds=3600, name="upload"),
    "search": Limit(limit=300, window_seconds=3600, name="search"),
    "read": Limit(limit=600, window_seconds=3600, name="read"),
}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_key(request: Request, name: str) -> str:
    user_id = getattr(request.state, "user_id", None)
    identity = f"u:{user_id}" if user_id else f"ip:{client_ip(request)}"
    return f"dv:rl:{name}:{identity}"


def enforce_rate_limit(request: Request, name: str) -> dict[str, str]:
    """Raise RateLimitedError when the caller exceeded the limit for `name`.

    Returns headers to attach to the response on success.
    """
    limit = LIMITS[name]
    if not settings.rate_limit_enabled:
        return {}
    cache = get_cache()
    allowed, remaining, retry_after = cache.rate_limit(
        rate_limit_key(request, name), limit.limit, limit.window_seconds
    )
    headers = {
        "X-RateLimit-Limit": str(limit.limit),
        "X-RateLimit-Remaining": str(remaining),
    }
    if not allowed:
        raise RateLimitedError(
            f"Too many requests for {name}. Try again in {retry_after} seconds.",
            retry_after=retry_after,
            details={"limit": limit.limit, "window_seconds": limit.window_seconds},
        )
    return headers


def limit_for_request(request: Request) -> str:
    """Classify a request when a route does not declare an explicit limit."""
    path = request.url.path
    method = request.method.upper()
    if "/auth/otp" in path:
        return "auth_otp"
    if "/auth/login" in path or "/auth/password" in path:
        return "auth_login"
    if "/auth/register" in path:
        return "auth_register"
    if "/auth/refresh" in path:
        return "auth_refresh"
    if path.startswith(f"{settings.api_v1_prefix}/ai"):
        return "ai"
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    if "/search" in path:
        return "search"
    return "read"
