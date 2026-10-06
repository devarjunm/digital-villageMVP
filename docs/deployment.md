# Digital Village — Deployment

> This document is the operator's runbook. It describes how a deployment *is* done; it does not
> claim that one has been done from this workspace. Nothing here has been executed against a real
> server from this repository, and no production credentials exist in it.

## 1. Environments

| Environment | Compose file | Data | Purpose |
|---|---|---|---|
| Local development | `docker-compose.dev.yml` | seeded demo rows, `is_demo=True` | day-to-day work, the integration test suite |
| Staging | `docker-compose.yml` (or the platform's equivalent) | production-shaped, no demo rows | release verification, migration rehearsal |
| Production | `docker-compose.yml` behind a managed load balancer, or the platform's own orchestration | real data only | farmers |

Rule that applies to every environment: **demo data never reaches production.** `scripts/seed_demo.py`
refuses to run unless `APP_ENV=development` (or `ALLOW_PROD_SEED=1` is set explicitly for a
throwaway review environment), and every demo row is written with `is_demo=True`.

## 2. Configuration

All configuration comes from environment variables; there are no secrets in the repository.
`.env.example` is the authoritative list with comments. The essentials:

| Variable | Notes |
|---|---|
| `APP_ENV` | `development` / `staging` / `production` — controls debug surfaces and seeding guards |
| `JWT_SECRET` | **required**, 32+ random bytes; rotating it invalidates all sessions by design |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db`; the role needs `CREATE` on `public` for migrations |
| `REDIS_URL` | cache, rate limiting and the job queue; a shared Redis is required for multi-worker deployments |
| `STORAGE_BACKEND` | `local` for single-node, `s3` for object storage; large images must **not** live in PostgreSQL |
| `MEDIA_PUBLIC_BASE_URL` | public prefix used when rendering media URLs |
| `WEATHER_PROVIDER` / `MARKET_PROVIDER` / `LLM_PROVIDER` / `EMBEDDING_PROVIDER` | `mock` for development; the real providers require the matching API keys |
| `SMS_PROVIDER` / `PUSH_PROVIDER` | `console` in development; `msg91`/`twilio` and `fcm` in production |
| `ML_MODELS_DIR` | directory holding versioned model artefacts (see §5) |
| `MLFLOW_TRACKING_URI` | MLflow tracking server for training metadata (optional at runtime) |
| `ANALYTICS_REQUIRES_CONSENT` | must stay `true` in production: analytics is gated on recorded consent |

Generate a secret and store it in the platform's secret manager, never in the image:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 3. Database preparation and migrations

PostgreSQL 17 with **vector** (pgvector) and **pg_trgm** is required. Extensions must exist *before*
the first migration, because the initial revision creates vector columns; a non-superuser
application role cannot create them itself, so run this once per database as a privileged user:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
GRANT ALL ON SCHEMA public TO dv;
```

The documented run order for any environment — the same order `scripts/dev_bootstrap.sh` uses
locally and the same order the release workflow rehearses:

```bash
cd backend
DATABASE_URL='postgresql+psycopg://dv:***@host:5432/digital_village' \
  alembic upgrade head                                  # 1. schema to the single head
DATABASE_URL='postgresql+psycopg://dv:***@host:5432/digital_village' \
  PYTHONPATH=.:.. python ../scripts/load_reference_data.py   # 2. reference data (crop catalog, etc.)
```

Reference data is **not** demo data: the application cannot create a crop for a code that is not in
`crops_catalog`, so step 2 is mandatory even in production. It is idempotent (it reports
`created / completed / defined` counts) and safe to re-run on every deploy.

Migrations are forward-only. `alembic downgrade` exists for every revision, but treat it as an
emergency tool: check that the previous application release tolerates the older schema before running
it.

## 4. Deploying the API and worker

```bash
docker compose -f docker-compose.yml build          # or pull the published image tag
docker compose -f docker-compose.yml up -d postgres redis
docker compose -f docker-compose.yml run --rm api alembic upgrade head
docker compose -f docker-compose.yml run --rm api python scripts/load_reference_data.py
docker compose -f docker-compose.yml up -d api worker nginx
```

The API and the worker run the same image with different commands, so there is exactly one build to
verify. The API must run with a process manager (`gunicorn -k uvicorn.workers.UvicornWorker`), and
the worker must be deployed at least once for background jobs (embeddings, notification fan-out,
model evaluation) to drain.

Health checks used by both the compose files and any external load balancer:

| Endpoint | Meaning | Expected |
|---|---|---|
| `GET /health` | liveness — process is up, no dependency calls | `200` |
| `GET /ready` | readiness — database, cache, and configured providers answers; reports model availability | `200` ready / `503` with the failing component named |

`/ready` deliberately does **not** report "ready" when a required dependency is down, and it names
which one, so an operator is never told "everything is fine" by a degraded service.

## 5. Installing models

Models are artefacts on disk, versioned by directory, with a model card:

```
artifacts/models/<name>/<version>/
  model.joblib | model.pt     the artefact itself
  model_card.json             task, framework, dataset provenance, metrics, calibration status
  metrics.json                the evaluation numbers the card refers to
  feature_names.json          input order + per-crop reference ranges (tabular models)
```

1. Produce the artefact with the training entrypoint (`python -m ai.crop_recommendation.train …` or
   `python mlops/train_all.py`), which writes the directory **and** logs the run to MLflow.
2. Validate it: `python mlops/validate_artifacts.py` — refuses an artefact whose card, metrics and
   feature order are missing or inconsistent.
3. Publish it to the `ML_MODELS_DIR` of the environment (bind mount, volume or object-storage sync).
4. Point the environment at it: `ML_CROP_REC_MODEL_VERSION=v202610051518` (or leave the variable
   empty to use the newest installed version).
5. Restart the API/worker so the registry re-reads the directory, then check `GET /api/v1/ai/models`
   and `GET /ready`.

A model that is not installed is reported as unavailable with an explanation
(`"No trained model artefact is installed for 'disease-detection'…"`); the API never serves a
placeholder, and the mobile app surfaces that message verbatim instead of hiding the feature.
Rolling back a model is therefore a configuration change: set the previous version and restart.

## 5b. Operator tools

| Task | Command |
|---|---|
| Validate a model artefact before deploying it | `python mlops/validate_artifacts.py --strict` |
| See what training would do | `python mlops/train_all.py --dry-run` |
| Re-embed the corpus after a provider change | `python mlops/reindex_embeddings.py --yes` |
| Model health: installed vs pinned versions, inference volume, latency, drift | `python mlops/monitor_models.py --days 7` |
| Queue status and worker health | `python -m app.workers.main --status` |

## 6. Enabling the real external providers

| Capability | Provider | Configuration | Verification |
|---|---|---|---|
| Weather | OpenWeatherMap | `WEATHER_PROVIDER=openweathermap`, `WEATHER_API_KEY=…` | `GET /api/v1/weather/provider` must show `provider: openweathermap`, `available: true`, `is_demo: false` |
| Mandi prices | data.gov.in Agmarknet | `MARKET_PROVIDER=govdata`, `MARKET_API_KEY=…`, `MARKET_RESOURCE_ID=…` | `GET /api/v1/markets/provider` |
| LLM (assistant, agent) | any OpenAI-compatible endpoint | `LLM_PROVIDER=openai`, `LLM_API_KEY=…`, `LLM_BASE_URL=…`, `LLM_MODEL=…` | `GET /api/v1/ai/health` |
| Embeddings (semantic search, RAG) | OpenAI or a local sentence-transformer | `EMBEDDING_PROVIDER=openai` (key) or `EMBEDDING_PROVIDER=sentence-transformers` (no key, CPU) | `GET /api/v1/search/health` |
| OTP SMS | MSG91 / Twilio | `SMS_PROVIDER=msg91`, credentials | Send one OTP to a test number |
| Push | Firebase Cloud Messaging | `PUSH_PROVIDER=fcm`, `PUSH_CREDENTIALS_FILE=/secrets/fcm.json` | Device-token registration then a test push |

Until a provider is configured, the matching demo provider runs and every response it produces is
labelled `is_demo: true` with a human-readable notice. There is no code path that returns demo data
claiming to be live data.

**Important**: changing the embedding provider changes the vector space, so every stored vector
becomes meaningless for the new model. After switching, run:

```bash
python mlops/reindex_embeddings.py --dry-run          # shows provider, dimension and corpus size
python mlops/reindex_embeddings.py --yes              # queues the embedding_reindex worker job
# and bump EMBEDDING_VERSION (and EMBEDDING_DIM if the model changed) in the environment
```

Until the re-embed finishes, semantic search returns no results rather than confidently wrong ones,
and every search response states the embedding provider and model used for the query so a mismatch is
visible instead of silent.

## 7. Backups, retention and privacy operations

* **Backups**: `pg_dump` on a schedule (plus WAL archiving for point-in-time recovery), and a copy of
  `artifacts/models` — losing an artefact makes a feature unavailable even though the database is
  intact. Media lives in object storage and follows that provider's own backup policy.
* **Retention**: AI request/response history is retained for `AI_HISTORY_RETENTION_DAYS`; deletion
  requests erase identifiers immediately and revoke sessions, and the response states what is kept
  (aggregated metrics and audit records) and why.
* **Consent**: analytics requires a recorded consent decision per purpose. Do not enable
  `ANALYTICS_REQUIRES_CONSENT=false` outside a development environment.
* **Verification**: after a restore, check `SELECT count(*) FROM crops_catalog` is non-zero and call
  `/ready`; an empty catalog means the reference-data step was skipped.

## 8. Monitoring and alerts

Prometheus scrapes the API's `/metrics`; `infrastructure/monitoring/` holds the scrape configuration
and alert rules for: error rate, p95 latency, readiness failures, provider failures (weather/market),
model-inference errors, job-queue depth and rate-limit rejections. Grafana dashboards are provisioned
from the same directory. Every log line is structured JSON carrying `request_id`, `route`, `user_id`
(an opaque identifier) and latency; tokens, OTPs, passwords and request bodies are never logged.

## 9. Rollback

1. Re-point the service to the previously published image tag and restart; no schema change is
   involved, so this is the fastest safe action.
2. If the release included a migration, verify the older release tolerates the schema before using
   `alembic downgrade <previous_revision>`; the API is written to tolerate additive columns, which is
   the migration style used throughout this repository.
3. Roll back models independently by setting `ML_*_MODEL_VERSION` to the previous version.
4. Provider outages are handled by explicit degradation: responses carry `stale_fallback=true` with
   the age of the data, or fail with a clear error envelope — never with invented values.
