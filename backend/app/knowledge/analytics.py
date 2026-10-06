"""Knowledge-base and platform analytics.

Two different things live here, and they are deliberately kept apart:

  1. **Product analytics** (`analytics_events`) — first-party, allow-listed events
     written by the API (post created, AI request, search performed…). No third
     party, no cross-site tracking, no advertising identifier. Users can opt out
     and can see what is stored (`/analytics/me/events`).
  2. **Knowledge/AI operational metrics** — corpus size, verification mix,
     retrieval health, AI request counts and latencies. Aggregates only.

Nothing here reports a metric it cannot compute from stored rows: there are no
placeholder numbers and no extrapolated "insights".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.ai.models import AIRequest, ModelInferenceEvent
from app.auth.dependencies import AdminUser, CurrentUser, DbSession, StaffUser
from app.core.config import settings
from app.core.enums import AIRequestKind, AIRequestStatus, PostCategory
from app.core.ratelimit import enforce_rate_limit
from app.knowledge.models import KnowledgeChunk, KnowledgeDocument

analytics_router = APIRouter()


@analytics_router.get("/overview", summary="Platform analytics overview (staff)")
def overview(db: DbSession, user: StaffUser, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, "read")
    return _overview(db, days=30)


@analytics_router.get("/knowledge", summary="Knowledge base composition")
def knowledge_analytics(db: DbSession, user: StaffUser, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, "read")
    from app.core.enums import VerificationStatus

    total_documents = _count(db, KnowledgeDocument)
    total_chunks = _count(db, KnowledgeChunk)
    embedded_chunks = int(
        db.execute(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.embedding.is_not(None))
        ).scalar_one()
    )
    by_verification = {
        status.value: _count(db, KnowledgeDocument, KnowledgeDocument.verification_status == status)
        for status in VerificationStatus
    }
    by_language = dict(
        db.execute(
            select(KnowledgeDocument.language, func.count()).group_by(KnowledgeDocument.language)
        ).all()
    )
    by_doc_type = dict(
        db.execute(
            select(KnowledgeDocument.doc_type, func.count()).group_by(KnowledgeDocument.doc_type)
        ).all()
    )
    demo_documents = _count(db, KnowledgeDocument, KnowledgeDocument.is_demo.is_(True))
    last_ingested = db.execute(select(func.max(KnowledgeDocument.created_at))).scalar_one_or_none()
    return {
        "documents": total_documents,
        "chunks": total_chunks,
        "embedded_chunks": embedded_chunks,
        "embedding_coverage_percent": round(100 * embedded_chunks / total_chunks, 1)
        if total_chunks
        else 0.0,
        "by_verification_status": {
            str(k.value if hasattr(k, "value") else k): v for k, v in by_verification.items()
        },
        "by_language": {
            str(k.value if hasattr(k, "value") else k): v for k, v in by_language.items()
        },
        "by_document_type": {
            str(k.value if hasattr(k, "value") else k): v for k, v in by_doc_type.items()
        },
        "demo_documents": demo_documents,
        "real_documents": total_documents - demo_documents,
        "last_document_added_at": last_ingested,
        "note": (
            "Counts are exact row counts. 'Embedding coverage' is the share of chunks with a stored vector; "
            "chunks without a vector are excluded from semantic retrieval but remain available to keyword search."
        ),
    }


@analytics_router.get("/ai", summary="AI usage by kind, provider and status (staff)")
def ai_analytics(
    db: DbSession,
    user: StaffUser,
    request: Request,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> dict[str, Any]:
    enforce_rate_limit(request, "read")
    since = datetime.now(UTC) - timedelta(days=days)
    by_kind = {
        kind.value: _count(db, AIRequest, AIRequest.kind == kind, since=since)
        for kind in AIRequestKind
    }
    rows = db.execute(
        select(AIRequest.provider, func.count(), func.avg(AIRequest.latency_ms))
        .where(AIRequest.created_at >= since)
        .group_by(AIRequest.provider)
    ).all()
    by_status = dict(
        db.execute(
            select(AIRequest.status, func.count())
            .where(AIRequest.created_at >= since)
            .group_by(AIRequest.status)
        ).all()
    )
    failed = int(
        db.execute(
            select(func.count())
            .select_from(AIRequest)
            .where(
                AIRequest.created_at >= since,
                AIRequest.status.in_([AIRequestStatus.FAILED, AIRequestStatus.REJECTED]),
            )
        ).scalar_one()
    )
    insufficient = int(
        db.execute(
            select(func.count())
            .select_from(AIRequest)
            .where(AIRequest.created_at >= since, AIRequest.insufficient_evidence.is_(True))
        ).scalar_one()
    )
    inference_events = int(
        db.execute(
            select(func.count())
            .select_from(ModelInferenceEvent)
            .where(ModelInferenceEvent.created_at >= since)
        ).scalar_one()
    )
    return {
        "window_days": days,
        "requests_by_kind": by_kind,
        "requests_by_status": {
            str(k.value if hasattr(k, "value") else k): v for k, v in by_status.items()
        },
        "providers": [
            {"provider": provider, "requests": count, "avg_latency_ms": round(float(avg or 0), 1)}
            for provider, count, avg in rows
        ],
        "failed_or_rejected": failed,
        "insufficient_evidence_answers": insufficient,
        "model_inference_events": inference_events,
        "note": (
            "Counts come from the ai_requests table. Accuracy is NOT reported here: no automatic "
            "ground-truth loop exists, so any accuracy figure would be fabricated."
        ),
    }


@analytics_router.get("/community", summary="Community activity (staff)")
def community_analytics(
    db: DbSession,
    user: StaffUser,
    request: Request,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> dict[str, Any]:
    enforce_rate_limit(request, "read")
    from app.community.models import Comment, Post, Report

    since = datetime.now(UTC) - timedelta(days=days)
    posts = _count(db, Post, Post.created_at >= since)
    comments = _count(db, Comment, Comment.created_at >= since)
    by_category = {
        category.value: _count(db, Post, Post.category == category, since=since)
        for category in PostCategory
    }
    reports = _count(db, Report, Report.created_at >= since)
    unanswered = _count(
        db,
        Post,
        Post.comment_count == 0,
        since=since,
    )
    return {
        "window_days": days,
        "posts_created": posts,
        "comments_created": comments,
        "posts_by_category": by_category,
        "unanswered_posts": unanswered,
        "reports_filed": reports,
        "report_rate_percent": round(100 * reports / posts, 2) if posts else 0.0,
        "active_authors": int(
            db.execute(
                select(func.count(func.distinct(Post.author_id))).where(Post.created_at >= since)
            ).scalar_one()
        ),
    }


@analytics_router.get("/me/events", summary="Your own recorded product events")
def my_events(
    db: DbSession,
    user: CurrentUser,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Transparency: users can see exactly what the platform recorded about them."""
    enforce_rate_limit(request, "read")
    from app.analytics.models import ProductEvent

    rows = list(
        db.execute(
            select(ProductEvent)
            .where(ProductEvent.user_id == user.id)
            .order_by(ProductEvent.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "name": row.name,
                "props": row.props,
                "created_at": row.created_at,
                "is_demo": row.is_demo,
            }
            for row in rows
        ],
        "note": (
            "These are the only product analytics events stored for your account. They contain no location "
            "history, no contact list and no advertising identifier."
        ),
    }


