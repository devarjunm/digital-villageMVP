"""Admin console API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminOverview(BaseModel):
    users: dict[str, int]
    farms: dict[str, int]
    crops: dict[str, int]
    community: dict[str, int]
    moderation: dict[str, Any]
    ai: dict[str, int]
    knowledge: dict[str, int]
    jobs: dict[str, Any]
    generated_at: datetime
    data_quality: dict[str, Any]


class AdminUserRow(BaseModel):
    id: uuid.UUID
    full_name: str
    display_name: str | None = None
    phone_masked: str | None = None
    email: str | None = None
    primary_role: str
    roles: list[str] = []
    is_active: bool
    is_verified: bool
    is_demo: bool
    created_at: datetime
    last_login_at: datetime | None = None
    locked_until: datetime | None = None
    restrictions: list[dict[str, Any]] = []


class AdminUserList(BaseModel):
    items: list[AdminUserRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    filters: dict[str, Any]


class AdminUserUpdate(BaseModel):
    """Administrative user changes always require a written reason (audited)."""

    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    primary_role: str | None = Field(default=None, max_length=24)
    add_roles: list[str] = Field(default_factory=list, max_length=6)
    remove_roles: list[str] = Field(default_factory=list, max_length=6)
    verified: bool | None = None
    unlock: bool = False
    reason: str = Field(
        min_length=10,
        max_length=500,
        description="Why this change is being made. Stored in the audit log with the before/after values.",
    )

    @model_validator(mode="after")
    def _something_changes(self) -> AdminUserUpdate:
        if not any(
            [
                self.is_active is not None,
                self.primary_role,
                self.add_roles,
                self.remove_roles,
                self.verified is not None,
                self.unlock,
            ]
        ):
            raise ValueError("Nothing to change.")
        return self


class AdminUserUpdateResult(BaseModel):
    user_id: uuid.UUID
    before: dict[str, Any]
    after: dict[str, Any]
    audit_id: uuid.UUID
    message: str


class JobRow(BaseModel):
    job_id: uuid.UUID
    kind: str
    status: str
    progress: int
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class JobList(BaseModel):
    items: list[JobRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    stats: dict[str, Any]


class JobEnqueueRequest(BaseModel):
    kind: str = Field(max_length=48)
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=10, max_length=500, description="Operational reason (audited).")
    delay_seconds: int = Field(default=0, ge=0, le=86_400)
    dedupe_key: str | None = Field(default=None, max_length=128)


class JobEnqueueResult(BaseModel):
    job_id: uuid.UUID
    status: str
    mode: str
    reason: str
    note: str


class ModelRegisterRequest(BaseModel):
    name: str = Field(max_length=96)
    version: str = Field(max_length=64)
    stage: str = Field(default="staging", pattern="^(staging|production|archived)$")
    notes: str | None = Field(default=None, max_length=1000)
    reason: str = Field(min_length=10, max_length=500)


class ModelActivateRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class ModelActionResult(BaseModel):
    name: str
    version: str
    stage: str
    is_active: bool
    metrics: dict[str, Any] = {}
    message: str
    audit_id: uuid.UUID | None = None


class SystemHealth(BaseModel):
    app_env: str
    version: str
    database: dict[str, Any]
    cache: dict[str, Any]
    storage: dict[str, Any]
    providers: dict[str, Any]
    models: dict[str, Any]
    migrations: dict[str, Any]
    disk: dict[str, Any]


class DataQualityReport(BaseModel):
    generated_at: datetime
    checks: list[dict[str, Any]]
    notes: list[str]
