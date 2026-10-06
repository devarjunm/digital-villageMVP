"""Notifications and delivery preferences (anti-spam by construction:
each type has its own switch, quiet hours are honoured, and fan-out is
deduplicated per recipient+subject)."""

from __future__ import annotations

import uuid
from datetime import datetime, time

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import NotificationType, enum_col
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "type", "subject_type", "subject_id", name="uq_notifications_dedupe"
        ),
        sa.Index("ix_notifications_user_created", "user_id", "created_at"),
        sa.Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        enum_col(NotificationType, "notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    body: Mapped[str] = mapped_column(sa.String(600), nullable=False)
    language: Mapped[str] = mapped_column(sa.String(8), default="en", nullable=False)
    subject_type: Mapped[str | None] = mapped_column(sa.String(32))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True))
    deep_link: Mapped[str | None] = mapped_column(sa.String(512))
    payload: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    push_sent_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    push_error: Mapped[str | None] = mapped_column(sa.String(255))

    def mark_read(self) -> None:
        self.read_at = utcnow()


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_preferences"
    __table_args__ = (sa.UniqueConstraint("user_id", name="uq_notification_preferences_user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    in_app_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    weather_alerts: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    market_updates: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    crop_reminders: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    community_activity: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    scheme_updates: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    ai_job_updates: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    digest_only: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    quiet_hours_start: Mapped[time | None] = mapped_column(sa.Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(sa.Time)
    max_per_day: Mapped[int] = mapped_column(sa.Integer, default=20, nullable=False)
