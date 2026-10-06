"""Observability and API-contract tests.

These are the tests that must never fail: if `/health` or `/ready` lie, nothing
downstream can be trusted. They also pin the *shape* of the error envelope and
the honesty of the demo/provider disclosures, because those are product
requirements (a client must be able to tell an operator that weather is coming
from the mock provider).
"""

from __future__ import annotations

import pytest


def test_health_reports_ok_without_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "version" in body
    # Liveness must never depend on PostgreSQL: it answers even when the DB is down.
    assert "checks" not in body or isinstance(body["checks"], dict)


def test_ready_reports_component_status(client):
    """Every component reports a tri-state status a probe can act on."""
    from app.core.observability import COMPONENT_STATUSES

    response = client.get("/ready")
    assert response.status_code in {200, 503}
    body = response.json()
    assert "status" in body
    components = body.get("components") or body.get("checks") or {}
    assert isinstance(components, dict)
    assert components, "readiness must enumerate its components"
    for name, component in components.items():
        assert isinstance(component, dict), name
        assert component.get("status") in COMPONENT_STATUSES, f"{name}: {component.get('status')!r}"
    # The database is the one dependency whose absence makes the service unready.
    assert components["database"]["status"] in {"ok", "degraded"}


def test_ready_never_hides_demo_providers(client):
    """Demo mode must be stated explicitly, and never reported as healthy."""
    body = client.get("/ready").json()
    providers = body.get("providers", {})
    demo = sorted(name for name, entry in providers.items() if entry.get("is_demo"))
    if not demo:
        pytest.skip("all providers are configured for production use")
    assert body["demo_mode"] is True
    assert any("Demo providers" in note for note in body.get("notes", []))
    for name in demo:
        assert providers[name]["provider"] == "mock" or providers[name]["provider"] in {
            "local",
            "console",
        }
        assert providers[name]["status"] == "degraded"


def test_provider_matrix_is_disclosed(client):
    """An operator must be able to see which subsystems are still demo providers."""
    body = client.get("/ready").json()
    providers = body.get("providers")
    assert providers, "readiness must publish the active provider for every external subsystem"
    for name in ("weather", "market", "llm", "embeddings", "storage", "sms"):
        assert name in providers, name
        assert "provider" in providers[name], name
        assert "is_demo" in providers[name], name
        # Demo providers must never be reported as healthy.
        assert providers[name]["status"] == ("degraded" if providers[name]["is_demo"] else "ok")


def test_openapi_documents_every_router(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    required_prefixes = (
        "/api/v1/auth",
        "/api/v1/users",
        "/api/v1/farmers",
        "/api/v1/farms",
        "/api/v1/crops",
        "/api/v1/community",
        "/api/v1/weather",
        "/api/v1/markets",
        "/api/v1/schemes",
        "/api/v1/search",
        "/api/v1/ai",
        "/api/v1/notifications",
        "/api/v1/admin",
    )
    for prefix in required_prefixes:
        assert any(path.startswith(prefix) for path in paths), f"no documented route under {prefix}"


def test_error_envelope_is_consistent(client):
    """Unknown routes and validation failures use the documented error shape."""
    missing = client.get("/api/v1/users/not-a-uuid")
    assert missing.status_code in {404, 422}
    body = missing.json()
    assert "error" in body or "detail" in body

    unauthenticated = client.get("/api/v1/users/me")
    assert unauthenticated.status_code == 401
    payload = unauthenticated.json()
    error = payload.get("error", payload)
    assert error.get("code") or payload.get("detail")
    # The client must be told how to authenticate, and never shown internals.
    assert "traceback" not in unauthenticated.text.lower()


def test_landing_page_serves_html_to_browsers_and_json_to_clients(client):
    """`/` is the API's front door: negotiable, and honest in both shapes."""
    as_json = client.get("/", headers={"Accept": "application/json"})
    assert as_json.status_code == 200
    assert as_json.headers["content-type"].startswith("application/json")
    body = as_json.json()
    assert body["version"]
    assert body["health"] == "/health"
    assert body["demo_mode"] is True, "the development stack runs with demo providers"
    assert body["status"] in {"ready", "degraded"}

    as_html = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert as_html.status_code == 200
    assert as_html.headers["content-type"].startswith("text/html")
    page = as_html.text
    assert "<!doctype html>" in page.lower()
    assert "Readiness:" in page, "the page must show the live readiness status"


def test_landing_page_loads_nothing_from_the_network(client):
    """It has to render in a sandboxed preview pane, so it must be self-contained."""
    page = client.get("/", headers={"Accept": "text/html"}).text
    lowered = page.lower()
    for forbidden in ("<script", "<link", "<iframe", "<img", "@import", "cdn.", "googleapis"):
        assert forbidden not in lowered, f"the status page must not depend on {forbidden}"
    # Links to our own endpoints are fine; external absolute URLs are not.
    assert "http://" not in lowered and "https://" not in lowered


def test_landing_page_reports_the_same_state_as_the_readiness_probe(client):
    """Two views of one computation: they must not be able to disagree."""
    status = client.get("/ready").json()["status"]
    page = client.get("/", headers={"Accept": "text/html"}).text
    assert f">{status}</strong>" in page, "the page must show the same status /ready returns"

    reported = client.get("/", headers={"Accept": "application/json"}).json()["status"]
    assert reported == status


def test_landing_page_states_demo_mode_without_claiming_production(client):
    page = client.get("/", headers={"Accept": "text/html"}).text
    # The development stack is demo: the page must say so rather than looking live.
    assert "Demo mode is active" in page
    assert "is_demo" in page
