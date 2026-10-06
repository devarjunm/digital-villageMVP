"""FastAPI application factory.

Boot order: logging → database engine → middleware → routers → error handlers.
The app never creates schema implicitly; `alembic upgrade head` is the only way
tables appear (see backend/alembic).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

# Importing the aggregate model map guarantees that every mapped class is
# registered on `Base.metadata` before the first request. Without it, a flush can
# fail with "could not find table 'background_jobs'" style errors when a service
# creates a row whose foreign key points at a table owned by another domain
# package that this process happens not to have imported yet.
import app.models
from app.api.v1.router import api_router
from app.core.cache import get_cache
from app.core.config import settings
from app.core.context import current_request_id, get_context
from app.core.errors import AppError, error_envelope
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.core.observability import ERRORS, metrics_payload, normalized_components
from app.database.capabilities import supports_pgvector
from app.database.session import database_health, dispose_engine, get_engine

configure_logging()
logger = get_logger(__name__)

APP_VERSION = "0.1.0"
API_DESCRIPTION = """
Digital Village — farmer-focused platform API.

**Data provenance is part of the contract.** Every response carrying weather,
market, scheme or AI data declares its source:
`provider` / `source` / `is_demo` for observed data, `model_name` +
`model_version` + `confidence` for model output, `trust_label` for community
content. Demo-mode responses say so explicitly and are never mixed with live data.
"""

TAGS_METADATA = [
    {"name": "auth", "description": "Registration, OTP, login, sessions, recovery."},
    {"name": "farmers", "description": "Farmer profile and public profile."},
    {"name": "farms", "description": "Farm records, soil tests, farm dashboard."},
    {"name": "crops", "description": "Planted crops, stages, crop activity log."},
    {"name": "community", "description": "Posts, comments, reactions, saves, follows, reports."},
    {"name": "moderation", "description": "Moderation queue, actions, audit log."},
    {"name": "weather", "description": "Current conditions, forecast, alerts (provider-tagged)."},
    {"name": "markets", "description": "Market prices (actual vs model estimate) and trends."},
    {"name": "schemes", "description": "Government schemes and deterministic eligibility checks."},
    {
        "name": "knowledge",
        "description": "Knowledge base, retrieval and RAG answers with citations.",
    },
    {"name": "search", "description": "Global keyword/semantic/hybrid search."},
    {"name": "ai", "description": "Crop doctor, recommendation, yield, price, assistant, agent."},
    {"name": "notifications", "description": "Notifications and preferences."},
    {
        "name": "admin",
        "description": "Admin console: users, moderation, content, AI ops, analytics.",
    },
    {"name": "analytics", "description": "Privacy-conscious product events."},
    {"name": "ops", "description": "Health, readiness and metrics."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db = database_health()
    if not db.get("available"):
        logger.error(
            "startup_database_unavailable",
            extra={"extra_fields": {"detail": db.get("detail", "")[:300]}},
        )
    else:
        logger.info(
            "startup_database_ready",
            extra={
                "extra_fields": {
                    "flavor": db.get("flavor"),
                    "version": db.get("version"),
                    "pgvector": db.get("pgvector"),
                }
            },
        )
    cache = get_cache()
    logger.info(
        "startup_providers",
        extra={
            "extra_fields": {
                "providers": settings.provider_status(),
                "cache": cache.backend,
                "demo_mode": settings.demo_mode,
            }
        },
    )
    yield
    dispose_engine()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=APP_VERSION,
        description=API_DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        docs_url="/docs" if not settings.is_production or settings.app_debug else "/docs",
        redoc_url="/redoc" if settings.app_env != "production" else None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
        contact={"name": "Digital Village", "url": "https://example.invalid/digital-village"},
        license_info={"name": "MIT"},
    )

    # ------------------------------------------------------------- middleware
    # Order matters: CORS outermost so preflight never hits rate limiting.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept-Language",
            "X-Client",
            "X-Request-ID",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Process-Time",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
        max_age=600,
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # --------------------------------------------------------------- routers
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Local object storage (development). In production, files are served by the
    # CDN / object store, never by the API process.
    if settings.storage_backend == "local":
        app.mount(
            "/files",
            StaticFiles(directory=str(settings.storage_dir), check_dir=False),
            name="files",
        )

    _register_error_handlers(app)
    _register_ops_routes(app)
    return app


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Single AppError → JSON envelope renderer.

    Defined at module level because `app.core.middleware` renders the same envelope
    for errors raised inside middleware (before routing), and importing this handler
    avoids two divergent error shapes for the same exception type.
    """
    ctx = get_context()
    route = request.scope.get("route")
    ERRORS.labels(code=exc.code, route=getattr(route, "path", request.url.path)).inc()
    if exc.http_status >= 500:
        logger.error(
            "app_error",
            extra={
                "extra_fields": {"code": exc.code, "detail": exc.message, "status": exc.http_status}
            },
        )
    else:
        logger.info(
            "client_error",
            extra={
                "extra_fields": {"code": exc.code, "detail": exc.message, "status": exc.http_status}
            },
        )
    headers = {}
    if exc.code == "rate_limited":
        retry_after = getattr(exc, "retry_after", 60)
        headers["Retry-After"] = str(retry_after)
    elif exc.http_status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=exc.http_status,
        content=error_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=ctx.request_id if ctx else current_request_id(),
        ),
        headers=headers,
    )


