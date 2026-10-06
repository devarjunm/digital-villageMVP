"""Community: posts, comments, reactions, saves, follows, reports."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.contracts import TrustLabel
from app.core.enums import (
    ContentStatus,
    PostCategory,
    ReactionKind,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    enum_col,
)
from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.database.types import Vector


class Post(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "posts"
    __table_args__ = (
        sa.CheckConstraint("length(title) BETWEEN 5 AND 200", name="title_length"),
        sa.CheckConstraint("length(body) BETWEEN 10 AND 8000", name="body_length"),
        sa.Index("ix_posts_status_created", "status", "created_at"),
        sa.Index("ix_posts_category_created", "category", "created_at"),
        sa.Index("ix_posts_crop_state", "crop_code", "state"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    category: Mapped[PostCategory] = mapped_column(
        enum_col(PostCategory, "post_category"), nullable=False, index=True
    )
    crop_code: Mapped[str | None] = mapped_column(sa.String(48), index=True)
    language: Mapped[str] = mapped_column(sa.String(8), default="en", nullable=False)
    state: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    district: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    village: Mapped[str | None] = mapped_column(sa.String(120))
    # Voluntarily attached farm context. Nullable by design: sharing farm data is
    # always the farmer's explicit choice.
    farm_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("farms.id", ondelete="SET NULL")
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("crops.id", ondelete="SET NULL")
    )
    status: Mapped[ContentStatus] = mapped_column(
        enum_col(ContentStatus, "content_status"),
        default=ContentStatus.PUBLISHED,
        nullable=False,
        index=True,
    )
    # Trust label is derived from the author's role/verification, never from
    # engagement counts (see app/community/trust.py).
    trust_label: Mapped[TrustLabel] = mapped_column(
        enum_col(TrustLabel, "trust_label"), default=TrustLabel.FARMER_EXPERIENCE, nullable=False
    )
    # Denormalised counters maintained inside the same transaction as the
    # underlying write; the authoritative counts live in the child tables.
    reaction_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    save_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    report_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    comments: Mapped[list[Comment]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="select"
    )
    reactions: Mapped[list[Reaction]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="select"
    )
    media: Mapped[list[PostMedia]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="selectin"
    )


class PostMedia(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "post_media"
    __table_args__ = (
        sa.UniqueConstraint("post_id", "media_id", name="uq_post_media_post_id_media_id"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    caption: Mapped[str | None] = mapped_column(sa.String(255))

    post: Mapped[Post] = relationship(back_populates="media")


class Comment(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    __tablename__ = "comments"
    __table_args__ = (
        sa.CheckConstraint("length(body) BETWEEN 1 AND 4000", name="body_length"),
        sa.Index("ix_comments_post_created", "post_id", "created_at"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ContentStatus] = mapped_column(
        enum_col(ContentStatus, "content_status"), default=ContentStatus.PUBLISHED, nullable=False
    )
    trust_label: Mapped[TrustLabel] = mapped_column(
        enum_col(TrustLabel, "trust_label"), default=TrustLabel.FARMER_EXPERIENCE, nullable=False
    )
    reaction_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    report_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    # A comment can reference the AI output it answers, if any.
    ai_output_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("ai_outputs.id", ondelete="SET NULL")
    )

    post: Mapped[Post] = relationship(back_populates="comments")
    replies: Mapped[list[Comment]] = relationship(
        back_populates="parent", cascade="all, delete-orphan", lazy="select"
    )
    parent: Mapped[Comment | None] = relationship(
        back_populates="replies", remote_side="Comment.id"
    )


class Reaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reactions"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "post_id", "comment_id", name="uq_reactions_user_target"),
        sa.CheckConstraint(
            "(post_id IS NOT NULL AND comment_id IS NULL) OR (post_id IS NULL AND comment_id IS NOT NULL)",
            name="exactly_one_target",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ReactionKind] = mapped_column(
        enum_col(ReactionKind, "reaction_kind"), default=ReactionKind.SUPPORT, nullable=False
    )

    post: Mapped[Post | None] = relationship(back_populates="reactions")


class SavedPost(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "saved_posts"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "post_id", name="uq_saved_posts_user_id_post_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    collection: Mapped[str | None] = mapped_column(sa.String(64))


class Follow(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "follows"
    __table_args__ = (
        sa.UniqueConstraint(
            "follower_id", "followee_id", name="uq_follows_follower_id_followee_id"
        ),
        sa.CheckConstraint("follower_id <> followee_id", name="no_self_follow"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class Report(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (
        sa.UniqueConstraint(
            "reporter_id", "target_type", "target_id", name="uq_reports_reporter_target"
        ),
        sa.Index("ix_reports_status_created", "status", "created_at"),
    )

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[ReportTargetType] = mapped_column(
        enum_col(ReportTargetType, "report_target_type"), nullable=False
    )
    target_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False, index=True)
    reason: Mapped[ReportReason] = mapped_column(
        enum_col(ReportReason, "report_reason"), nullable=False
    )
    details: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[ReportStatus] = mapped_column(
        enum_col(ReportStatus, "report_status"),
        default=ReportStatus.OPEN,
        nullable=False,
        index=True,
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(sa.Text)


class PostEmbedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Semantic index for community posts (pgvector on PostgreSQL)."""

    __tablename__ = "post_embeddings"
    __table_args__ = (sa.UniqueConstraint("post_id", name="uq_post_embeddings_post_id"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    embedding = mapped_column(Vector(384), nullable=False)
    embedding_model: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    embedding_version: Mapped[str] = mapped_column(sa.String(32), default="1", nullable=False)
    source_text_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
