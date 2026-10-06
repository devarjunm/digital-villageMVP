"""User account schemas (public projections never include contact details)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import ConsentKind, Language, Role, UserStatus


class UserPublicProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    primary_role: Role
    display_name: str | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    state: str | None = None
    primary_crops: list[str] = []
    interests: list[str] = []
    farming_experience_years: int | None = None
    organisation: str | None = None
    bio: str | None = None
    verified_expert: bool = False
    post_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    is_following: bool = False
    member_since: datetime


class UpdateAccountRequest(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    preferred_language: Language | None = None
    avatar_media_id: uuid.UUID | None = None
    email: EmailStr | None = None


class AdminUpdateUserRequest(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    status: UserStatus | None = None
    primary_role: Role | None = None
    add_role: Role | None = None
    remove_role: Role | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_required_with_status(cls, v, info):
        # Any change to status or roles is an auditable action, so it needs a reason.
        if (
            info.data.get("status")
            or info.data.get("primary_role")
            or info.data.get("add_role")
            or info.data.get("remove_role")
        ) and (not v or len(v.strip()) < 5):
            raise ValueError("A short reason is required for account changes (audit log).")
        return v


class DeleteAccountRequest(BaseModel):
    confirm: str = Field(description="Type DELETE to confirm")


class UserSearchResult(BaseModel):
    id: uuid.UUID
    display_name: str
    primary_role: Role
    village: str | None
    district: str | None
    state: str | None
    primary_crops: list[str] = []


class ConsentDecision(BaseModel):
    kind: ConsentKind
    granted: bool


class ConsentUpdateRequest(BaseModel):
    """A batch of decisions from the consent screen.

    Clients send only the purposes the user actually answered; a purpose that is
    left out keeps its previous (or absent) state, and an absent state counts as
    refused.
    """

    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")

    decisions: list[ConsentDecision] = Field(min_length=1, max_length=len(ConsentKind))
    policy_version: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "The policy version the user was shown. If it does not match the server's current version the "
            "request is rejected with 422, so a stale screen cannot record a decision against new wording."
        ),
    )
    app_version: str | None = Field(default=None, max_length=24)

    @field_validator("decisions")
    @classmethod
    def _unique_kinds(cls, value: list[ConsentDecision]) -> list[ConsentDecision]:
        kinds = [item.kind for item in value]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Send at most one decision per purpose.")
        return value


class ConsentItem(BaseModel):
    kind: ConsentKind
    title: str
    description: str
    required: bool
    granted: bool
    decided_at: datetime | None = None
    revoked_at: datetime | None = None
    source: str | None = None


class ConsentOverview(BaseModel):
    policy_version: str
    items: list[ConsentItem]
    note: str


class DataExportRequest(BaseModel):
    """User-initiated export of their own data (privacy requirement)."""

    confirm: str = Field(description="Type EXPORT to confirm.")

    @field_validator("confirm")
    @classmethod
    def _confirm(cls, value: str) -> str:
        if value.strip().upper() != "EXPORT":
            raise ValueError("Type EXPORT to confirm this request.")
        return "EXPORT"
