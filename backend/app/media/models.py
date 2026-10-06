"""Object storage records.

Binary content is never stored in PostgreSQL. A `MediaAsset` row holds the
storage key, provenance and the validation results computed on upload, so the
database can be audited for "what did we accept" without holding payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MediaAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media_assets"
    __table_args__ = (
        sa.UniqueConstraint("storage_key", name="uq_media_assets_storage_key"),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
    )

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    purpose: Mapped[str] = mapped_column(sa.String(32), default="post_image", nullable=False)
    storage_backend: Mapped[str] = mapped_column(sa.String(16), default="local", nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    public_url: Mapped[str | None] = mapped_column(sa.String(1024))
    original_filename: Mapped[str | None] = mapped_column(sa.String(255))
    mime_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    width: Mapped[int | None] = mapped_column(sa.Integer)
    height: Mapped[int | None] = mapped_column(sa.Integer)
    validated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    validation_notes: Mapped[list[str]] = mapped_column(sa.JSON, default=list, nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
