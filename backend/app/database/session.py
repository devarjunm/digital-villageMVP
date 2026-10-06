"""Engine/session management and the FastAPI dependency."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _engine_kwargs(url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        "future": True,
        "pool_pre_ping": settings.db_pool_pre_ping,
    }
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs.pop("pool_pre_ping")
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_recycle"] = 1800
    return kwargs


def get_engine(url: str | None = None) -> Engine:
    global _engine
    if _engine is None or url is not None:
        target = url or settings.database_url
        _engine = sa.create_engine(target, **_engine_kwargs(target))
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        # Any process that opens a session needs the complete mapper registry:
        # background workers and scripts never import the API, and a partially
        # mapped registry fails at flush time with a confusing
        # "could not find table ..." error instead of at import time.
        import app.models  # noqa: F401

        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def configure_database(url: str) -> None:
    """Rebind the engine (used at startup and by the test fixture)."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
    get_engine(url)
    get_session_factory()


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request. Services own transaction
    boundaries (commit where a unit of work completes)."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Session for workers/scripts and services that need an explicit boundary."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_health() -> dict[str, Any]:
    try:
        with get_engine().connect() as conn:
            version = conn.execute(sa.text("select version()")).scalar_one()
            vector = conn.execute(
                sa.text("select extversion from pg_extension where extname = 'vector'")
            ).scalar_one_or_none()
        return {
            "available": True,
            "flavor": "postgresql" if "PostgreSQL" in str(version) else "other",
            "version": str(version).split(" on ")[0],
            "pgvector": vector,
        }
    except Exception as exc:
        logger.warning("database_health_check_failed", extra={"extra_fields": {"error": str(exc)}})
        return {"available": False, "detail": str(exc)}
