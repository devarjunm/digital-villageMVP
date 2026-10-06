"""Unified search across knowledge documents, community posts and schemes.

Two modes, and the API always says which one ran:

  * `mode=keyword` — PostgreSQL full-text/ILIKE matching. Exact wording matters,
    but it is fast, needs no embeddings, and works on any database.
  * `mode=semantic` — pgvector cosine similarity over embedded chunks/posts,
    with the same metadata filters (crop, language, state, document type,
    verification status).
  * `mode=hybrid` (default) — both, merged with reciprocal-rank fusion.

Results are grouped by type and every item carries `source_type` plus the
metadata a user needs to judge it (verification status, trust label, source URL,
whether it came from demo data).
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.auth.dependencies import DbSession, OptionalUser
from app.core.enums import DocumentType, PostCategory, VerificationStatus
from app.core.i18n import resolve_language
from app.core.logging import get_logger
from app.core.ratelimit import enforce_rate_limit

logger = get_logger(__name__)
router = APIRouter()

RRF_K = 60  # reciprocal rank fusion constant (documented, not tuned on data)


def _keyword_documents(
    db, *, query: str, language: str | None, doc_type: DocumentType | None, limit: int
):
    from sqlalchemy import exists, or_, select

    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument

    stmt = select(KnowledgeDocument).where(KnowledgeDocument.deleted_at.is_(None))
    pattern = f"%{query}%"
    # Document body text lives in chunks, so the keyword search covers the title,
    # the summary and the indexed chunk text (via EXISTS, not a row-multiplying join).
    stmt = stmt.where(
        or_(
            KnowledgeDocument.title.ilike(pattern),
            KnowledgeDocument.summary.ilike(pattern),
            exists().where(
                KnowledgeChunk.document_id == KnowledgeDocument.id,
                KnowledgeChunk.content.ilike(pattern),
            ),
        )
    )
    if language:
        stmt = stmt.where(KnowledgeDocument.language == language)
    if doc_type:
        stmt = stmt.where(KnowledgeDocument.doc_type == doc_type)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [
        {
            "source_type": "knowledge_document",
            "id": str(row.id),
            "title": row.title,
            "snippet": (row.summary or _first_chunk_text(db, row.id))[:300],
            "language": row.language.value if hasattr(row.language, "value") else str(row.language),
            "doc_type": row.doc_type.value if hasattr(row.doc_type, "value") else str(row.doc_type),
            "verification_status": row.verification_status.value
            if hasattr(row.verification_status, "value")
            else str(row.verification_status),
            "source_name": row.source_name,
            "source_url": row.source_url,
            "crop_codes": row.crop_codes or [],
            "is_demo": row.is_demo,
            "score": None,
            "method": "keyword",
        }
        for row in rows
    ]


def _first_chunk_text(db, document_id) -> str:
    from sqlalchemy import select

    from app.knowledge.models import KnowledgeChunk

    content = db.execute(
        select(KnowledgeChunk.content)
        .where(KnowledgeChunk.document_id == document_id)
        .order_by(KnowledgeChunk.chunk_index.asc())
        .limit(1)
    ).scalar_one_or_none()
    return content or ""


def _keyword_posts(db, *, query: str, crop: str | None, state: str | None, limit: int):
    from app.community.repository import PostRepository

    stmt = PostRepository(db).query_posts(crop_code=crop, state=state, query=query)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [
        {
            "source_type": "community_post",
            "id": str(row.id),
            "title": row.title,
            "snippet": row.body[:300],
            "language": row.language,
            "category": row.category.value if hasattr(row.category, "value") else str(row.category),
            "trust_label": row.trust_label.value
            if hasattr(row.trust_label, "value")
            else str(row.trust_label),
            "crop_code": row.crop_code,
            "state": row.state,
            "reaction_count": row.reaction_count,
            "comment_count": row.comment_count,
            "is_demo": row.is_demo,
            "score": None,
            "method": "keyword",
        }
        for row in rows
    ]


def _keyword_schemes(db, *, query: str, state: str | None, language: str, limit: int):
    from app.schemes.service import SchemeService

    service = SchemeService(db)
    items, _total = service.list(state=state, query=query, language=language, limit=limit, offset=0)
    return [
        {
            "source_type": "scheme",
            "id": item.slug,
            "title": item.name,
            "snippet": (item.eligibility_summary or item.description or "")[:300],
            "language": item.language,
            "category": item.category,
            "state_codes": item.state_codes,
            "verification_status": item.verification_status,
            "source_url": item.official_source_url,
            "is_demo": item.is_demo,
            "score": None,
            "method": "keyword",
        }
        for item in items
    ]


def _semantic(
    db, *, query: str, language: str | None, crop: str | None, state: str | None, top_k: int
):
    from genai.embeddings.provider import get_embedding_provider

    from app.database.vector_search import KnowledgeVectorIndex, PostVectorIndex

    provider = get_embedding_provider()
    embedded = provider.embed([query], input_type="query")
    vector = embedded.vectors[0]

    results: list[dict[str, Any]] = []
    knowledge_filters: dict[str, Any] = {}
    if language:
        knowledge_filters["language"] = language
    if crop:
        knowledge_filters["crop_codes"] = [crop]
    if state:
        knowledge_filters["state_codes"] = [state]
    knowledge = KnowledgeVectorIndex(db).search(
        query_vector=vector, top_k=top_k, filters=knowledge_filters
    )
    for hit in knowledge.hits:
        meta = hit.metadata or {}
        results.append(
            {
                "source_type": "knowledge_chunk",
                "id": hit.id,
                "document_id": meta.get("document_id"),
                "title": meta.get("title") or "Knowledge document",
                "snippet": hit.content[:300],
                "language": meta.get("language"),
                "doc_type": meta.get("doc_type"),
                "verification_status": meta.get("verification_status"),
                "source_name": meta.get("source_name"),
                "source_url": meta.get("source_url"),
                "crop_codes": meta.get("crop_codes") or [],
                "is_demo": bool(meta.get("is_demo", False)),
                "score": round(hit.score, 4),
                "method": knowledge.method,
            }
        )

    post_filters: dict[str, Any] = {}
    if crop:
        post_filters["crop_code"] = crop
    if state:
        post_filters["state"] = state
    posts = PostVectorIndex(db).search(query_vector=vector, top_k=top_k, filters=post_filters)
    for hit in posts.hits:
        meta = hit.metadata or {}
        results.append(
            {
                "source_type": "community_post",
                "id": hit.id,
                "title": meta.get("title") or "Community post",
                "snippet": hit.content[:300],
                "category": meta.get("category"),
                "trust_label": meta.get("trust_label"),
                "crop_code": meta.get("crop_code"),
                "state": meta.get("state"),
                "is_demo": bool(meta.get("is_demo", False)),
                "score": round(hit.score, 4),
                "method": posts.method,
            }
        )
    return results, {
        "method": f"{knowledge.method}+{posts.method}",
        "index_used": bool(knowledge.index_used and posts.index_used),
        "embedding_provider": embedded.provider,
        "embedding_model": embedded.model,
        "embedding_is_demo": embedded.is_demo,
        "notices": embedded.notices,
    }


def _fuse(keyword: list[dict], semantic: list[dict], limit: int) -> list[dict]:
    """Reciprocal rank fusion — deterministic, no learned weights."""
    scores: dict[tuple[str, str], float] = {}
    payloads: dict[tuple[str, str], dict] = {}
    for source, items in (("keyword", keyword), ("semantic", semantic)):
        for rank, item in enumerate(items, start=1):
            key = (item["source_type"], str(item["id"]))
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            payload = dict(item)
            payload.setdefault("matched_by", [])
            if source not in payload["matched_by"]:
                payload["matched_by"].append(source)
            payloads[key] = {**payloads.get(key, {}), **payload}
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    merged: list[dict] = []
    for key, score in ordered[:limit]:
        item = dict(payloads[key])
        item["fusion_score"] = round(score, 6)
        merged.append(item)
    return merged


@router.get("", summary="Search knowledge, community and schemes")
def search(
    db: DbSession,
    request: Request,
    user: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    mode: Annotated[str, Query(pattern="^(keyword|semantic|hybrid)$")] = "hybrid",
    language: Annotated[str | None, Query(max_length=8)] = None,
    crop: Annotated[str | None, Query(max_length=48)] = None,
    state: Annotated[str | None, Query(max_length=120)] = None,
    doc_type: Annotated[DocumentType | None, Query()] = None,
    verification_status: Annotated[VerificationStatus | None, Query()] = None,
    category: Annotated[PostCategory | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    enforce_rate_limit(request, "search")
    started = time.perf_counter()
    lang = resolve_language(language, request.headers.get("accept-language"))
    warnings: list[str] = []

    keyword_items: list[dict] = []
    if mode in {"keyword", "hybrid"}:
        keyword_items += _keyword_documents(
            db, query=q, language=language, doc_type=doc_type, limit=limit
        )
        keyword_items += _keyword_posts(db, query=q, crop=crop, state=state, limit=limit)
        keyword_items += _keyword_schemes(db, query=q, state=state, language=lang, limit=limit)
        if category:
            keyword_items = [
                item
                for item in keyword_items
                if item["source_type"] != "community_post" or item.get("category") == category.value
            ]
        if verification_status:
            keyword_items = [
                item
                for item in keyword_items
                if item["source_type"] != "knowledge_document"
                or item.get("verification_status") == verification_status.value
            ]

    semantic_items: list[dict] = []
    semantic_meta: dict[str, Any] = {}
    if mode in {"semantic", "hybrid"}:
        try:
            semantic_items, semantic_meta = _semantic(
                db, query=q, language=language, crop=crop, state=state, top_k=limit
            )
            if category:
                semantic_items = [
                    item
                    for item in semantic_items
                    if item["source_type"] != "community_post"
                    or item.get("category") == category.value
                ]
        except Exception as exc:
            logger.warning(
                "semantic_search_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )
            warnings.append(
                "Semantic search is temporarily unavailable; showing keyword results only. "
                f"Reason: {type(exc).__name__}."
            )

    if mode == "keyword" or (mode == "hybrid" and not semantic_items):
        items = keyword_items[:limit]
        for item in items:
            item.setdefault("matched_by", ["keyword"])
        method = "keyword"
    elif mode == "semantic":
        items = semantic_items[:limit]
        for item in items:
            item.setdefault("matched_by", ["semantic"])
        method = "semantic"
    else:
        items = _fuse(keyword_items, semantic_items, limit)
        method = "hybrid_rrf"

    notices: list[str] = list(semantic_meta.get("notices") or [])
    if semantic_meta.get("embedding_is_demo"):
        notices.append(
            "Semantic search used the demo embedding provider (lexical vectors): exact wording matches well, "
            "paraphrases may be missed until a production embedding model is configured."
        )
    if any(item.get("is_demo") for item in items):
        notices.append(
            "Some results come from demo data seeded for development. Each item carries an is_demo flag."
        )
    if not items:
        # "Nothing matched" must be said in words: an empty list is ambiguous
        # between "no such topic" and "the index/search is not set up yet".
        notices.append(
            "No results matched this query. Try fewer or more general words, or remove filters"
            + (
                " — the semantic index is still using the demo embedding provider."
                if semantic_meta.get("embedding_is_demo")
                else "."
            )
        )

    return {
        "query": q,
        "mode": mode,
        "method": method,
        "language": lang,
        "filters": {
            "crop": crop,
            "state": state,
            "doc_type": doc_type.value if doc_type else None,
            "verification_status": verification_status.value if verification_status else None,
            "category": category.value if category else None,
        },
        "counts": {
            "total": len(items),
            "keyword_candidates": len(keyword_items),
            "semantic_candidates": len(semantic_items),
            "by_type": _count_by_type(items),
        },
        "items": items,
        "semantic": semantic_meta or None,
        "warnings": warnings,
        "notices": notices,
        "fusion": (
            {
                "method": "reciprocal_rank_fusion",
                "k": RRF_K,
                "note": "Deterministic fusion of keyword and vector rankings; no learned weights are used.",
            }
            if method == "hybrid_rrf"
            else None
        ),
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def _count_by_type(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item.get("source_type"))
        counts[key] = counts.get(key, 0) + 1
    return counts


@router.get("/suggest", summary="Lightweight autocomplete over document titles and crop names")
def suggest(
    db: DbSession,
    request: Request,
    user: OptionalUser,
    q: Annotated[str, Query(min_length=2, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> dict:
    enforce_rate_limit(request, "search")
    from sqlalchemy import select

    from app.crops.models import CropCatalog
    from app.knowledge.models import KnowledgeDocument

    pattern = f"%{q}%"
    docs = (
        db.execute(
            select(KnowledgeDocument.title)
            .where(KnowledgeDocument.deleted_at.is_(None), KnowledgeDocument.title.ilike(pattern))
            .limit(limit)
        )
        .scalars()
        .all()
    )
    crops = db.execute(
        select(CropCatalog.code, CropCatalog.name_en)
        .where(CropCatalog.name_en.ilike(pattern))
        .limit(limit)
    ).all()
    suggestions = [{"type": "document", "text": title} for title in docs]
    suggestions += [{"type": "crop", "text": name, "code": code} for code, name in crops]
    return {
        "query": q,
        "suggestions": suggestions[:limit],
        "kind": "prefix_substring_match",
        "note": "Suggestions come from your own database only; no external suggestion service is called.",
    }
