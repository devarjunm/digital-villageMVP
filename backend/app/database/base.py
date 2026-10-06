"""Declarative base and the shared column mixins (ids, timestamps, soft delete,
audit fields).

Every table inherits from Base; no table defines created_at/updated_at by hand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def json_document() -> sa.types.TypeEngine:
    """A JSON column that is *jsonb* on PostgreSQL.

    jsonb is required wherever the database itself has to look inside the value
    (``@>`` containment, ``?|`` key existence). Plain ``json`` has no such
    operators, so querying it either errors or silently degrades to a LIKE on the
    text representation — which is how a state filter once matched nothing.
    Write-only blobs (audit snapshots, metrics) stay as plain JSON, because they
    are never queried and jsonb rewrites the whole value on write.
    """
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def array_contains(column: sa.ColumnElement, values: list[str]) -> sa.ColumnElement[bool]:
    """``column @> values`` — "does this JSON list contain any of these tags?".

    Written as an explicit cast because the generic ``JSON`` type only knows how
    to express containment as a ``LIKE`` on the text form, which PostgreSQL
    rejects on a json/jsonb column (``operator does not exist: json ~~ text``).
    """
    return sa.cast(column, postgresql.JSONB).contains(sa.cast(values, postgresql.JSONB))


def new_uuid() -> uuid.UUID:
    """UUIDv4 — generated application-side so SQLite tests behave identically."""
    return uuid.uuid4()


class Base(DeclarativeBase):
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    # Queryable list-of-string fields default to jsonb (see json_document); the
    # annotation map keeps hand-written Mapped[list[str]] columns consistent.
    type_annotation_map: ClassVar[dict] = {
        dict[str, object]: sa.JSON,
        list[str]: json_document(),
        list[dict[str, object]]: sa.JSON,
    }

    @declared_attr.directive
    def __tablename__(cls) -> str:
        name = cls.__name__
        out: list[str] = []
        for i, ch in enumerate(name):
            if ch.isupper() and i > 0:
                out.append("_")
            out.append(ch.lower())
        table = "".join(out)
        if not table.endswith("s"):
            table += "s"
        return table

    def to_dict(self) -> dict[str, object]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=new_uuid, index=False
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=sa.func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class AuditMixin:
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


class DemoFlagMixin:
    """Marks seeded/demo rows so production analytics and clients can exclude them.
    Nothing in the API mixes demo rows with live rows silently."""

    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False, index=True)