def _register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(AppError)(app_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = {
            "fields": [
                {
                    "loc": ".".join(str(p) for p in err.get("loc", [])),
                    "msg": err.get("msg"),
                    "type": err.get("type"),
                }
                for err in exc.errors()[:25]
            ]
        }
        ERRORS.labels(code="validation_error", route=request.url.path).inc()
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                code="validation_error",
                message="Some of the submitted values are invalid. Please check the highlighted fields.",
                details=details,
                request_id=current_request_id(),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            415: "unsupported_media_type",
            429: "rate_limited",
        }
        code = codes.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(
                code=code, message=message, details=None, request_id=current_request_id()
            ),
            headers=getattr(exc, "headers", None) or None,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        # Constraint violations are expected (duplicate handle, invalid FK...).
        # The SQL text is logged for operators and not returned to the client.
        logger.warning("integrity_error", extra={"extra_fields": {"detail": str(exc.orig)[:300]}})
        ERRORS.labels(code="conflict", route=request.url.path).inc()
        return JSONResponse(
            status_code=409,
            content=error_envelope(
                code="conflict",
                message="That action conflicts with existing data.",
                details={},
                request_id=current_request_id(),
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database_error")
        ERRORS.labels(code="database_error", route=request.url.path).inc()
        return JSONResponse(
            status_code=503,
            content=error_envelope(
                code="database_unavailable",
                message="The database is temporarily unavailable. Please try again.",
                details={},
                request_id=current_request_id(),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Full detail to the log (with the request id), nothing sensitive to the client.
        logger.exception("unhandled_exception", extra={"extra_fields": {"path": request.url.path}})
        ERRORS.labels(code="internal_error", route=request.url.path).inc()
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                code="internal_error",
                message="Something went wrong on our side. The issue has been logged.",
                details={},
                request_id=current_request_id(),
            ),
        )


def readiness_payload() -> tuple[dict[str, object], bool]:
    """Compute readiness once, for both `/ready` and the HTML landing page.

    Returns `(payload, critical_ok)`. Kept at module level so the landing page
    cannot report a different picture from the probe a load balancer uses.
    """
    db = database_health()
    cache = get_cache().health()
    vector_ok = supports_pgvector(get_engine()) if db.get("available") else False
    models_dir = settings.models_path
    checks = {
        "database": db,
        "cache": cache,
        "pgvector": {"available": vector_ok},
        "model_directory": {
            "path": str(models_dir),
            "exists": models_dir.exists(),
            "artifacts": sorted(p.name for p in models_dir.glob("*"))
            if models_dir.exists()
            else [],
        },
    }
    components = normalized_components(checks)
    # Providers get their own block: each one is reachable *and* either a
    # development stand-in or a configured production dependency. A demo provider
    # is reported `degraded` — never `ok` — so a monitoring rule ("alert if any
    # component is degraded") catches an accidental production deployment that is
    # still serving mock weather or LLM data.
    providers = {
        name: {**entry, "status": "degraded" if entry.get("is_demo") else "ok"}
        for name, entry in settings.provider_status().items()
    }
    critical_ok = bool(db.get("available"))
    demo_providers = sorted(
        name for name, entry in providers.items() if entry["status"] == "degraded"
    )
    payload: dict[str, object] = {
        "status": "ready" if critical_ok else "degraded",
        "ready": critical_ok,
        "demo_mode": settings.demo_mode,
        "components": components,
        "providers": providers,
        "checks": checks,
        "notes": (
            [
                f"Demo providers in use: {', '.join(demo_providers)}. Responses are labelled "
                "is_demo=true and must not be treated as real weather, market or AI output."
            ]
            if demo_providers
            else []
        ),
    }
    return payload, critical_ok


def _root_summary(readiness: dict[str, object]) -> dict[str, object]:
    """JSON shape of `/` for API clients."""
    return {
        "service": settings.app_name,
        "api": settings.api_v1_prefix,
        "docs": "/docs",
        "docs_note": (
            "/docs loads Swagger UI assets from a CDN, so it needs network access. "
            "This JSON document and the HTML landing page do not."
        ),
        "health": "/health",
        "ready": "/ready",
        "metrics": "/metrics",
        "version": APP_VERSION,
        "demo_mode": settings.demo_mode,
        "status": readiness.get("status"),
        "note": (
            "Demo mode is active: external providers are served locally and their "
            "responses are labelled is_demo=true."
            if settings.demo_mode
            else "External providers are configured from the environment."
        ),
    }


def _endpoint_groups(app: FastAPI) -> list[tuple[str, int]]:
    """Count mounted operations per API group, read from the live OpenAPI schema."""
    groups: dict[str, int] = {}
    for path, operations in app.openapi().get("paths", {}).items():
        prefix = settings.api_v1_prefix
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :].strip("/")
        if not remainder:
            continue
        group = remainder.split("/", 1)[0]
        groups[group] = groups.get(group, 0) + len(operations)
    return sorted(groups.items())


def render_status_page(app: FastAPI) -> str:
    """A self-contained, server-rendered status page for the API's front door.

    No scripts, stylesheets, fonts or images are loaded from the network, so the
    page renders in a sandboxed preview pane as well as in a normal browser, and
    every figure on it comes from the same readiness computation `/ready` serves.
    """
    import html as html_lib

    payload, critical_ok = readiness_payload()
    components = payload.get("components") or {}
    providers = payload.get("providers") or {}
    notes = payload.get("notes") or []

    def esc(value: object) -> str:
        return html_lib.escape(str(value))

    def colour(status: object) -> str:
        return {"ok": "#0b7a3b", "degraded": "#a35b00", "down": "#a11212"}.get(str(status), "#555")

    component_rows = "".join(
        f"<tr><td>{esc(name)}</td>"
        f"<td style='color:{colour(entry.get('status'))};font-weight:600'>{esc(entry.get('status'))}</td>"
        f"<td>{esc(entry.get('backend') or entry.get('version') or entry.get('path') or '')}</td></tr>"
        for name, entry in components.items()
    )
    provider_rows = "".join(
        f"<tr><td>{esc(name)}</td>"
        f"<td style='color:{colour(entry.get('status'))};font-weight:600'>{esc(entry.get('status'))}</td>"
        f"<td>{esc(entry.get('provider'))}</td>"
        f"<td>{'yes' if entry.get('is_demo') else 'no'}</td></tr>"
        for name, entry in providers.items()
    )
    group_rows = "".join(
        f"<tr><td><code>{esc(settings.api_v1_prefix)}/{esc(group)}</code></td><td>{count} operations</td></tr>"
        for group, count in _endpoint_groups(app)
    )
    notes_html = (
        "<ul>" + "".join(f"<li>{esc(note)}</li>" for note in notes) + "</ul>" if notes else ""
    )
    demo_banner = (
        "<p style='background:#fff5e6;border:1px solid #f0c98a;padding:10px 12px;border-radius:6px'>"
        "<strong>Demo mode is active.</strong> External providers are served locally; every response "
        "they produce carries <code>is_demo: true</code> and a notice. Seeded rows are marked "
        "<code>is_demo</code> and must not be presented as verified agricultural, market or scheme "
        "information.</p>"
        if settings.demo_mode
        else "<p><strong>Production provider configuration is active</strong> (no demo providers).</p>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(settings.app_name)} API — status</title>
</head>
<body style="margin:0;padding:24px;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#14210f;background:#f7f8f6">
<main style="max-width:880px;margin:0 auto">
  <h1 style="margin:0 0 4px;font-size:24px">{esc(settings.app_name)} API</h1>
  <p style="margin:0 0 16px;color:#4a5546">
    version {esc(APP_VERSION)} · environment {esc(settings.app_env)} ·
    <a href="/docs">/docs</a> · <a href="/openapi.json">/openapi.json</a> ·
    <a href="/health">/health</a> · <a href="/ready">/ready</a> · <a href="/metrics">/metrics</a>
  </p>
  <p style="margin:0 0 16px;padding:10px 12px;border-radius:6px;border:1px solid #bcd3c2;background:{'#eef7f0' if critical_ok else '#fdecec'}">
    Readiness: <strong style="color:{'#0b7a3b' if critical_ok else '#a11212'}">{esc(payload.get('status'))}</strong>
    — {len(components)} component(s) and {len(providers)} provider(s) reported below.
  </p>
  {demo_banner}
  <h2 style="font-size:17px;margin:22px 0 6px">Components</h2>
  <table style="width:100%;border-collapse:collapse;background:#fff">
    <thead><tr>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">component</th>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">status</th>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">detail</th>
    </tr></thead>
    <tbody>{component_rows}</tbody>
  </table>
  <h2 style="font-size:17px;margin:22px 0 6px">Providers</h2>
  <table style="width:100%;border-collapse:collapse;background:#fff">
    <thead><tr>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">capability</th>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">status</th>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">provider</th>
      <th align="left" style="padding:6px;border-bottom:1px solid #dfe5dc">demo</th>
    </tr></thead>
    <tbody>{provider_rows}</tbody>
  </table>
  {notes_html}
  <h2 style="font-size:17px;margin:22px 0 6px">API groups</h2>
  <table style="width:100%;border-collapse:collapse;background:#fff">{group_rows}</table>
  <p style="margin:18px 0 0;color:#4a5546;font-size:14px">
    Interactive documentation at <a href="/docs">/docs</a> loads its assets from a CDN, so it needs
    network access; this page does not. Demo accounts (development only, password
    <code>DemoPass!23</code>): farmer <code>+919000000001</code>, expert <code>+919000000003</code>,
    moderator <code>+919000000004</code>, admin <code>+919000000005</code>.
  </p>
  <p style="margin:14px 0 0;color:#6b756a;font-size:13px">
    Every figure above is read live from this API. Nothing on this page is a placeholder.
  </p>
</main>
</body>
</html>"""


def _register_ops_routes(app: FastAPI) -> None:
    @app.get("/health", tags=["ops"], summary="Liveness probe (no dependencies)")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": APP_VERSION,
            "environment": settings.app_env,
        }

    @app.get("/ready", tags=["ops"], summary="Readiness probe (checks dependencies)")
    async def ready(response: Response) -> dict[str, object]:
        payload, critical_ok = readiness_payload()
        if not critical_ok:
            response.status_code = 503
        return payload

    @app.get("/", include_in_schema=False)
    async def root(request: Request) -> Response:
        """The API's front door.

        Browsers get a self-contained HTML status page; API clients (and anything
        sending `Accept: application/json`) keep the JSON document. Both are built
        from the same readiness computation `/ready` serves, so the page cannot
        report a different picture from the load balancer's probe.
        """
        accept = request.headers.get("accept", "")
        if "text/html" in accept and "application/json" not in accept:
            return HTMLResponse(render_status_page(app))
        payload, _ = readiness_payload()
        return JSONResponse(_root_summary(payload))

    @app.get("/metrics", tags=["ops"], summary="Prometheus metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=metrics_payload(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )


app = create_app()
