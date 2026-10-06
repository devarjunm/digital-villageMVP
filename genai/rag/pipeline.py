"""RAG pipeline: ingest → chunk → embed → store (pgvector) → retrieve → rerank
→ answer with citations → guardrails.

Key properties:
  * ingestion is idempotent per (document, chunk content hash): re-running only
    embeds new or changed chunks;
  * retrieval applies metadata filters (crop, language, region, doc type, source,
    verification status, date window) in the same query as the vector search;
  * citations are *constructed from retrieved rows*, then re-verified, so an
    answer cannot reference a document that was not retrieved;
  * insufficient evidence returns a structured "I don't know" response with the
    reason, never a guess;
  * every stage is timed and reported so callers (and the admin console) can see
    latency and which components were actually used.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.contracts import AI_DISCLAIMER, EvidenceItem
from app.core.i18n import t
from app.core.logging import get_logger
from app.database.capabilities import supports_pgvector
from app.database.vector_search import KnowledgeVectorIndex
from app.knowledge.models import KnowledgeChunk, KnowledgeDocument
from genai.embeddings.provider import EmbeddingProvider, get_embedding_provider
from genai.guardrails.agriculture import (
    GuardrailReport,
    apply_dosage_rule,
    check_citations,
    check_grounding,
    notice_for_flags,
    safety_flags,
)
from genai.llm.provider import LLMMessage, LLMProvider, get_llm_provider
from genai.reranking.lexical import Candidate, RankedCandidate, get_reranker

logger = get_logger(__name__)


# --------------------------------------------------------------------- schemas (light DTOs)
@dataclass(slots=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    source_name: str
    source_url: str | None
    doc_type: str
    language: str
    verification_status: str
    publication_date: str | None
    heading: str | None
    content: str
    vector_score: float
    rerank_score: float | None = None

    def as_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            kind="knowledge_chunk",
            ref_id=self.chunk_id,
            title=f"{self.title}" + (f" — {self.heading}" if self.heading else ""),
            source_name=self.source_name,
            source_url=self.source_url,
            snippet=self.content[:400],
            score=self.rerank_score
            if self.rerank_score is not None
            else self.vector_score,
            verification_status=self.verification_status,
            published_at=date.fromisoformat(self.publication_date)
            if self.publication_date
            else None,
        )


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    method: str
    index_used: bool
    reranker: str
    candidate_count: int
    latency_ms: int
    embedding_provider: str
    embedding_model: str
    embedding_is_demo: bool
    filters_applied: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AnswerResult:
    answer: str
    citations: list[EvidenceItem]
    insufficient_evidence: bool
    insufficient_reason: str | None
    guardrail: GuardrailReport
    llm_provider: str
    llm_model: str
    llm_is_demo: bool
    retrieval: RetrievalResult
    notices: list[str] = field(default_factory=list)
    disclaimer: str = AI_DISCLAIMER
    latency_ms: int = 0


# --------------------------------------------------------------------- ingestion
class IngestionService:
    """Chunk + embed + store. Called by the API (admin upload) and by the worker."""

    def __init__(self, db: Session, provider: EmbeddingProvider | None = None) -> None:
        self.db = db
        self.provider = provider or get_embedding_provider()

    def ingest(self, *, document: KnowledgeDocument, raw_text: str) -> dict[str, Any]:
        from genai.rag.chunking import chunk_text

        started = time.perf_counter()
        chunks = chunk_text(raw_text)
        if not chunks:
            document.indexing_status = "failed"
            document.indexing_error = (
                "No text content could be extracted from this document."
            )
            self.db.commit()
            return {
                "document_id": str(document.id),
                "chunks": 0,
                "embedded": 0,
                "status": "failed",
                "error": document.indexing_error,
            }

        existing = {
            row.content_hash: row
            for row in self.db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
            ).scalars()
        }

        to_embed: list[tuple[int, Any]] = []
        embedded_count = 0
        for chunk in chunks:
            row = existing.get(chunk.content_hash)
            if row is None:
                row = KnowledgeChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    heading=chunk.heading,
                    content=chunk.content,
                    token_count=chunk.token_estimate,
                    char_count=chunk.char_count,
                    content_hash=chunk.content_hash,
                )
                self.db.add(row)
                self.db.flush()
                to_embed.append((len(to_embed), row))
            elif row.embedding is None or row.embedding_model != self.provider.model:
                to_embed.append((len(to_embed), row))

        if to_embed:
            vectors = self.provider.embed(
                [row.content for _i, row in to_embed], input_type="document"
            )
            for (position, row), vector in zip(to_embed, vectors.vectors):
                row.embedding = vector
                row.embedding_model = vectors.model
                row.embedding_version = vectors.version
            embedded_count = len(to_embed)

        # Remove chunks that no longer exist in the source text.
        current_hashes = {chunk.content_hash for chunk in chunks}
        for content_hash, row in existing.items():
            if content_hash not in current_hashes:
                self.db.delete(row)

        document.indexing_status = "indexed"
        document.indexing_error = None
        document.chunk_count = len(chunks)
        document.verified_at = document.verified_at or None
        self.db.commit()

        result = {
            "document_id": str(document.id),
            "chunks": len(chunks),
            "embedded": embedded_count,
            "reused": len(chunks) - embedded_count,
            "embedding_provider": self.provider.name,
            "embedding_model": self.provider.model,
            "embedding_is_demo": self.provider.is_demo,
            "status": "indexed",
            "note": (
                "Embeddings were produced by the demo provider (lexical vectors). Configure "
                "EMBEDDING_PROVIDER for true semantic retrieval."
                if self.provider.is_demo
                else "Embeddings produced by the configured production embedding provider."
            ),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        logger.info(
            "document_ingested",
            extra={"extra_fields": {"chunks": len(chunks), "embedded": embedded_count}},
        )
        return result


# -------------------------------------------------------------------- retrieval
class RetrievalService:
    def __init__(self, db: Session, provider: EmbeddingProvider | None = None) -> None:
        self.db = db
        self.provider = provider or get_embedding_provider()
        self.index = KnowledgeVectorIndex(db)
        self.reranker = get_reranker()

    def retrieve(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
        use_reranker: bool = True,
    ) -> RetrievalResult:
        started = time.perf_counter()
        top_k = top_k or settings.rag_top_k
        min_score = settings.rag_min_score if min_score is None else min_score
        filters = {k: v for k, v in (filters or {}).items() if v not in (None, [], "")}

        embed_result = self.provider.embed([query], input_type="query")
        query_vector = embed_result.vectors[0]
        search = self.index.search(
            query_vector=query_vector,
            top_k=max(top_k * 4, 12),
            filters=filters,
            min_score=None,  # reranker applies the score floor after combining signals
        )

        chunks = [self._to_chunk(hit) for hit in search.hits]
        reranker_name = "none"
        if use_reranker and chunks:
            candidates = [
                Candidate(
                    id=chunk.chunk_id,
                    text=f"{chunk.title}. {chunk.heading or ''}. {chunk.content}",
                    vector_score=chunk.vector_score,
                    metadata={
                        "crop_code": filters.get("crop_code"),
                        "language": chunk.language,
                        "doc_type": chunk.doc_type,
                        "source_name": chunk.source_name,
                    },
                )
                for chunk in chunks
            ]
            ranked: list[RankedCandidate] = self.reranker.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
                metadata_filters=filters,
            )
            by_id = {chunk.chunk_id: chunk for chunk in chunks}
            reranked: list[RetrievedChunk] = []
            for item in ranked:
                chunk = by_id[item.candidate.id]
                chunk.rerank_score = item.score
                reranked.append(chunk)
            chunks = [c for c in reranked if (c.rerank_score or 0) >= min_score]
            reranker_name = getattr(self.reranker, "name", "lexical_bm25")
        else:
            chunks = [c for c in chunks if c.vector_score >= min_score][:top_k]

        latency_ms = int((time.perf_counter() - started) * 1000)
        return RetrievalResult(
            chunks=chunks,
            method=search.method,
            index_used=search.index_used,
            reranker=reranker_name,
            candidate_count=search.candidate_count,
            latency_ms=latency_ms,
            embedding_provider=embed_result.provider,
            embedding_model=embed_result.model,
            embedding_is_demo=embed_result.is_demo,
            filters_applied=filters,
        )

    @staticmethod
    def _to_chunk(hit: Any) -> RetrievedChunk:
        meta = hit.metadata
        return RetrievedChunk(
            chunk_id=hit.id,
            document_id=str(meta.get("document_id")),
            title=meta.get("title") or "Untitled document",
            source_name=meta.get("source_name") or "unknown",
            source_url=meta.get("source_url"),
            doc_type=meta.get("doc_type") or "unknown",
            language=meta.get("language") or "en",
            verification_status=meta.get("verification_status") or "unverified",
            publication_date=meta.get("publication_date"),
            heading=meta.get("heading"),
            content=hit.content,
            vector_score=hit.score,
        )

    def health(self) -> dict[str, Any]:
        indexed = int(
            self.db.execute(
                select(KnowledgeChunk.id)
                .where(KnowledgeChunk.embedding.is_not(None))
                .limit(1)
            ).scalar()
            is not None
        )
        documents = int(
            self.db.execute(select(KnowledgeDocument.id)).scalars().all().__len__()
        )
        chunks_with_vectors = int(
            self.db.execute(
                select(KnowledgeChunk.id).where(KnowledgeChunk.embedding.is_not(None))
            )
            .scalars()
            .all()
            .__len__()
        )
        return {
            "embedding_provider": self.provider.health(),
            "reranker": getattr(self.reranker, "name", "lexical_bm25"),
            "pgvector": supports_pgvector(self.db.get_bind()),
            "documents": documents,
            "chunks_with_embeddings": chunks_with_vectors,
            "has_indexed_content": indexed,
        }


# ----------------------------------------------------------------------- answer
class RAGAnswerService:
    """Retrieval-augmented answer generation with guardrails."""

    def __init__(
        self,
        db: Session,
        *,
        llm: LLMProvider | None = None,
        retrieval: RetrievalService | None = None,
    ) -> None:
        self.db = db
        self.llm = llm or get_llm_provider()
        self.retrieval = retrieval or RetrievalService(db)

    def answer(
        self,
        *,
        question: str,
        language: str = "en",
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        extra_context: list[str] | None = None,
        include_community: bool = False,
    ) -> AnswerResult:
        started = time.perf_counter()
        retrieval = self.retrieval.retrieve(
            query=question, filters=filters, top_k=top_k
        )

        hits_pairs = [
            (
                chunk.rerank_score
                if chunk.rerank_score is not None
                else chunk.vector_score,
                chunk.content,
            )
            for chunk in retrieval.chunks
        ]
        grounded, reason = check_grounding(
            answer="", hits=hits_pairs, min_score=settings.rag_min_score
        )

        citations = [chunk.as_evidence() for chunk in retrieval.chunks]
        notices: list[str] = []
        if retrieval.embedding_is_demo:
            notices.append(
                "Retrieval used the demo embedding provider (lexical vectors). Configure EMBEDDING_PROVIDER "
                "for true semantic search quality."
            )

        if not grounded:
            answer_text = t("notice.insufficient_evidence", language)
            return AnswerResult(
                answer=answer_text,
                citations=[],
                insufficient_evidence=True,
                insufficient_reason=reason,
                guardrail=GuardrailReport(
                    grounded=False,
                    top_score=None,
                    citation_count=0,
                    notices=[reason or ""],
                ),
                llm_provider=self.llm.name,
                llm_model=self.llm.model,
                llm_is_demo=self.llm.is_demo,
                retrieval=retrieval,
                notices=notices
                + [
                    "No answer was generated because the indexed evidence was insufficient. "
                    "This is deliberate: the assistant does not guess about agricultural practice."
                ],
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        context_blocks = []
        for index, chunk in enumerate(retrieval.chunks, start=1):
            label = f"{chunk.source_name} | {chunk.title}" + (
                f" | {chunk.heading}" if chunk.heading else ""
            )
            context_blocks.append(f"[EVIDENCE {index}: {label}]\n{chunk.content}")
        for extra in extra_context or []:
            context_blocks.append(f"[CONTEXT: Digital Village farm data]\n{extra}")

        system_prompt = (
            "You are the Digital Village agricultural assistant.\n"
            "Rules you must follow:\n"
            "1. Answer only from the EVIDENCE and CONTEXT blocks provided. If they do not contain the answer, "
            "say that you cannot answer from the available sources.\n"
            "2. Cite the source label of every statement you take from evidence.\n"
            "3. Never invent a source, a scheme name, a price, a dosage or a statistic.\n"
            "4. Distinguish clearly between retrieved documentation, general explanation and any model output "
            "that appears in the context.\n"
            "5. State uncertainty plainly and recommend a qualified local professional (agriculture officer, "
            "KVK, veterinarian) for consequential decisions.\n"
            f"6. Answer in the user's language: {language} (en=English, mr=Marathi, hi=Hindi). "
            "Keep agricultural terms in the language commonly used by farmers.\n"
        )
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="system", content="CONTEXT:\n" + "\n\n".join(context_blocks)
            ),
            LLMMessage(role="user", content=question),
        ]
        llm_result = self.llm.complete(messages, temperature=0.1)

        answer_text = llm_result.text.strip()
        guardrail_flags = safety_flags(question, answer_text)
        answer_text, modified, actions = apply_dosage_rule(
            answer=answer_text,
            evidence_texts=[chunk.content for chunk in retrieval.chunks],
        )
        citations, citation_actions = check_citations(
            citations=citations,
            hits=[
                (chunk.vector_score, chunk.content, chunk.as_evidence())
                for chunk in retrieval.chunks
            ],
        )
        notices.extend(notice_for_flags(guardrail_flags))
        notices.extend(llm_result.notices)

        report = GuardrailReport(
            grounded=True,
            top_score=max(hits_pairs)[0] if hits_pairs else None,
            citation_count=len(citations),
            flags=guardrail_flags,
            actions=actions + citation_actions,
            notices=notices,
            answer_modified=modified,
        )
        logger.info(
            "rag_answer_generated",
            extra={
                "extra_fields": {
                    "llm": self.llm.name,
                    "is_demo_llm": self.llm.is_demo,
                    "chunks": len(retrieval.chunks),
                    "citations": len(citations),
                    "flags": guardrail_flags,
                }
            },
        )
        return AnswerResult(
            answer=answer_text,
            citations=citations,
            insufficient_evidence=False,
            insufficient_reason=None,
            guardrail=report,
            llm_provider=llm_result.provider,
            llm_model=llm_result.model,
            llm_is_demo=llm_result.is_demo,
            retrieval=retrieval,
            notices=notices,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def build_document_from_text(
    db: Session,
    *,
    title: str,
    text: str,
    source_name: str,
    source_url: str | None,
    language: str,
    doc_type: str,
    crop_codes: list[str] | None = None,
    state_codes: list[str] | None = None,
    publication_date: date | None = None,
    verification_status: str = "unverified",
    created_by_id: uuid.UUID | None = None,
    is_demo: bool = False,
) -> tuple[KnowledgeDocument, dict[str, Any]]:
    """Create + index a document from raw text (admin/seed path)."""
    from app.core.enums import DocumentType, Language, VerificationStatus

    document = KnowledgeDocument(
        title=title[:300],
        source_name=source_name[:200],
        source_url=source_url,
        language=Language(language) if language in ("en", "mr", "hi") else Language.EN,
        doc_type=DocumentType(doc_type)
        if doc_type in {d.value for d in DocumentType}
        else DocumentType.ARTICLE,
        crop_codes=crop_codes or [],
        state_codes=state_codes or [],
        publication_date=publication_date,
        verification_status=VerificationStatus(verification_status)
        if verification_status in {v.value for v in VerificationStatus}
        else VerificationStatus.UNVERIFIED,
        indexing_status="pending",
        is_demo=is_demo,
    )
    db.add(document)
    db.flush()
    result = IngestionService(db).ingest(document=document, raw_text=text)
    return document, result
