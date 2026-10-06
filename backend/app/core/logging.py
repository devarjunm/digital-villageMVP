"""Structured logging with request correlation and secret redaction.

- LOG_FORMAT=json  → one JSON object per line (production default)
- LOG_FORMAT=console → human readable line (development)

A redaction filter removes anything that looks like a credential before it is
emitted, so a careless log call cannot leak tokens, OTPs or passwords.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from app.core.config import settings
from app.core.context import get_context

_SECRET_KEY_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "otp",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "refresh",
    "code_hash",
)

_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{10,13})(?!\d)")
_OTP_KEYS = ("otp", "code")


def _redact(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(v, key) for v in value]
    if isinstance(value, str):
        if key and any(h in key.lower() for h in _SECRET_KEY_HINTS) and len(value) <= 64:
            return "***redacted***"
        value = _JWT_RE.sub("***jwt***", value)
        if key and key.lower() in _OTP_KEYS:
            return "***redacted***"
        return value
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict):
            record.args = _redact(record.args)
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            record.extra_fields = _redact(record.extra_fields)  # type: ignore[attr-defined]
        return True


class ContextFilter(logging.Filter):
    """Attaches request_id/user_id/route from the contextvar without callers
    having to pass them explicitly."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_context()
        record.request_id = ctx.request_id if ctx else None
        record.user_id = ctx.user_id if ctx else None
        record.route = ctx.route if ctx else None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in ("request_id", "user_id", "route"):
            value = getattr(record, field_name, None)
            if value:
                payload[field_name] = value
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(_redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        bits = []
        for field_name in ("request_id", "user_id", "route"):
            value = getattr(record, field_name, None)
            if value:
                bits.append(f"{field_name.split('_')[0]}={value}")
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            bits.extend(f"{k}={_redact(v, k)}" for k, v in _redact(extra).items())
        if bits:
            base += "  [" + " ".join(str(b) for b in bits) + "]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_CONFIGURED = False


def configure_logging() -> None:
    """Idempotent root logging configuration."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else ConsoleFormatter())
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    # Third-party noise control
    for noisy, level in {
        "uvicorn.access": logging.WARNING,
        "uvicorn.error": logging.INFO,
        "sqlalchemy.engine": logging.INFO if settings.db_echo else logging.WARNING,
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "multipart": logging.WARNING,
    }.items():
        logging.getLogger(noisy).setLevel(level)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Log with structured fields that the formatter renders and redacts."""
    logger.log(level, message, extra={"extra_fields": fields})
