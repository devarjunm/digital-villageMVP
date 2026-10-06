"""Moderation API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.enums import (
    ModerationActionType,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)


class CaseOut(BaseModel):
    id: uuid.UUID
    target_type: ReportTargetType
    target_id: uuid.UUID
    author_id: uuid.UUID | None
    reason: ReportReason
    status: ReportStatus
    priority: int
    signals: dict[str, Any] = {}
    assigned_to_id: uuid.UUID | None = None
    resolved_by_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    reports: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    target_snapshot: dict[str, Any] | None = None


class QueueResponse(BaseModel):
    items: list[CaseOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    stats: dict[str, Any]


class ActionRequest(BaseModel):
    action: ModerationActionType
    reason: str = Field(min_length=10, max_length=1000)
    restriction_hours: int | None = Field(
        default=None,
        ge=1,
        le=24 * 365,
        description="Required in practice for restrict_author; omit or set for a permanent restriction.",
    )
    target_type: str | None = Field(
        default=None, description="Override target (defaults to the case target)."
    )
    target_id: uuid.UUID | None = None
    resolution_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _restrict_needs_hours_or_permanent(self) -> ActionRequest:
        # A restriction with no end date is allowed (it is permanent), but then the
        # reason must say so explicitly — otherwise an accidental omission would
        # silently create a permanent ban.
        if (
            self.action == ModerationActionType.RESTRICT_AUTHOR
            and self.restriction_hours is None
            and "permanent" not in self.reason.lower()
        ):
            raise ValueError(
                "A permanent restriction must be stated as such in the reason (include the word 'permanent')."
            )
        return self


class CorrectionRequest(BaseModel):
    corrected_target_type: ReportTargetType
    corrected_target_id: uuid.UUID
    note: str = Field(
        min_length=10,
        max_length=1000,
        description="What was corrected and how (shown to moderators and linked to the case).",
    )


class ExpertReviewRequest(BaseModel):
    note: str = Field(min_length=10, max_length=1000)


class AuditEntryOut(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    reason: str | None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime


class ModerationStats(BaseModel):
    open: int
    in_review: int
    resolved: int
    dismissed: int
    total: int
    high_priority_open: int
    oldest_open_at: datetime | None = None
    sla_note: str


class PolicyOut(BaseModel):
    """Published moderation policy so users can see the rules they are judged by."""

    reporting: list[str]
    actions: list[dict[str, str]]
    corrections: list[str]
    ai_limits: list[str]
    appeals: list[str]
