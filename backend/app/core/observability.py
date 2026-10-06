"""Prometheus metrics + health helpers.

Metric names are the contract used by infrastructure/monitoring/alerts.yml.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


def _make(name: str, *args, **kwargs):
    """Get-or-create so repeated imports (tests) never raise DuplicatedTimeseries."""
    try:
        return getattr(REGISTRY, "_names_to_collectors", {})[name]
    except Exception:
        pass
    try:
        existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
        if existing is not None:
            return existing
    except Exception:
        pass
    return (args and args[0](name, *args[1:], **kwargs)) or Counter(name, *args, **kwargs)


HTTP_REQUESTS = _make(
    "dv_http_requests_total",
    Counter,
    "Total HTTP requests",
    ["method", "route", "status"],
)
HTTP_LATENCY = _make(
    "dv_http_request_duration_seconds",
    Histogram,
    "HTTP request duration",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
MODEL_INFERENCES = _make(
    "dv_model_inference_total",
    Counter,
    "Model inference calls",
    ["model_name", "model_version", "outcome"],
)
MODEL_LATENCY = _make(
    "dv_model_inference_duration_seconds",
    Histogram,
    "Model inference duration",
    ["model_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
PROVIDER_CALLS = _make(
    "dv_provider_calls_total",
    Counter,
    "External provider calls",
    ["provider", "operation", "outcome"],
)
JOB_COUNTER = _make(
    "dv_jobs_total",
    Counter,
    "Background jobs processed",
    ["kind", "status"],
)
JOB_QUEUE_DEPTH = _make("dv_job_queue_depth", Gauge, "Pending jobs in the queue")
LLM_TOKEN_COUNTER = _make(
    "dv_llm_tokens_total",
    Counter,
    "LLM tokens consumed, by provider and direction (prompt/completion)",
    ["provider", "kind"],
)
# Backwards-compatible alias used by older call sites.
LLM_TOKENS = LLM_TOKEN_COUNTER
NOTIFICATION_COUNTER = _make(
    "dv_notifications_total",
    Counter,
    "Notifications created/sent, by type and channel",
    ["type", "channel"],
)
AI_FEEDBACK = _make(
    "dv_ai_feedback_total", Counter, "User feedback on AI outputs", ["model_name", "verdict"]
)
ERRORS = _make("dv_errors_total", Counter, "Handled application errors", ["code", "route"])


def metrics_payload() -> bytes:
    return generate_latest(REGISTRY)


@contextmanager
def observe_model_call(model_name: str, model_version: str = "unknown") -> Iterator[None]:
    start = time.perf_counter()
    outcome = "success"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        MODEL_LATENCY.labels(model_name=model_name).observe(time.perf_counter() - start)
        MODEL_INFERENCES.labels(
            model_name=model_name, model_version=model_version or "unknown", outcome=outcome
        ).inc()


@contextmanager
def observe_provider_call(provider: str, operation: str) -> Iterator[None]:
    outcome = "success"
    try:
        yield
    except Exception:
        outcome = "error"
        raise
    finally:
        PROVIDER_CALLS.labels(provider=provider, operation=operation, outcome=outcome).inc()


# ---------------------------------------------------------------------------
# Readiness contract
# ---------------------------------------------------------------------------
# Component health is produced by different subsystems (database_health(),
# Cache.health(), the provider matrix), each with its own dictionary shape. A
# probe or dashboard has to be able to parse them uniformly, so /ready normalises
# every component to carry a `status` of one of these three values while keeping
# the subsystem's own fields intact.
COMPONENT_STATUSES = ("ok", "degraded", "unavailable")


def component_status(component: dict) -> str:
    """Derive a tri-state status from a component health dictionary."""
    explicit = component.get("status")
    if isinstance(explicit, str) and explicit in COMPONENT_STATUSES:
        return explicit
    if component.get("available") is True or component.get("reachable") is True:
        # Reachable but explicitly flagged as not production-ready still counts as
        # degraded, so a demo provider cannot be mistaken for a healthy one.
        if component.get("is_demo") is True or component.get("degraded") is True:
            return "degraded"
        return "ok"
    if component.get("available") is False or component.get("reachable") is False:
        return "unavailable"
    return "degraded" if component else "unavailable"


def normalized_components(checks: dict[str, dict]) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for name, component in checks.items():
        if not isinstance(component, dict):
            normalized[name] = {"status": "ok" if component else "unavailable", "value": component}
            continue
        normalized[name] = {**component, "status": component_status(component)}
    return normalized
