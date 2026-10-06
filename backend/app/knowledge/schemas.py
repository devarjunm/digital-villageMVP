"""Knowledge base and RAG API contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.contracts import EvidenceItem
from app.core.enums import DocumentType, Language, VerificationStatus


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_name: str
    source_url: str | None
    publication_date: date | None
    last_updated_on: date | None
    language: Language
    doc_type: DocumentType
    category: str | None = None
    crop_codes: list[str] = []
    state_codes: list[str] = []
    topics: list[str] = []
    license: str | None
    summary: str | None
    verification_status: VerificationStatus
    indexing_status: str
    indexing_error: str | None
    chunk_count: int
    is_demo: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocumentOut):
    chunks_preview: list[dict[str, Any]] = []
    embedding_model: str | None = None


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    content: str = Field(min_length=50, description="Document text (plain text or markdown)")
    source_name: str = Field(min_length=2, max_length=200)
    source_url: str | None = Field(default=None, max_length=1024)
    language: Language = Language.EN
    doc_type: DocumentType = DocumentType.ARTICLE
    crop_codes: list[str] = Field(default_factory=list, max_length=20)
    state_codes: list[str] = Field(default_factory=list, max_length=20)
    topics: list[str] = Field(default_factory=list, max_length=20)
    publication_date: date | None = None
    license: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=1000)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class DocumentUpdateRequest(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    verification_status: VerificationStatus | None = None
    summary: str | None = Field(default=None, max_length=1000)
    topics: list[str] | None = None
    crop_codes: list[str] | None = None
    state_codes: list[str] | None = None
    content: str | None = Field(
        default=None, min_length=50, description="Replaces content and re-indexes"
    )


class IngestionResult(BaseModel):
    document_id: uuid.UUID
    chunks: int
    embedded: int
    reused: int = 0
    embedding_provider: str
    embedding_model: str
    embedding_is_demo: bool
    status: str
    note: str
    latency_ms: int


class RetrievalFilters(BaseModel):
    crop_code: str | None = None
    language: Language | None = None
    doc_types: list[DocumentType] | None = None
    region: str | None = Field(default=None, description="State name or code")
    source_name: str | None = None
    verification_status: VerificationStatus | None = None
    published_after: date | None = None
    document_id: uuid.UUID | None = None


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int = Field(default=6, ge=1, le=20)
    rerank: bool = True


class RetrievedChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    heading: str | None
    source_name: str
    source_url: str | None
    doc_type: str
    language: str
    verification_status: str
    publication_date: str | None
    content: str
    vector_score: float
    rerank_score: float | None = None


class RetrieveResponse(BaseModel):
    query: str
    chunks: list[RetrievedChunkOut]
    citations: list[EvidenceItem]
    method: str
    index_used: bool
    reranker: str
    candidate_count: int
    latency_ms: int
    embedding_provider: str
    embedding_model: str
    embedding_is_demo: bool
    filters_applied: dict[str, Any] = {}
    notices: list[str] = []


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    language: Language | None = Field(
        default=None, description="Response language; defaults to your profile language"
    )
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int = Field(default=6, ge=1, le=12)
    use_farm_context: bool = Field(
        default=True,
        description="Include your farm/crop data as CONTEXT (labelled separately from evidence)",
    )


class GuardrailReportOut(BaseModel):
    grounded: bool
    top_score: float | None = None
    citation_count: int
    flags: list[str] = []
    actions: list[str] = []
    notices: list[str] = []
    answer_modified: bool = False


class AskResponse(BaseModel):
    answer: str
    citations: list[EvidenceItem]
    insufficient_evidence: bool
    insufficient_reason: str | None = None
    guardrails: GuardrailReportOut
    llm: dict[str, Any]
    retrieval: dict[str, Any]
    notices: list[str] = []
    disclaimer: str
    ai_request_id: uuid.UUID | None = None
    data_class: Literal["model_output"] = "model_output"
    source_types: list[str] = Field(
        default_factory=list,
        description="Which kinds of sources contributed (knowledge, farm context, …)",
    )


class KnowledgeHealth(BaseModel):
    embedding: dict[str, Any]
    reranker: str
    pgvector: bool
    documents: int
    chunks_with_embeddings: int
    has_indexed_content: bool
    llm: dict[str, Any]
    note: str
