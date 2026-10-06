"""Background job records (Redis queue, with an inline fallback)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import JobKind, JobStatus, enum_col
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class BackgroundJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "background_jobs"
    __table_args__ = (
        sa.Index("ix_background_jobs_status_scheduled", "status", "scheduled_at"),
        sa.CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    kind: Mapped[JobKind] = mapped_column(enum_col(JobKind, "job_kind"), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_col(JobStatus, "job_status"), default=JobStatus.QUEUED, nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(sa.JSON)
    progress: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(sa.Integer, default=3, nullable=False)
    # Defaulted application-side (not just in enqueue()) so any creation path — a
    # test, a fixture, an admin script — produces a claimable job instead of
    # tripping the NOT NULL constraint.
    scheduled_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(128), unique=True)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)

    def to_public(self) -> dict[str, Any]:
        kind = self.kind.value if hasattr(self.kind, "value") else str(self.kind)
        status = self.status.value if hasattr(self.status, "value") else str(self.status)
        return {
            "job_id": str(self.id),
            "kind": kind,
            "status": status,
            "progress": self.progress,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.last_error,
        }
