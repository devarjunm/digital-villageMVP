"""Alembic environment.

The database URL is read from the environment (DATABASE_URL) — never from a
tracked file — and the target metadata is the aggregate model map
(app.models), so autogenerate sees every table.

Safety rules:
  * `APP_ENV=production` requires an explicit `ALEMBIC_ALLOW_PROD=1` for
    destructive operations (compare_metadata drops are never auto-applied);
  * `alembic upgrade head` is the only supported way to create schema; the
    application never calls create_all.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (registers all mapped classes on Base.metadata)
from alembic import context
from app.core.config import settings
from app.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


# Objects created with raw SQL in revision e1d0628ce86d (pgvector HNSW indexes,
# extension-owned tables). Autogenerate cannot express these, so they are excluded
# from comparison instead of being reported as "removed" on every run.
RAW_SQL_INDEXES = {"ix_knowledge_chunks_embedding", "ix_post_embeddings_hnsw"}
EXTERNAL_TABLES = {"spatial_ref_sys"}


def include_object(object_, name, type_, reflected, compare_to):
    """Skip objects this project does not manage through autogenerate."""
    if type_ == "table":
        return name not in EXTERNAL_TABLES
    if type_ == "index":
        # Vector indexes are created with raw SQL in the migration that needs them;
        # autogenerate cannot express them, so it must not report them as missing.
        return name not in RAW_SQL_INDEXES
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


# Guard: refuse to run in production without an explicit acknowledgement, because
# migrations there are a planned release step, not an incidental command.
if settings.is_production and os.environ.get("ALEMBIC_ALLOW_PROD") != "1":
    raise SystemExit(
        "Refusing to run migrations with APP_ENV=production. Set ALEMBIC_ALLOW_PROD=1 to confirm "
        "you have a backup and a maintenance window."
    )

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
