"""Dialect capability flags.

Used to skip or substitute PostgreSQL-only behaviour (HNSW index, `<=>`
operator, `tsvector`) when the suite runs against SQLite, so no test or code
path ever claims to have exercised a feature it did not.

Two things matter here, and both were got wrong at first:

1. **A capability answer must be real, never a swallowed failure.** The flag is
   read to decide whether to run the pgvector SQL or a slower Python cosine
   fallback. If the check itself errors, the old `except Exception: return False`
   turned "I could not tell" into "not supported" and the fallback ran silently —
   which is how a broken `jsonb_array_length` call inside the pgvector query
   survived a full test suite: the tests never reached that SQL.
2. **The argument may be an Engine *or* a Connection.** `db.get_bind()` returns a
   `Connection` inside a test session (the suite wraps every test in a
   transaction) and an `Engine` in the application. The old code assumed an
   `Engine`, so under test it raised `AttributeError` on `.connect()`, which the
   blanket `except` hid. Capability results therefore differed between tests and
   production — the opposite of what a capability flag is for.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, inspect
from sqlalchemy.engine import Engine

Connectable = Engine | Connection


@contextmanager
def _connection(target: Connectable) -> Iterator[Connection]:
    """Yield a connection without stealing one that the caller already owns.

    Closing a connection that belongs to an active session (or to an enclosing
    transaction) would end that transaction, so an existing `Connection` is used
    as-is and only connections we opened ourselves are closed.
    """
    if isinstance(target, Connection):
        yield target
        return
    with target.connect() as conn:
        yield conn


def dialect_name(target: Connectable) -> str:
    return target.dialect.name


def _has_extension(target: Connectable, extension: str) -> bool:
    """Whether `extension` is installed in the database behind `target`.

    A non-PostgreSQL backend is a *supported* answer (``False``). Anything else
    that goes wrong is re-raised: a capability probe that fails must not be
    mistaken for a capability that is absent.
    """
    if dialect_name(target) != "postgresql":
        return False
    with _connection(target) as conn:
        row = conn.exec_driver_sql(
            "select 1 from pg_extension where extname = %s",
            # exec_driver_sql does not expand parameters; the extension name is a
            # hard-coded constant from this module, never user input.
            (extension,),
        ).scalar()
    return bool(row)


def supports_pgvector(target: Connectable) -> bool:
    return _has_extension(target, "vector")


def supports_full_text_search(target: Connectable) -> bool:
    return dialect_name(target) == "postgresql"


def supports_trigram(target: Connectable) -> bool:
    return _has_extension(target, "pg_trgm")


def table_names(target: Connectable) -> list[str]:
    with _connection(target) as conn:
        return sorted(inspect(conn).get_table_names())
