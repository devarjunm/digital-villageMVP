# Digital Village — Local development

This is the "how do I get it running and how do I know it works" document. It lists the commands
that are actually run in this workspace, together with their recorded results, so a claim in a status
table can always be traced back to a command.

## 1. Prerequisites

Nothing beyond a Debian/Ubuntu-like host with `python3`, `sudo` and network access for the bootstrap
step: PostgreSQL and Redis are installed by the script. Flutter is only needed for the mobile app.

## 2. One command from clean checkout to working stack

```bash
bash scripts/dev_bootstrap.sh
```

Steps it performs, in order (and why that order):

1. installs PostgreSQL (+pgvector) and Redis;
2. starts both and waits for `pg_isready` / `redis-cli ping`;
3. creates `.venv` if missing and installs `backend/requirements.txt` + `requirements-dev.txt`;
4. creates the `dv` role and the `digital_village` database, then creates the **vector** and
   **pg_trgm** extensions (extensions first — the initial migration creates vector columns);
5. runs `alembic upgrade head` and prints the current revision;
6. runs `scripts/seed_demo.py` (development data, all `is_demo=True`).

It is idempotent, refuses to run against `APP_ENV=production`, and every credential in it is the
documented development default from `.env.example`.

Variants:

```bash
SKIP_SEED=1 bash scripts/dev_bootstrap.sh     # schema only
SKIP_APT=1 bash scripts/dev_bootstrap.sh      # packages already present
```

## 3. Everyday commands

```bash
# API (reload on change)
cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

`--host 0.0.0.0` matters: with the default loopback binding, the Android app cannot reach the API
from an emulator or a phone. To test the mobile app against this server, see
**`docs/mobile_release.md` §4** (or run `bash scripts/lan_address.sh`, which prints the LAN address
the phone should use and the matching commands).

# Background worker (embeddings, notifications, evaluation jobs)
cd backend && ../.venv/bin/python -m app.workers.runner

# Backend tests (the suite creates and migrates digital_village_test itself)
cd backend && TEST_DATABASE_URL='postgresql+psycopg://dv:dv_password@localhost:5432/digital_village_test' \
  ../.venv/bin/pytest tests -q

# A single suite / a single test
cd backend && ../.venv/bin/pytest tests/test_community_trust.py -q
cd backend && ../.venv/bin/pytest tests/test_ai_safety.py -q -k crop

# Cross-package tests (artefact integrity, config/docs consistency)
.venv/bin/pytest tests -q

# Lint, format, import check
.venv/bin/ruff check backend ai genai scripts mlops tests
.venv/bin/ruff format backend ai genai scripts mlops tests
PYTHONPATH=backend:. .venv/bin/python scripts/check_imports.py

# Re-seed / reference data
DATABASE_URL='postgresql+psycopg://dv:dv_password@localhost:5432/digital_village' PYTHONPATH=. \
  .venv/bin/python scripts/seed_demo.py --quiet
DATABASE_URL='postgresql+psycopg://dv:dv_password@localhost:5432/digital_village' PYTHONPATH=backend:. \
  .venv/bin/python scripts/load_reference_data.py
```

## 4. Test layout

| Suite | Covers |
|---|---|
| `backend/tests/test_auth_flows.py`, `test_users_*` | registration, OTP, login, refresh/rotation, logout-everywhere, recovery, role management |
| `backend/tests/test_farms_crops.py` | farm/crop CRUD, ownership rules, unit conversion, soil tests |
| `backend/tests/test_community_trust.py` | trust labels, reactions never upgrading labels, expert-only information, report → case → note, moderator vs admin removal, restrictions enforced on the write path |
| `backend/tests/test_ai_safety.py` | uncertainty wording, refusal when evidence is thin, feedback enum, per-user history, model-unavailable messaging, unknown crop rejection |
| `backend/tests/test_privacy_consent.py` | consent gating of analytics, data export contents (and what is excluded), deletion erasing identifiers and revoking sessions |
| `backend/tests/test_external_sources.py` | provider provenance and demo labelling for weather/markets/schemes, search result contracts, notification scoping, scheme rule evaluation |
| `backend/tests/test_search_rag.py`, `test_agent_tools.py`, `test_model_registry.py` | retrieval and citation rules, tool permission boundaries, artefact/registry behaviour |
| `tests/` (repo root) | cross-package checks: every model artefact is internally consistent, every documented config key exists, no secrets committed |

Test-database conventions: the suite creates `digital_village_test` if absent, enables `vector` and
`pg_trgm`, migrates it with Alembic (so the schema under test is exactly the schema production gets)
and runs each test in a transaction that is rolled back afterwards. Redis database 15 is flushed
around the run so cache entries cannot leak between tests.

## 5. Recorded results in this environment

| Command | Result |
|---|---|
| `bash scripts/dev_bootstrap.sh` | complete: packages installed, role/database created, extensions enabled, `alembic upgrade head` at the single head, seed printed its per-table counts |
| `pytest tests -q` (backend) | **73 passed, 1 skipped** — the skip is "disease model artefact is not installed in this environment", which is the intended default state |
| `check_imports.py` | `tested 157 modules, 0 failures` |
| `ruff check` + `ruff format --check` | clean for `backend/ ai/ genai/ scripts/` |
| `python -c "app.main.app.openapi()"` | 128 paths, 177 schemas |
| `seed_demo.py --quiet` (second run) | idempotent; counts unchanged |
| crop recommendation, live call | `200`, `model_version=v202610051518`, `score_type=relative_model_score` |

## 6. Repository conventions

* **Layering per domain package**: `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `repository.py`
  (queries only), `service.py` (business rules, transactions, events), `router.py` (HTTP only).
  Routers never contain queries; services never build HTTP responses.
* **Migrations**: one head, additive style, every revision has a working `downgrade()`. A JSON column
  that the database has to *query into* is `jsonb` (`app/database/base.py::json_document`); write-only
  blobs stay plain `json`.
* **Errors**: raise `AppError` subclasses from `app/core/errors.py`; the handler renders the single
  error envelope with a `request_id`. Ownership failures are `404` (never `403`, which would confirm
  the row exists); role failures are `403`.
* **Docs discipline**: status claims in any document use the `[built] / [partial] / [planned]` legend
  and must be traceable to a command result like the ones in §5.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pg_isready: command not found` | the container was reset; run `bash scripts/dev_bootstrap.sh` |
| Tests report "PostgreSQL is not reachable" and skip | same as above — the suite skips rather than failing, so check for skips, not only failures |
| `ModuleNotFoundError: genai` | run with `PYTHONPATH=backend:.` (the packages `ai/` and `genai/` live at the repo root) |
| `relation "crops_catalog" does not exist` | migrations not applied: `alembic upgrade head` |
| `unknown crop code` when creating a crop | reference data not loaded: `python scripts/load_reference_data.py` |
| Weather/market endpoints return demo-shaped values | `WEATHER_PROVIDER`/`MARKET_PROVIDER` are still `mock`; this is labelled in every response on purpose |
| Disease screening returns 503 | no artefact installed; see `docs/deployment.md` §5 |
| `alembic` reports multiple heads | a branch was merged without a merge revision: `alembic merge heads` |
