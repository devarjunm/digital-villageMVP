"""Knowledge base service: browse, ingest, update, retrieve."""

from __future__ import annotations

import uuid

from genai.rag.pipeline import IngestionService, RetrievalService, build_document_from_text
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.enums import DocumentType, Language, VerificationStatus
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.base import array_contains, utcnow
from app.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.knowledge.schemas import (
    DocumentCreateRequest,
    DocumentUpdateRequest,
    IngestionResult,
    KnowledgeDocumentDetail,
    KnowledgeDocumentOut,
)

logger = get_logger(__name__)


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ browse
    def to_out(self, document: KnowledgeDocument) -> KnowledgeDocumentOut:
        return KnowledgeDocumentOut.model_validate(document)

    def list(
        self,
        *,
        crop_code: str | None = None,
        language: Language | None = None,
        doc_type: DocumentType | None = None,
        verification_status: VerificationStatus | None = None,
        source_name: str | None = None,
        region: str | None = None,
        query: str | None = None,
        include_demo: bool = True,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDocumentOut], int]:
        stmt = select(KnowledgeDocument).where(KnowledgeDocument.deleted_at.is_(None))
        if not include_demo:
            stmt = stmt.where(KnowledgeDocument.is_demo.is_(False))
        if language:
            stmt = stmt.where(KnowledgeDocument.language == language)
        if doc_type:
            stmt = stmt.where(KnowledgeDocument.doc_type == doc_type)
        if verification_status:
            stmt = stmt.where(KnowledgeDocument.verification_status == verification_status)
        if source_name:
            stmt = stmt.where(KnowledgeDocument.source_name == source_name)
        if crop_code:
            stmt = stmt.where(array_contains(KnowledgeDocument.crop_codes, [crop_code]))
        if region:
            stmt = stmt.where(
                or_(
                    array_contains(KnowledgeDocument.state_codes, [region]),
                    # A document with no state tags is national guidance and applies everywhere.
                    KnowledgeDocument.state_codes == [],
                )
            )
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    KnowledgeDocument.title.ilike(pattern), KnowledgeDocument.summary.ilike(pattern)
                )
            )
        rows = list(
            self.db.execute(
                stmt.order_by(KnowledgeDocument.created_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )
        total = len(list(self.db.execute(stmt).scalars()))
        return [self.to_out(row) for row in rows], total

    def get(self, document_id: uuid.UUID) -> KnowledgeDocument:
        document = self.db.get(KnowledgeDocument, document_id)
        if document is None or document.deleted_at is not None:
            raise NotFoundError("That document could not be found.")
        return document

    def detail(self, document_id: uuid.UUID) -> KnowledgeDocumentDetail:
        document = self.get(document_id)
        chunks = list(
            self.db.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
                .limit(5)
            ).scalars()
        )
        base = self.to_out(document)
        return KnowledgeDocumentDetail(
            **base.model_dump(),
            chunks_preview=[
                {
                    "chunk_index": chunk.chunk_index,
                    "heading": chunk.heading,
                    "preview": chunk.content[:280],
                    "char_count": chunk.char_count,
                    "embedded": chunk.embedding is not None,
                    "embedding_model": chunk.embedding_model,
                }
                for chunk in chunks
            ],
            embedding_model=chunks[0].embedding_model if chunks else None,
        )

    # ------------------------------------------------------------------ ingest
    def create(
        self, *, payload: DocumentCreateRequest, actor_id: uuid.UUID | None, is_demo: bool = False
    ) -> tuple[KnowledgeDocument, IngestionResult]:
        document, result = build_document_from_text(
            self.db,
            title=payload.title,
            text=payload.content,
            source_name=payload.source_name,
            source_url=payload.source_url,
            language=payload.language.value,
            doc_type=payload.doc_type.value,
            crop_codes=payload.crop_codes,
            state_codes=payload.state_codes,
            publication_date=payload.publication_date,
            verification_status=payload.verification_status.value,
            created_by_id=actor_id,
            is_demo=is_demo,
        )
        document.topics = payload.topics
        document.summary = payload.summary
        document.license = payload.license
        self.db.commit()
        self.db.refresh(document)
        return document, IngestionResult(**result)

    def update(
        self, *, document_id: uuid.UUID, payload: DocumentUpdateRequest, actor_id: uuid.UUID | None
    ) -> tuple[KnowledgeDocument, IngestionResult | None]:
        document = self.get(document_id)
        data = payload.model_dump(exclude_unset=True)
        content = data.pop("content", None)
        for field, value in data.items():
            if value is not None:
                setattr(document, field, value)
        if payload.verification_status is not None:
            document.verified_by_id = actor_id
            document.verified_at = utcnow()
        if content:
            result = IngestionService(self.db).ingest(document=document, raw_text=content)
            self.db.refresh(document)
            return document, IngestionResult(**result)
        self.db.commit()
        self.db.refresh(document)
        return document, None

    def reindex(self, document_id: uuid.UUID) -> IngestionResult:
        document = self.get(document_id)
        chunks = list(
            self.db.execute(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .order_by(KnowledgeChunk.chunk_index)
            ).scalars()
        )
        if not chunks:
            raise ValidationError("This document has no stored text to re-index.")
        text = "\n\n".join(chunk.content for chunk in chunks)
        result = IngestionService(self.db).ingest(document=document, raw_text=text)
        self.db.refresh(document)
        return IngestionResult(**result)

    def soft_delete(self, document_id: uuid.UUID) -> None:
        document = self.get(document_id)
        document.deleted_at = utcnow()
        self.db.commit()

    # ---------------------------------------------------------------- retrieve
    def sources(self) -> list[str]:
        rows = self.db.execute(
            select(KnowledgeDocument.source_name)
            .where(KnowledgeDocument.deleted_at.is_(None))
            .distinct()
        ).scalars()
        return sorted(rows)

    def health(self) -> dict:
        from genai.llm.provider import get_llm_provider

        retrieval_health = RetrievalService(self.db).health()
        llm = get_llm_provider().health()
        return {
            **retrieval_health,
            "llm": llm,
            "note": (
                "Retrieval quality reflects the active embedding provider; the demo provider returns lexical "
                "vectors, so semantic recall is limited until a production embedding model is configured."
            ),
        }
