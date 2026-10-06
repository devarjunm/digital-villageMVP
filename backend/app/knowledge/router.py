"""Knowledge base and RAG endpoints.

`/ask` is the RAG entry point: it retrieves evidence, generates an answer through
the configured LLM provider, and returns provider/retrieval metadata plus
citations. When retrieval finds nothing above the configured floor, the response
says so explicitly (`insufficient_evidence: true`) instead of guessing.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from genai.rag.pipeline import RAGAnswerService, RetrievalService

from app.analytics.service import AnalyticsService
from app.auth.dependencies import (
    AdminUser,
    DbSession,
    ExpertUser,
    OptionalUser,
    StaffUser,
)
from app.core.enums import DocumentType, Language, VerificationStatus
from app.core.i18n import resolve_language
from app.core.pagination import PageParams, page_params, paginate
from app.core.ratelimit import enforce_rate_limit
from app.knowledge.schemas import (
    AskRequest,
    AskResponse,
    DocumentCreateRequest,
    DocumentUpdateRequest,
    GuardrailReportOut,
    IngestionResult,
    KnowledgeDocumentDetail,
    KnowledgeHealth,
    RetrievedChunkOut,
    RetrieveRequest,
    RetrieveResponse,
)
from app.knowledge.service import KnowledgeService

router = APIRouter()


def _filters_dict(filters) -> dict:
    data = filters.model_dump(exclude_unset=True, exclude_none=True)
    mapping: dict = {}
    if data.get("crop_code"):
        mapping["crop_codes"] = [data["crop_code"]]
    if data.get("language"):
        mapping["language"] = data["language"]
    if data.get("doc_types"):
        mapping["doc_types"] = data["doc_types"]
    if data.get("region"):
        mapping["state_codes"] = [data["region"]]
    if data.get("source_name"):
        mapping["source_name"] = data["source_name"]
    if data.get("verification_status"):
        mapping["verification_status"] = data["verification_status"]
    if data.get("document_id"):
        mapping["document_id"] = str(data["document_id"])
    if data.get("published_after"):
        mapping["published_after"] = data["published_after"]
    return mapping


@router.get("/documents", summary="Browse knowledge documents")
def list_documents(
    db: DbSession,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    crop: Annotated[str | None, Query(max_length=48)] = None,
    language: Annotated[Language | None, Query()] = None,
    doc_type: Annotated[DocumentType | None, Query()] = None,
    verification_status: Annotated[VerificationStatus | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    include_demo: bool = True,
) -> dict:
    enforce_rate_limit(request, "read")
    items, total = KnowledgeService(db).list(
        crop_code=crop,
        language=language,
        doc_type=doc_type,
        verification_status=verification_status,
        source_name=source,
        query=q,
        include_demo=include_demo,
        limit=params.limit,
        offset=params.offset,
    )
    return paginate(items, params, total)


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
    summary="Document detail with chunk preview",
)
def get_document(document_id: uuid.UUID, db: DbSession) -> KnowledgeDocumentDetail:
    return KnowledgeService(db).detail(document_id)


@router.post(
    "/documents",
    response_model=IngestionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Add and index a knowledge document (expert/staff)",
)
def create_document(
    payload: DocumentCreateRequest, user: ExpertUser, db: DbSession
) -> IngestionResult:
    document, result = KnowledgeService(db).create(payload=payload, actor_id=user.id)
    return result


@router.patch(
    "/documents/{document_id}",
    response_model=IngestionResult | None,
    summary="Update a document (content changes re-index automatically)",
)
def update_document(
    document_id: uuid.UUID, payload: DocumentUpdateRequest, user: StaffUser, db: DbSession
) -> IngestionResult | None:
    _document, result = KnowledgeService(db).update(
        document_id=document_id, payload=payload, actor_id=user.id
    )
    return result


@router.post(
    "/documents/{document_id}/reindex",
    response_model=IngestionResult,
    summary="Re-embed a document",
)
def reindex_document(document_id: uuid.UUID, user: StaffUser, db: DbSession) -> IngestionResult:
    return KnowledgeService(db).reindex(document_id)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a document",
)
def delete_document(document_id: uuid.UUID, user: AdminUser, db: DbSession) -> None:
    KnowledgeService(db).soft_delete(document_id)


@router.post(
    "/retrieve", response_model=RetrieveResponse, summary="Semantic retrieval with metadata filters"
)
def retrieve(payload: RetrieveRequest, db: DbSession, request: Request) -> RetrieveResponse:
    enforce_rate_limit(request, "search")
    result = RetrievalService(db).retrieve(
        query=payload.query,
        filters=_filters_dict(payload.filters),
        top_k=payload.top_k,
        use_reranker=payload.rerank,
    )
    return RetrieveResponse(
        query=payload.query,
        chunks=[
            RetrievedChunkOut(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.title,
                heading=chunk.heading,
                source_name=chunk.source_name,
                source_url=chunk.source_url,
                doc_type=chunk.doc_type,
                language=chunk.language,
                verification_status=chunk.verification_status,
                publication_date=chunk.publication_date,
                content=chunk.content,
                vector_score=chunk.vector_score,
                rerank_score=chunk.rerank_score,
            )
            for chunk in result.chunks
        ],
        citations=[chunk.as_evidence() for chunk in result.chunks],
        method=result.method,
        index_used=result.index_used,
        reranker=result.reranker,
        candidate_count=result.candidate_count,
        latency_ms=result.latency_ms,
        embedding_provider=result.embedding_provider,
        embedding_model=result.embedding_model,
        embedding_is_demo=result.embedding_is_demo,
        filters_applied=result.filters_applied,
        notices=(
            ["Retrieval used the demo embedding provider (lexical vectors)."]
            if result.embedding_is_demo
            else []
        ),
    )


@router.post("/ask", response_model=AskResponse, summary="RAG answer grounded in indexed documents")
def ask(payload: AskRequest, db: DbSession, request: Request, user: OptionalUser) -> AskResponse:
    enforce_rate_limit(request, "ai")
    language = (payload.language.value if payload.language else None) or resolve_language(
        user.preferred_language.value if user else None, request.headers.get("accept-language")
    )
    context_lines: list[str] = []
    if payload.use_farm_context and user is not None:
        from app.farmers.service import FarmerService

        dashboard = FarmerService(db).dashboard(user)
        for crop in dashboard.active_crops[:5]:
            context_lines.append(
                f"Your crop: {crop['crop_name']} (code {crop['crop_code']}) on farm '{crop['farm_name']}', "
                f"stage {crop['stage']}, sown {crop['sowing_date']}, area {crop['area_value']} {crop['area_unit']}."
            )
        context_lines.append(
            f"Your profile: state {dashboard.profile.state}, district {dashboard.profile.district}, "
            f"crops {', '.join(dashboard.profile.primary_crops) or 'not recorded'}."
        )
    filters = _filters_dict(payload.filters)
    if user is not None and user.profile and not filters.get("state_codes") and user.profile.state:
        filters["state_codes"] = [user.profile.state]

    service = RAGAnswerService(db)
    result = service.answer(
        question=payload.question,
        language=language,
        filters=filters,
        top_k=payload.top_k,
        extra_context=context_lines,
    )

    from app.ai.request_log import record_ai_request

    ai_request_id = record_ai_request(
        db,
        user_id=user.id if user else None,
        kind="assistant_chat",
        language=language,
        input_summary={
            "question": payload.question[:300],
            "filters": filters,
            "farm_context_used": bool(context_lines),
        },
        output={
            "answer": result.answer[:2000],
            "citations": [c.model_dump(mode="json") for c in result.citations],
            "insufficient_evidence": result.insufficient_evidence,
            "guardrail": asdict(result.guardrail),
        },
        model_name=f"rag:{result.llm_provider}",
        model_version=result.llm_model,
        confidence=result.guardrail.top_score,
        confidence_interpretation=(
            "Retrieval similarity of the best matching source (not a probability that the answer is correct)."
        ),
        evidence=[c.model_dump(mode="json") for c in result.citations],
        insufficient_evidence=result.insufficient_evidence,
        latency_ms=result.latency_ms,
        provider=result.llm_provider,
        is_demo=result.llm_is_demo or result.retrieval.embedding_is_demo,
    )
    AnalyticsService(db).record_event(
        name="assistant_message",
        user_id=user.id if user else None,
        props={
            "language": language,
            "citations_count": len(result.citations),
            "insufficient_evidence": result.insufficient_evidence,
            "source": "knowledge_ask",
        },
        is_demo=result.llm_is_demo,
    )
    source_types = ["knowledge"]
    if any(c.kind == "knowledge_chunk" for c in result.citations):
        source_types = ["knowledge"]
    if context_lines:
        source_types.append("farmer_farm_context")
    return AskResponse(
        answer=result.answer,
        citations=result.citations,
        insufficient_evidence=result.insufficient_evidence,
        insufficient_reason=result.insufficient_reason,
        guardrails=GuardrailReportOut(
            grounded=result.guardrail.grounded,
            top_score=result.guardrail.top_score,
            citation_count=result.guardrail.citation_count,
            flags=result.guardrail.flags,
            actions=result.guardrail.actions,
            notices=result.guardrail.notices,
            answer_modified=result.guardrail.answer_modified,
        ),
        llm={
            "provider": result.llm_provider,
            "model": result.llm_model,
            "is_demo": result.llm_is_demo,
            "note": (
                "Demo provider active: answers are extractive summaries of retrieved evidence, not LLM text. "
                "Configure LLM_PROVIDER for generative answers."
                if result.llm_is_demo
                else "Generated by the configured LLM provider."
            ),
        },
        retrieval={
            "method": result.retrieval.method,
            "index_used": result.retrieval.index_used,
            "reranker": result.retrieval.reranker,
            "candidate_count": result.retrieval.candidate_count,
            "latency_ms": result.retrieval.latency_ms,
            "embedding_provider": result.retrieval.embedding_provider,
            "embedding_model": result.retrieval.embedding_model,
            "embedding_is_demo": result.retrieval.embedding_is_demo,
            "filters_applied": result.retrieval.filters_applied,
        },
        notices=result.notices,
        disclaimer=result.disclaimer,
        ai_request_id=ai_request_id,
        source_types=source_types,
    )


@router.get("/sources", response_model=list[str], summary="Distinct document sources")
def sources(db: DbSession) -> list[str]:
    return KnowledgeService(db).sources()


@router.get("/health", response_model=KnowledgeHealth, summary="Index and model provider status")
def health(db: DbSession) -> KnowledgeHealth:
    return KnowledgeHealth(**KnowledgeService(db).health())
