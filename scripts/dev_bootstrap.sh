#!/usr/bin/env bash
# Rebuild the Digital Village development environment on a fresh machine.
#
# This script exists because the sandbox/CI container is ephemeral: the Python
# virtualenv, the PostgreSQL cluster and Redis are *not* part of the repository
# snapshot, while the source tree and the migrations are. Running this script is
# therefore the first step of every fresh session, and it doubles as the
# documented way for a new developer to get from a clean checkout to a working
# API + database.
#
# Usage:
#   bash scripts/dev_bootstrap.sh              # everything
#   SKIP_SEED=1 bash scripts/dev_bootstrap.sh  # schema only, no demo rows
#   SKIP_APT=1 bash scripts/dev_bootstrap.sh   # don't touch system packages
#
# It is idempotent: re-running it is safe and changes nothing that is already
# in place. It never writes secrets — the credentials below are the documented
# DEVELOPMENT defaults from .env.example, and the script refuses to run against
# APP_ENV=production.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DB_NAME="${POSTGRES_DB:-digital_village}"
DB_USER="${POSTGRES_USER:-dv}"
DB_PASSWORD="${POSTGRES_PASSWORD:-dv_password}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$REPO_ROOT/.venv"

if [[ "${APP_ENV:-development}" == "production" ]]; then
  echo "Refusing to bootstrap a development database with APP_ENV=production." >&2
  exit 2
fi

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "1/6 System packages (postgresql-17 + pgvector, redis)"
if [[ "${SKIP_APT:-0}" != "1" ]]; then
  if ! command -v psql >/dev/null 2>&1 || ! command -v redis-server >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-17-pgvector redis-server
  else
    echo "already installed"
  fi
else
  echo "skipped (SKIP_APT=1)"
fi

step "2/6 Services"
if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
  sudo pg_ctlcluster 17 main start || sudo service postgresql start
  for _ in $(seq 1 20); do pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1 && break; sleep 1; done
fi
pg_isready -h "$DB_HOST" -p "$DB_PORT"
if ! redis-cli ping >/dev/null 2>&1; then
  redis-server --daemonize yes --bind 127.0.0.1 --port 6379
fi
redis-cli ping

step "3/6 Python virtualenv + dependencies"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q -r backend/requirements.txt -r backend/requirements-dev.txt
"$VENV_DIR/bin/python" -c "import fastapi, sqlalchemy, alembic, psycopg, redis, jwt, argon2; print('core dependencies import OK')"

step "4/6 Database role, extensions and database"
sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 \
  || sudo -u postgres psql -v ON_ERROR_STOP=1 -c \
     "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD' CREATEDB"
sudo -u postgres psql -v ON_ERROR_STOP=1 -tAc \
  "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
  || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
# Extensions must exist before the first migration: it creates vector columns.
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c \
  "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null
# The application role is not a superuser, so extension creation has to be
# granted once here (documented in docs/deployment.md).
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c \
  "GRANT ALL ON SCHEMA public TO $DB_USER;"

step "5/6 Migrations"
export DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
export PYTHONPATH="$REPO_ROOT/backend:$REPO_ROOT"
(cd backend && "$VENV_DIR/bin/alembic" upgrade head)
(cd backend && "$VENV_DIR/bin/alembic" current)

step "6/6 Demo data"
if [[ "${SKIP_SEED:-0}" == "1" ]]; then
  echo "skipped (SKIP_SEED=1)"
else
  "$VENV_DIR/bin/python" scripts/seed_demo.py
fi

cat <<EOF

Bootstrap complete.

  API docs      : http://localhost:8000/docs
  Health        : curl -s localhost:8000/health
  Start the API : cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
  Run tests     : cd backend && ../.venv/bin/pytest -q

All data created by the seed step is development/demo data (is_demo=True) and
must never be presented as verified agricultural, market or scheme information.
EOF
