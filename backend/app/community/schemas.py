"""Community API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.contracts import TrustLabel
from app.core.enums import ContentStatus, PostCategory, ReactionKind, ReportReason, ReportTargetType


class AuthorBrief(BaseModel):
    id: uuid.UUID
    display_name: str
    primary_role: str
    village: str | None = None
    district: str | None = None
    state: str | None = None
    verified_expert: bool = False
    is_following: bool = False


class MediaBrief(BaseModel):
    id: uuid.UUID
    url: str | None
    width: int | None
    height: int | None
    mime_type: str


class PostCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    body: str = Field(min_length=10, max_length=8000)
    category: PostCategory
    crop_code: str | None = Field(default=None, max_length=48)
    language: str = Field(default="en", pattern="^(en|mr|hi)$")
    state: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    village: str | None = Field(default=None, max_length=120)
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)
    source_urls: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Reference links (e.g. an official advisory) recorded with the post.",
    )
    farm_id: uuid.UUID | None = Field(
        default=None, description="Optional: attach farm context voluntarily (never required)"
    )
    crop_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one_of_farm_or_crop(self) -> PostCreate:
        if self.crop_id and not self.farm_id:
            raise ValueError("crop_id requires farm_id so the app can verify ownership.")
        return self


class PostUpdate(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=5, max_length=200)
    body: str | None = Field(default=None, min_length=10, max_length=8000)
    category: PostCategory | None = None
    crop_code: str | None = Field(default=None, max_length=48)
    media_ids: list[uuid.UUID] | None = Field(default=None, max_length=6)
    source_urls: list[str] | None = Field(default=None, max_length=5)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    parent_id: uuid.UUID | None = None
    source_urls: list[str] = Field(default_factory=list, max_length=3)


class CommentOut(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    parent_id: uuid.UUID | None
    author: AuthorBrief
    body: str
    trust_label: TrustLabel
    status: ContentStatus
    reaction_count: int
    report_count: int
    created_at: datetime
    edited_at: datetime | None = None
    my_reaction: str | None = None
    replies: list[CommentOut] = []
    is_demo: bool = False


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    category: PostCategory
    crop_code: str | None
    language: str
    state: str | None
    district: str | None
    village: str | None
    author: AuthorBrief
    media: list[MediaBrief] = []
    source_urls: list[str] = []
    trust_label: TrustLabel
    trust_reasons: list[str] = []
    engagement: dict[str, Any] = {}
    status: ContentStatus
    reaction_count: int
    comment_count: int
    save_count: int
    view_count: int
    report_count: int
    my_reaction: str | None = None
    is_saved: bool = False
    attached_farm: dict | None = None
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None = None
    is_demo: bool = False
    ranking: dict[str, float] | None = None


class FeedResponse(BaseModel):
    items: list[PostOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    ranking: dict[str, Any]
    filters: dict[str, Any]


class PostDetail(BaseModel):
    post: PostOut
    comments: list[CommentOut]
    similar_posts: list[dict] = Field(
        default_factory=list,
        description="Semantically similar posts (empty when no embeddings exist yet).",
    )
    similar_method: str | None = None


class ReactionRequest(BaseModel):
    kind: ReactionKind = ReactionKind.SUPPORT


class ReportRequest(BaseModel):
    target_type: ReportTargetType = Field(description="post | comment | user")
    target_id: uuid.UUID
    reason: ReportReason
    details: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional context for the moderator. Never required, never public.",
    )

    @model_validator(mode="after")
    def _details_for_other(self) -> ReportRequest:
        if self.reason == ReportReason.OTHER and not (self.details or "").strip():
            raise ValueError("Please describe the problem when choosing 'other'.")
        return self


class ReportAck(BaseModel):
    status: str
    report_id: uuid.UUID | None = None
    message: str
    already_reported: bool = False


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    category: PostCategory | None = None
    crop_code: str | None = None
    state: str | None = None
    top_k: int = Field(default=10, ge=1, le=30)


class SemanticSearchResponse(BaseModel):
    query: str
    results: list[dict]
    method: str
    index_used: bool
    embedding_provider: str
    embedding_is_demo: bool
    notices: list[str] = []


CommentOut.model_rebuild()
