"""Moderation cases, actions and the immutable audit log."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ModerationActionType,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    enum_col,
)
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModerationCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "moderation_cases"
    __table_args__ = (
        sa.Index("ix_moderation_cases_status_created", "status", "created_at"),
        sa.UniqueConstraint("report_id", name="uq_moderation_cases_report_id"),
    )

    report_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("reports.id", ondelete="SET NULL")
    )
    target_type: Mapped[ReportTargetType] = mapped_column(
        enum_col(ReportTargetType, "report_target_type"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[ReportReason] = mapped_column(
        enum_col(ReportReason, "report_reason"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        enum_col(ReportStatus, "report_status"),
        default=ReportStatus.OPEN,
        nullable=False,
        index=True,
    )
    priority: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    # Advisory AI signals. These can inform a human moderator; they can never
    # label an agricultural claim false (see docs/architecture.md §6).
    ai_signals: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(sa.Text)

    actions: Mapped[list[ModerationAction]] = relationship(
        back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )


class ModerationAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "moderation_actions"

    case_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("moderation_cases.id", ondelete="CASCADE"), index=True
    )
    moderator_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    action: Mapped[ModerationActionType] = mapped_column(
        enum_col(ModerationActionType, "moderation_action_type"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    # Duration in hours for temporary restrictions (null ⇒ permanent/not applicable)
    restriction_hours: Mapped[int | None] = mapped_column(sa.Integer)
    notified_author: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    case: Mapped[ModerationCase | None] = relationship(back_populates="actions")


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_target", "target_type", "target_id"),
        sa.Index("ix_audit_logs_actor", "actor_id", "created_at"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_role: Mapped[str | None] = mapped_column(sa.String(24))
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(sa.String(32))
    target_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True))
    before: Mapped[dict | None] = mapped_column(sa.JSON)
    after: Mapped[dict | None] = mapped_column(sa.JSON)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64))
    request_id: Mapped[str | None] = mapped_column(sa.String(64))


class UserRestriction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Temporary/permanent capability restriction applied by moderation."""

    __tablename__ = "user_restrictions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability: Mapped[str] = mapped_column(sa.String(32), default="post", nullable=False)
    reason: Mapped[str | None] = mapped_column(sa.Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False, index=True)

    def is_active(self, now: datetime | None = None) -> bool:
        if not self.active:
            return False
        if self.expires_at is None:
            return True
        from app.database.base import utcnow

        return self.expires_at > (now or utcnow())
