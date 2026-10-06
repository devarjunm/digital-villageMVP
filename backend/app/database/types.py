"""Portable column types.

`Vector` maps to pgvector's `vector(n)` on PostgreSQL and to TEXT (JSON array)
elsewhere, so the same models can be used by the test suite on SQLite. Exact
vector behaviour (HNSW index, `<=>` operator) is only available on PostgreSQL —
see app/database/vector_search.py for the capability-aware query layer.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.types import TypeDecorator, UserDefinedType


class PGVector(UserDefinedType):
    """Minimal pgvector adapter — no pgvector python package required."""

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: object) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(f"{float(x):.7g}" for x in value) + "]"

        return process if dialect.name == "postgresql" else None

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, list):
                return [float(x) for x in value]
            return [float(x) for x in str(value).strip("[]").split(",") if x != ""]

        return process


class Vector(TypeDecorator):
    """Embedding column. `dim` must match EMBEDDING_DIM for the active provider."""

    impl = sa.Text
    cache_ok = True

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(sa.Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        values = [float(x) for x in value]
        if len(values) != self.dim:
            raise ValueError(f"embedding has {len(values)} dims, expected {self.dim}")
        if dialect.name == "postgresql":
            return "[" + ",".join(f"{v:.7g}" for v in values) + "]"
        return json.dumps(values)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return [float(x) for x in value]
        raw = str(value).strip()
        if raw.startswith("["):
            try:
                return [float(x) for x in json.loads(raw)]
            except json.JSONDecodeError:
                pass
        return [float(x) for x in raw.strip("[]{}").split(",") if x.strip() != ""]
