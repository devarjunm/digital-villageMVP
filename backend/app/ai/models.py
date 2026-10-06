"""AI request/output/feedback bookkeeping, prediction history, agent
conversations, model registry and inference monitoring.

Traceability contract: every AI feature writes an `AIRequest` and, on success,
an `AIOutput` plus a `Prediction` row carrying `model_name` + `model_version`.
`ModelInferenceEvent` is the append-only monitoring feed (latency, outcome,
input fingerprint) used by the drift/latency dashboards.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AIRequestKind,
    AIRequestStatus,
    FeedbackVerdict,
    ModelStage,
    enum_col,
)
from app.database.base import (
    Base,
    DemoFlagMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AIRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "ai_requests"
    __table_args__ = (
        sa.Index("ix_ai_requests_kind_status", "kind", "status", "created_at"),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_non_negative"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[AIRequestKind] = mapped_column(
        enum_col(AIRequestKind, "ai_request_kind"), nullable=False, index=True
    )
    status: Mapped[AIRequestStatus] = mapped_column(
        enum_col(AIRequestStatus, "ai_request_status"),
        default=AIRequestStatus.QUEUED,
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(sa.String(8), default="en", nullable=False)
    input_summary: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    model_name: Mapped[str | None] = mapped_column(sa.String(96))
    model_version: Mapped[str | None] = mapped_column(sa.String(64))
    provider: Mapped[str | None] = mapped_column(sa.String(48))
    error_code: Mapped[str | None] = mapped_column(sa.String(64))
    error_detail: Mapped[str | None] = mapped_column(sa.Text)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("background_jobs.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    output: Mapped[AIOutput | None] = relationship(
        back_populates="request", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in (AIRequestStatus.SUCCEEDED, AIRequestStatus.FAILED)


class AIOutput(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_outputs"
    __table_args__ = (
        sa.UniqueConstraint("ai_request_id", name="uq_ai_outputs_ai_request_id"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
    )

    ai_request_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    output: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))
    confidence_interpretation: Mapped[str | None] = mapped_column(sa.String(300))
    evidence: Mapped[list[dict]] = mapped_column(sa.JSON, default=list, nullable=False)
    model_name: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    disclaimer: Mapped[str | None] = mapped_column(sa.Text)
    insufficient_evidence: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    request: Mapped[AIRequest] = relationship(back_populates="output")
    feedback: Mapped[list[AIFeedback]] = relationship(
        back_populates="ai_output", cascade="all, delete-orphan", lazy="selectin"
    )


class Prediction(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    """User-facing prediction history (disease scans, recommendations, yield and
    price estimates). Kept separate from AIRequest so history endpoints are a
    simple indexed query and so results survive request-log retention."""

    __tablename__ = "predictions"
    __table_args__ = (
        sa.Index("ix_predictions_user_kind_created", "user_id", "kind", "created_at"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="score_range"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("ai_requests.id", ondelete="SET NULL")
    )
    kind: Mapped[AIRequestKind] = mapped_column(
        enum_col(AIRequestKind, "ai_request_kind"), nullable=False, index=True
    )
    subject_type: Mapped[str | None] = mapped_column(sa.String(32))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True))
    crop_code: Mapped[str | None] = mapped_column(sa.String(48), index=True)
    label: Mapped[str | None] = mapped_column(sa.String(160))
    score: Mapped[float | None] = mapped_column(sa.Numeric(5, 4))
    result: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    input_summary: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    model_name: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class AIFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_feedback"
    __table_args__ = (
        sa.UniqueConstraint("ai_output_id", "user_id", name="uq_ai_feedback_ai_output_id_user_id"),
    )

    ai_output_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("ai_outputs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(
        enum_col(FeedbackVerdict, "feedback_verdict"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(sa.Text)
    corrected_label: Mapped[str | None] = mapped_column(sa.String(160))
    correction_details: Mapped[str | None] = mapped_column(sa.Text)
    # Explicit, revocable consent. Nothing is used for training without it.
    consent_to_train: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    used_in_training: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    ai_output: Mapped[AIOutput] = relationship(back_populates="feedback")


class AgentConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.String(200), default="New conversation", nullable=False)
    language: Mapped[str] = mapped_column(sa.String(8), default="en", nullable=False)
    farm_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("farms.id", ondelete="SET NULL")
    )
    crop_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("crops.id", ondelete="SET NULL")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", lazy="select"
    )


class AgentMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_messages"
    __table_args__ = (sa.Index("ix_agent_messages_conversation", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # user | assistant | tool
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(sa.String(64))
    tool_input: Mapped[dict | None] = mapped_column(sa.JSON)
    tool_output_summary: Mapped[dict | None] = mapped_column(sa.JSON)
    tool_error: Mapped[str | None] = mapped_column(sa.String(300))
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("ai_requests.id", ondelete="SET NULL")
    )
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)

    conversation: Mapped[AgentConversation] = relationship(back_populates="messages")


class ModelRegistryEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Model registry mirror (MLflow is the training-side source of truth).

    `metrics` is copied verbatim from the evaluation run recorded during
    training — the API never invents a metric value.
    """

    __tablename__ = "model_registry_entries"
    __table_args__ = (
        sa.UniqueConstraint("name", "version", name="uq_model_registry_entries_name_version"),
        sa.Index("ix_model_registry_entries_name_stage", "name", "stage"),
    )

    name: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    task: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    framework: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    stage: Mapped[ModelStage] = mapped_column(
        enum_col(ModelStage, "model_stage"), default=ModelStage.STAGING, nullable=False, index=True
    )
    mlflow_run_id: Mapped[str | None] = mapped_column(sa.String(64))
    artifact_uri: Mapped[str | None] = mapped_column(sa.String(512))
    metrics: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    parameters: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    training_data: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    evaluation_report: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    model_card_url: Mapped[str | None] = mapped_column(sa.String(512))
    trained_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text)


class ModelInferenceEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only inference telemetry (source for latency & drift views)."""

    __tablename__ = "model_inference_events"
    __table_args__ = (
        sa.Index("ix_model_inference_events_model_created", "model_name", "created_at"),
        sa.CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
    )

    model_name: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(16), nullable=False)  # success | error
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # Hashed, non-reversible fingerprint of the normalised input: lets us detect
    # distribution shift without storing the underlying farmer data.
    input_fingerprint: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    input_features: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    output_summary: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(sa.String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class ModelEvaluation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Evaluation run: either from training (held-out test set) or from
    production monitoring once labels become available via user feedback."""

    __tablename__ = "model_evaluations"

    model_name: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    evaluation_type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )  # test_set | production_labels
    dataset_version: Mapped[str | None] = mapped_column(sa.String(64))
    sample_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    metrics: Mapped[dict] = mapped_column(sa.JSON, default=dict, nullable=False)
    confusion_matrix: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    per_class_metrics: Mapped[list] = mapped_column(sa.JSON, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text)
