# Digital Village — Architecture

> Status legend used across all docs: **[built]** = implemented and covered by
> tests in this repo · **[partial]** = implemented with a documented gap ·
> **[planned]** = designed here, not yet implemented. Nothing is marked built
> unless it runs.

## 1. What Digital Village is

A farmer-facing digital platform with three data-class layers that are kept
strictly separate everywhere in the system:

| Class | Meaning | Example | How the UI must present it |
|---|---|---|---|
| **Observed / official** | Retrieved from a named source with a timestamp and provenance | mandi price from a configured market API, IMD/OpenWeather observation, a government scheme record with `official_source_url` | source name + timestamp or "no live source configured" |
| **Model output** | Produced by a model in this repo, with version + uncertainty | crop recommendation, disease screening, yield/price estimate | `model_version`, confidence/interval, "AI-assisted estimate" |
| **User content** | Written by a farmer/expert/moderator | community post, comment, correction | author role + trust label (farmer experience / expert / official / AI) |

Every API response that carries one of these carries the label. This is
enforced by shared Pydantic mixins (`DataSourceMixin`, `ModelOutputMixin`,
`TrustLabelMixin`) rather than by convention, see `backend/app/core/contracts.py`.

## 2. High-level container view

```
                    ┌──────────────────────────────────────────────┐
                    │            Flutter app (Android-first)       │
                    │  presentation → domain → data (clean arch.)  │
                    │  Dio API client · Riverpod state · i18n      │
                    └───────────────┬──────────────────────────────┘
                          HTTPS/JSON │ REST /api/v1/*  (+ /files/*)
                    ┌───────────────▼──────────────────────────────┐
                    │     Nginx (TLS termination, rate limit,       │
                    │     request-id, security headers)             │
                    └───────────────┬──────────────────────────────┘
                    ┌───────────────▼──────────────────────────────┐
                    │  FastAPI app (Uvicorn, Gunicorn workers)      │
                    │  api/v1 routers → services → repositories     │
                    │  core: config, security, errors, logging,     │
                    │  rate limiting, cache, observability          │
                    └───┬───────────┬──────────┬───────────┬────────┘
                        │           │          │           │
             ┌──────────▼──┐  ┌─────▼────┐ ┌───▼───────┐ ┌─▼──────────────┐
             │ PostgreSQL  │  │  Redis   │ │ Object    │ │ MLflow tracking│
             │ + pgvector  │  │ cache +  │ │ storage   │ │ + registry     │
             │ (system of  │  │ job queue│ │ (local/S3)│ │ (experiments)  │
             │  record)    │  │ + limits │ └───────────┘ └────────────────┘
             └─────────────┘  └────┬─────┘
                                   │ jobs
                    ┌──────────────▼───────────────────────────────┐
                    │ Worker process (same image, different command)│
                    │ disease inference · embeddings · ingestion ·  │
                    │ notification fan-out · model evaluation       │
                    └──────────────────────────────────────────────┘
```

### Why these choices

* **Modular monolith.** One deployable API + one worker. Microservices would add
  operational cost with no benefit at this stage; module boundaries
  (`app/<domain>/`) are enforced by import rules + tests, so extraction later is
  mechanical.
* **Sync SQLAlchemy 2.0 + psycopg3.** FastAPI runs sync endpoints in a threadpool;
  this keeps the ORM code straightforward and avoids the async/sync split that
  produces subtle bugs with pgvector and MLflow clients. *(An async read-only
  path can be added per-endpoint later without changing the domain layer.)*
* **Jobs via Redis with an inline fallback.** `JOB_QUEUE_MODE=auto` uses Redis when
  reachable and otherwise executes the job in-process, recording the same
  `ai_jobs` / `background_jobs` rows so behaviour is observable either way and a
  single-node dev machine needs no Redis.
* **Providers everywhere an external service exists** (weather, market data, SMS,
  LLM, embeddings, storage, ranking). Each has a real implementation and a demo
  implementation, chosen by environment variable; the demo implementations
  return data tagged `is_demo: true` **and** an explicit `provider` field, so
  demo data can never be silently mistaken for live data.

## 3. Backend module map

```
backend/app/
  main.py            app factory, middleware, router mount, error handlers
  core/              config, logging, security, errors, middleware, cache,
                     rate_limit, pagination, observability, contracts, i18n
  database/          engine/session, Base, mixins, portable Vector type,
                     alembic glue
  api/v1/router.py   single place where every versioned router is mounted
  auth/              OTP + JWT + sessions + roles
  users/  farmers/  farms/  crops/
  community/         posts, comments, reactions, saves, follows, reports
  moderation/        queue, actions, audit
  weather/  markets/  schemes/  knowledge/  search/  notifications/
  ai/                vision (disease), crop recommendation, yield, price,
                     assistant, agent, feedback, model registry client
  admin/             admin & analytics API
  providers/         external-service interfaces + demo/real implementations
  workers/           job queue, handlers, worker entrypoint
```

Per-domain layout is consistent: `models.py` (SQLAlchemy), `schemas.py`
(Pydantic), `repository.py` (queries only), `service.py` (business rules,
transactions, events), `router.py` (HTTP only). The layering requested in the
specification (`models/`, `schemas/`, `services/`, `repositories/`) is realised
*inside* each domain package instead of as four global folders that would all
grow into 40-file dumps — an explicit architecture decision recorded here.

