"""Agricultural knowledge base: documents, chunks, embeddings, ingestions."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DocumentType, Language, VerificationStatus, enum_col
from app.database.base import (
    Base,
    DemoFlagMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    json_document,
)
from app.database.types import Vector


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, DemoFlagMixin):
    """A source document. Provenance is mandatory: every document records where
    it came from, when it was published/updated, its language and its
    verification status. The RAG layer may only cite rows from this table (and
    the derived chunks), which is what makes fabricated citations impossible.
    """

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        sa.CheckConstraint("length(title) >= 5", name="title_length"),
        sa.Index("ix_knowledge_documents_lang_type", "language", "doc_type"),
    )

    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    source_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    source_url: Mapped[str | None] = mapped_column(sa.String(1024))
    source_organisation_type: Mapped[str | None] = mapped_column(sa.String(64))
    publication_date: Mapped[date | None] = mapped_column(sa.Date)
    last_updated_on: Mapped[date | None] = mapped_column(sa.Date)
    language: Mapped[Language] = mapped_column(
        enum_col(Language, "language"), default=Language.EN, nullable=False
    )
    doc_type: Mapped[DocumentType] = mapped_column(
        enum_col(DocumentType, "document_type"), nullable=False, index=True
    )
    crop_codes: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    state_codes: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    topics: Mapped[list[str]] = mapped_column(json_document(), default=list, nullable=False)
    license: Mapped[str | None] = mapped_column(sa.String(160))
    summary: Mapped[str | None] = mapped_column(sa.Text)
    # Where the raw content came from: manual | url_import | file_upload
    ingestion_method: Mapped[str] = mapped_column(sa.String(32), default="manual", nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_col(VerificationStatus, "verification_status"),
        default=VerificationStatus.UNVERIFIED,
        nullable=False,
        index=True,
    )
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    indexing_status: Mapped[str] = mapped_column(
        sa.String(16), default="pending", nullable=False, index=True
    )
    indexing_error: Mapped[str | None] = mapped_column(sa.Text)
    chunk_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="select"
    )


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_knowledge_chunks_document_index"
        ),
        sa.CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(sa.String(300))
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    char_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    embedding = mapped_column(Vector(384), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(sa.String(96))
    embedding_version: Mapped[str | None] = mapped_column(sa.String(32))
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
