"""Request-scoped context (request id, user, route) shared by logging & metrics."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


@dataclass
class RequestContext:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    user_id: str | None = None
    route: str | None = None
    method: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ip: str | None = None

    def as_log_fields(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "route": self.route,
            "method": self.method,
        }


_ctx: ContextVar[RequestContext | None] = ContextVar("dv_request_context", default=None)


def new_request_context(request_id: str | None = None) -> RequestContext:
    ctx = RequestContext(request_id=request_id or uuid4().hex)
    _ctx.set(ctx)
    return ctx


def get_context() -> RequestContext | None:
    return _ctx.get()


def current_request_id() -> str | None:
    ctx = _ctx.get()
    return ctx.request_id if ctx else None


def current_user_id() -> str | None:
    ctx = _ctx.get()
    return ctx.user_id if ctx else None


def set_user(user_id: str | None) -> None:
    ctx = _ctx.get()
    if ctx is not None:
        ctx.user_id = user_id