@analytics_router.get("/me/preferences", summary="Analytics opt-out state")
def my_preferences(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """The analytics purpose is one entry in the general consent record.

    This endpoint is a convenience view over `user_consents`; the authoritative
    list of purposes lives at GET /api/v1/users/me/consents.
    """
    from app.core.enums import ConsentKind
    from app.users.consent import ConsentService, policy_version

    service = ConsentService(db)
    decision = service.current(user.id, ConsentKind.ANALYTICS)
    return {
        "analytics_opt_in": service.has_consent(user.id, ConsentKind.ANALYTICS),
        "policy_version": policy_version(),
        "decided_at": decision.decided_at if decision else None,
        "note": (
            "Product events are only recorded while this purpose is granted; with no recorded decision the "
            "platform records none. Operational logs (errors, security events, rate limiting) are kept "
            "regardless, for a limited period, so the platform can function safely."
        ),
    }


@analytics_router.patch("/me/preferences", summary="Opt out of product analytics")
def set_preferences(db: DbSession, user: CurrentUser, analytics_opt_in: bool) -> dict[str, Any]:
    from app.core.enums import ConsentKind, ConsentSource
    from app.users.consent import ConsentService, policy_version

    ConsentService(db).record(
        user_id=user.id,
        kind=ConsentKind.ANALYTICS,
        granted=analytics_opt_in,
        source=ConsentSource.MOBILE_APP,
        note="Set through the analytics preferences endpoint.",
    )
    return {
        "analytics_opt_in": analytics_opt_in,
        "saved": True,
        "policy_version": policy_version(),
        "note": (
            "Recorded as a consent decision. Turning this off stops new product events for your account "
            "immediately; already-recorded events remain until you delete your account or ask support to purge them."
        ),
    }


@analytics_router.get("/health", summary="Analytics subsystem health (admin)")
def analytics_health(db: DbSession, user: AdminUser) -> dict[str, Any]:
    from app.analytics.models import ProductEvent
    from app.users.consent import ConsentService

    return {
        "events_recorded": _count(db, ProductEvent),
        "last_event_at": db.execute(select(func.max(ProductEvent.created_at))).scalar_one_or_none(),
        "events_last_7_days": _count(db, ProductEvent, since=datetime.now(UTC) - timedelta(days=7)),
        "consent_required_for_signed_in_users": settings.analytics_requires_consent,
        "consent": ConsentService(db).consent_stats(),
        "retention_note": "Product events are kept for 400 days by default and can be purged by an admin.",
    }


def _count(db, model, *conditions, since=None) -> int:
    stmt = select(func.count()).select_from(model)
    if since is not None:
        stmt = stmt.where(model.created_at >= since)
    for condition in conditions:
        if condition is not None:
            stmt = stmt.where(condition)
    return int(db.execute(stmt).scalar_one())


def _overview(db, *, days: int) -> dict[str, Any]:
    from app.ai.models import AIRequest as _AI
    from app.community.models import Comment, Post
    from app.farms.models import Farm
    from app.users.models import User

    since = datetime.now(UTC) - timedelta(days=days)
    return {
        "window_days": days,
        "users": {
            "total": _count(db, User),
            "active": _count(db, User, User.is_active.is_(True)),
            "new_in_window": _count(db, User, since=since),
            "demo_accounts": _count(db, User, User.is_demo.is_(True)),
            "real_accounts": _count(db, User, User.is_demo.is_(False)),
        },
        "farms": {"total": _count(db, Farm)},
        "community": {
            "posts_in_window": _count(db, Post, since=since),
            "comments_in_window": _count(db, Comment, since=since),
        },
        "ai_requests_in_window": _count(db, _AI, since=since),
        "data_quality": {
            "demo_vs_real_note": (
                "Development records are flagged (`is_demo`) and reported separately; they are never "
                "silently merged with real usage numbers."
            )
        },
    }
