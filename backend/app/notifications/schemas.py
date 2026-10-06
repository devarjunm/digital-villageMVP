"""Notification API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import NotificationType


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    language: str
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    deep_link: str | None = None
    payload: dict[str, Any] = {}
    read: bool = False
    read_at: datetime | None = None
    push_sent_at: datetime | None = None
    push_error: str | None = None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    unread_count: int


class UnreadCount(BaseModel):
    unread_count: int
    max_per_day: int
    created_last_24h: int


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    in_app_enabled: bool
    push_enabled: bool
    weather_alerts: bool
    market_updates: bool
    crop_reminders: bool
    community_activity: bool
    scheme_updates: bool
    ai_job_updates: bool
    digest_only: bool
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    max_per_day: int


class PreferenceUpdate(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    in_app_enabled: bool | None = None
    push_enabled: bool | None = None
    weather_alerts: bool | None = None
    market_updates: bool | None = None
    crop_reminders: bool | None = None
    community_activity: bool | None = None
    scheme_updates: bool | None = None
    ai_job_updates: bool | None = None
    digest_only: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    max_per_day: int | None = Field(default=None, ge=1, le=200)


class DeviceRegister(BaseModel):
    token: str = Field(min_length=10, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios|web)$")


class DeviceOut(BaseModel):
    id: uuid.UUID
    platform: str
    token_suffix: str
    is_active: bool
    last_seen_at: datetime
    note: str = "Full tokens are never returned by the API."


class PushHealth(BaseModel):
    provider: str
    is_demo: bool
    configured: bool
    note: str | None = None
    project_id: str | None = None


class BroadcastRequest(BaseModel):
    """Admin broadcast. Requires a reason; always creates an audit entry."""

    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=600)
    audience: str = Field(pattern="^(all|role|state|demo_users|real_users)$")
    role: str | None = Field(default=None, max_length=32)
    state: str | None = Field(default=None, max_length=120)
    reason: str = Field(
        min_length=10, max_length=500, description="Why this broadcast is necessary (audited)."
    )
    dry_run: bool = Field(default=False, description="Count recipients without sending.")


class BroadcastResult(BaseModel):
    audience: str
    recipients: int
    created: int
    skipped: dict[str, int] = {}
    dry_run: bool
    push: dict[str, Any] = {}