## 4. Request lifecycle

1. Nginx assigns/propagates `X-Request-ID`, applies edge rate limits.
2. `RequestContextMiddleware` binds request-id, user-id (if authenticated),
   route and start time into a structlog-style contextvar; the response carries
   `X-Request-ID` and `X-Process-Time`.
3. `RateLimitMiddleware`/dependency applies per-route limits from Redis
   (fixed-window with burst, keyed by user id when authenticated else IP).
4. Dependency chain: `get_db` (session per request, commit/rollback in the
   service layer) → `get_current_user` → `require_role(...)`.
5. Router validates input (Pydantic v2, strict where it matters) → service →
   repository → Postgres.
6. Errors: domain exceptions (`NotFoundError`, `PermissionDeniedError`,
   `ValidationError`, `RateLimitedError`, `ProviderUnavailableError`) are mapped
   by handlers into a single error envelope. Stack traces are logged with the
   request id and **never** returned to clients.

## 5. AI architecture

```
                 ┌──────────────────────────────────────────┐
 image/text ───▶ │ validation (type, size, dimensions,      │
                 │ quality gates, language detection)       │
                 └───────────────┬──────────────────────────┘
                                 ▼
        ┌────────────────────────────────────────────────────────┐
        │  ModelRuntime (ai/…): load once, version pinned,       │
        │  inference timed + counted, failure isolated           │
        └──────┬───────────────┬───────────────┬────────────────┘
               ▼               ▼               ▼
        sklearn/torch     retrieval        agent (tool calls)
        predictors        (pgvector RAG)   with allow-listed tools
               │               │               │
               └───────────────┴───────────────┘
                                 ▼
        evidence assembly (citations, model version, uncertainty)
                                 ▼
        response contract + prediction/feedback rows + metrics
```

* **No ML result is invented.** If an artifact is missing, the endpoint returns
  `503` with `model_unavailable` and the reason (`no artifact at
  ML_MODELS_DIR/...`, `disease model trained on 0 classes`) instead of a fake
  answer. The Flutter UI renders that state explicitly.
* **Crop recommendation** is a classifier over 7 chemical/climatic features with
  a documented synthetic-vs-public dataset situation (see `docs/ai.md`).
* **Disease detection** is a PyTorch transfer-learning image classifier whose
  real performance is whatever the included evaluation run measures — the number
  is always read from the model card produced at training time, never typed by
  hand.
* **RAG** answers only from indexed chunks; citations are constructed from
  retrieved rows, so an invented citation is structurally impossible, and an
  insufficient-evidence path returns "not enough indexed evidence".
* **Agent** tools are thin, permission-checked wrappers over services the user
  could call directly; the LLM never sees SQL and never gets a DB handle.

## 6. Trust & moderation model

* Every post/comment gets a **trust label** derived from author role and
  verification state, not from engagement counts.
* Reports create moderation cases; moderators act (dismiss/hide/remove/warn/
  restrict) and every action writes an `audit_logs` row plus a notification to
  the author with the reason. AI assists (spam heuristics, duplicate/near-
  duplicate detection, tone) but **cannot** label an agricultural claim false.
* Corrections are first-class objects attached to a post with a source URL, so
  "community supported" ≠ "scientifically verified" is visible in the UI.

## 7. Deployment topology (cloud-agnostic, AWS-mapped)

| Concern | Portable implementation | AWS mapping |
|---|---|---|
| API | container on Linux, `uvicorn` behind Nginx | ECS Fargate / EC2 + ALB |
| Database | PostgreSQL 16+ with `vector` extension | RDS/Aurora PostgreSQL + pgvector |
| Cache/queue | Redis 7 | ElastiCache |
| Object storage | `StorageBackend` interface (local or S3 API) | S3 |
| Model artifacts | `ML_MODELS_DIR` volume or `s3://` URI | S3 + ECS task volume / download on start |
| Experiments | MLflow server, Postgres backend + artifact root | ECS service + RDS |
| Secrets | environment variables from a secret manager | AWS Secrets Manager → task env |
| Metrics/logs | `/metrics` (Prometheus), JSON logs | CloudWatch + AMP/AMG |

No code path reads a cloud-specific API directly; S3 is behind the storage
abstraction, so GCP/Azure/on-prem need only new provider implementations.

## 8. Verified-in-this-sandbox vs. designed

| Component | State |
|---|---|
| PostgreSQL 17.11 + pgvector 0.8.0 (local, in sandbox) | **running, used by the test suite** |
| Redis 8 (local, in sandbox) | **running, used by cache/rate-limit tests** |
| Docker / docker-compose images | **built configs, not executed here** (no Docker daemon in the sandbox). CI builds them on every PR. |
| Flutter app | **code complete for implemented features, not compiled here** (Flutter SDK unavailable in the sandbox). CI runs `flutter analyze` + `flutter test`. |
| External providers (weather/market/LLM/embeddings) | demo providers exercised by tests; real providers require credentials in `.env` |

This table is the honest answer to "does it run?": the backend, database,
migrations, seed, tests and the live API do run in this environment — see
`docs/development.md` for the exact commands that were executed.
