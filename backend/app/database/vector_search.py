"""Capability-aware vector search.

On PostgreSQL with pgvector the query uses the `<=>` cosine-distance operator and
can use an HNSW index. Elsewhere (SQLite test runs) the same interface is served
by fetching candidates and computing cosine similarity in Python, and the result
records `method="python_cosine_fallback"` so a test can never claim index-backed
search was verified when it was not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.database.capabilities import supports_pgvector

logger = get_logger(__name__)


@dataclass(slots=True)
class VectorHit:
    id: str
    score: float  # cosine similarity in [-1, 1]; higher is better
    distance: float
    metadata: dict[str, Any]
    content: str = ""


@dataclass(slots=True)
class VectorSearchResult:
    hits: list[VectorHit]
    method: str
    index_used: bool
    candidate_count: int


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _format_vector(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.7g}" for v in vector) + "]"


class KnowledgeVectorIndex:
    """pgvector-backed index over knowledge_chunks."""

    table = "knowledge_chunks"
    column = "embedding"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.engine: Engine = db.get_bind()  # type: ignore[assignment]

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int = 8,
        candidate_limit: int = 200,
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
    ) -> VectorSearchResult:
        filters = filters or {}
        if supports_pgvector(self.engine):
            return self._search_pgvector(
                query_vector=query_vector, top_k=top_k, filters=filters, min_score=min_score
            )
        return self._search_python(
            query_vector=query_vector,
            top_k=top_k,
            filters=filters,
            min_score=min_score,
            candidate_limit=candidate_limit,
        )

    # ------------------------------------------------------------- postgres
    def _search_pgvector(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any],
        min_score: float | None,
    ) -> VectorSearchResult:
        params: dict[str, Any] = {"qvec": _format_vector(query_vector), "k": top_k}
        conditions = ["kc.embedding IS NOT NULL"]
        if filters.get("language"):
            conditions.append("d.language = :language")
            params["language"] = filters["language"]
        if filters.get("doc_types"):
            conditions.append("d.doc_type = ANY(:doc_types)")
            params["doc_types"] = list(filters["doc_types"])
        if filters.get("document_id"):
            conditions.append("kc.document_id = :document_id")
            params["document_id"] = str(filters["document_id"])
        if filters.get("crop_codes"):
            conditions.append("d.crop_codes ?| :crop_codes")
            params["crop_codes"] = list(filters["crop_codes"])
        if filters.get("state_codes"):
            # `state_codes` is jsonb (see `database.base.json_document`), so the
            # array-length function must be `jsonb_array_length`. The earlier
            # `json_array_length` does not exist for jsonb: PostgreSQL raised
            # UndefinedFunction, the API surfaced it as 500 database_unavailable,
            # and *every* RAG answer request from a farmer with a known state
            # failed — the filter is always applied when farm context exists.
            # `?|` (JSONB key-exists-any) is already PostgreSQL-specific, so this
            # branch is consistently PostgreSQL syntax.
            conditions.append(
                "(d.state_codes ?| :state_codes OR jsonb_array_length(d.state_codes) = 0)"
            )
            params["state_codes"] = list(filters["state_codes"])
        if filters.get("verification_status"):
            conditions.append("d.verification_status = :verification_status")
            params["verification_status"] = filters["verification_status"]
        if filters.get("source_name"):
            conditions.append("d.source_name = :source_name")
            params["source_name"] = filters["source_name"]

        where_clause = " AND ".join(conditions)
        sql = text(
            f"""
            SELECT kc.id, kc.content, kc.document_id, kc.chunk_index, kc.heading,
                   d.title, d.source_name, d.source_url, d.doc_type, d.language,
                   d.verification_status, d.publication_date, d.crop_codes,
                   1 - (kc.embedding <=> CAST(:qvec AS vector)) AS score
            FROM {self.table} kc
            JOIN knowledge_documents d ON d.id = kc.document_id
            WHERE {where_clause} AND d.deleted_at IS NULL
            ORDER BY kc.embedding <=> CAST(:qvec AS vector)
            LIMIT :k
            """
        )
        rows = self.db.execute(sql, params).mappings().all()
        hits = [
            VectorHit(
                id=str(row["id"]),
                score=float(row["score"]),
                distance=1 - float(row["score"]),
                content=row["content"],
                metadata={
                    "document_id": str(row["document_id"]),
                    "chunk_index": row["chunk_index"],
                    "heading": row["heading"],
                    "title": row["title"],
                    "source_name": row["source_name"],
                    "source_url": row["source_url"],
                    "doc_type": row["doc_type"],
                    "language": row["language"],
                    "verification_status": row["verification_status"],
                    "publication_date": str(row["publication_date"])
                    if row["publication_date"]
                    else None,
                },
            )
            for row in rows
        ]
        if min_score is not None:
            hits = [h for h in hits if h.score >= min_score]
        return VectorSearchResult(
            hits=hits, method="pgvector_cosine", index_used=True, candidate_count=len(rows)
        )

    # --------------------------------------------------------------- sqlite
    def _search_python(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any],
        min_score: float | None,
        candidate_limit: int,
    ) -> VectorSearchResult:
        from app.knowledge.models import KnowledgeChunk, KnowledgeDocument

        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.embedding.is_not(None), KnowledgeDocument.deleted_at.is_(None))
            .limit(candidate_limit)
        )
        if filters.get("document_id"):
            stmt = stmt.where(KnowledgeChunk.document_id == filters["document_id"])
        if filters.get("language"):
            stmt = stmt.where(KnowledgeDocument.language == filters["language"])
        if filters.get("doc_types"):
            stmt = stmt.where(KnowledgeDocument.doc_type.in_(list(filters["doc_types"])))

        rows = self.db.execute(stmt).all()
        hits: list[VectorHit] = []
        for chunk, document in rows:
            score = cosine_similarity(query_vector, list(chunk.embedding or []))
            if min_score is not None and score < min_score:
                continue
            hits.append(
                VectorHit(
                    id=str(chunk.id),
                    score=round(score, 6),
                    distance=round(1 - score, 6),
                    content=chunk.content,
                    metadata={
                        "document_id": str(document.id),
                        "chunk_index": chunk.chunk_index,
                        "heading": chunk.heading,
                        "title": document.title,
                        "source_name": document.source_name,
                        "source_url": document.source_url,
                        "doc_type": document.doc_type.value
                        if hasattr(document.doc_type, "value")
                        else str(document.doc_type),
                        "language": document.language.value
                        if hasattr(document.language, "value")
                        else str(document.language),
                        "verification_status": document.verification_status.value
                        if hasattr(document.verification_status, "value")
                        else str(document.verification_status),
                        "publication_date": document.publication_date.isoformat()
                        if document.publication_date
                        else None,
                    },
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return VectorSearchResult(
            hits=hits[:top_k],
            method="python_cosine_fallback",
            index_used=False,
            candidate_count=len(rows),
        )


class PostVectorIndex:
    """pgvector index over community posts (semantic community search)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.engine: Engine = db.get_bind()  # type: ignore[assignment]

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
    ) -> VectorSearchResult:
        filters = filters or {}
        if supports_pgvector(self.engine):
            params: dict[str, Any] = {"qvec": _format_vector(query_vector), "k": top_k}
            conditions = [
                "pe.embedding IS NOT NULL",
                "p.deleted_at IS NULL",
                "p.status = 'published'",
            ]
            if filters.get("crop_code"):
                conditions.append("p.crop_code = :crop_code")
                params["crop_code"] = filters["crop_code"]
            if filters.get("category"):
                conditions.append("p.category = :category")
                params["category"] = filters["category"]
            if filters.get("state"):
                conditions.append("p.state = :state")
                params["state"] = filters["state"]
            if filters.get("district"):
                conditions.append("p.district = :district")
                params["district"] = filters["district"]
            if filters.get("language"):
                conditions.append("p.language = :language")
                params["language"] = filters["language"]
            sql = text(
                f"""
                SELECT p.id, p.title, p.body, pe.post_id,
                       1 - (pe.embedding <=> CAST(:qvec AS vector)) AS score
                FROM post_embeddings pe
                JOIN posts p ON p.id = pe.post_id
                WHERE {' AND '.join(conditions)}
                ORDER BY pe.embedding <=> CAST(:qvec AS vector)
                LIMIT :k
                """
            )
            rows = self.db.execute(sql, params).mappings().all()
            hits = [
                VectorHit(
                    id=str(row["id"]),
                    score=float(row["score"]),
                    distance=1 - float(row["score"]),
                    content=f"{row['title']}\n{row['body'][:400]}",
                    metadata={"post_id": str(row["id"]), "title": row["title"]},
                )
                for row in rows
            ]
            if min_score is not None:
                hits = [h for h in hits if h.score >= min_score]
            return VectorSearchResult(
                hits=hits, method="pgvector_cosine", index_used=True, candidate_count=len(rows)
            )

        from app.community.models import Post, PostEmbedding

        stmt = (
            select(PostEmbedding, Post)
            .join(Post, Post.id == PostEmbedding.post_id)
            .where(Post.deleted_at.is_(None))
            .limit(500)
        )
        if filters.get("crop_code"):
            stmt = stmt.where(Post.crop_code == filters["crop_code"])
        if filters.get("category"):
            stmt = stmt.where(Post.category == filters["category"])
        rows = self.db.execute(stmt).all()
        hits: list[VectorHit] = []
        for embedding_row, post in rows:
            score = cosine_similarity(query_vector, list(embedding_row.embedding or []))
            if min_score is not None and score < min_score:
                continue
            hits.append(
                VectorHit(
                    id=str(post.id),
                    score=round(score, 6),
                    distance=round(1 - score, 6),
                    content=f"{post.title}\n{post.body[:400]}",
                    metadata={"post_id": str(post.id), "title": post.title},
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return VectorSearchResult(
            hits=hits[:top_k],
            method="python_cosine_fallback",
            index_used=False,
            candidate_count=len(rows),
        )


def ensure_vector_indexes(db: Session) -> dict[str, Any]:
    """Creates HNSW indexes when pgvector is available. Idempotent; called by the
    embedding-reindex job and by the deployment runbook (never automatically at
    import time — index creation belongs to migrations/ops)."""
    engine = db.get_bind()
    if not supports_pgvector(engine):
        return {"created": [], "skipped": True, "reason": "pgvector not available on this database"}
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding ON knowledge_chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
        "CREATE INDEX IF NOT EXISTS ix_post_embeddings_hnsw ON post_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)",
    ]
    created: list[str] = []
    for statement in statements:
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(statement)
            created.append(statement.split(" ON ")[1].split(" ")[0])
        except Exception as exc:
            logger.warning(
                "vector_index_creation_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )
    return {"created": created, "skipped": False, "dimension": settings.embedding_dim}
