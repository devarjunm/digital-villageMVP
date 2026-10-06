"""Moderation endpoints (moderator/admin) + the public policy page.

The policy endpoint is public on purpose: users should be able to read exactly
how content is judged, what the automated signals can and cannot do, and how to
appeal, without needing an account.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import (
    AdminUser,
    DbSession,
    StaffUser,
    client_metadata,
    current_session_id,
)
from app.core.enums import ReportReason, ReportStatus, ReportTargetType
from app.core.pagination import PageParams, page_params
from app.core.ratelimit import enforce_rate_limit
from app.moderation.schemas import (
    ActionRequest,
    AuditEntryOut,
    CaseOut,
    CorrectionRequest,
    ExpertReviewRequest,
    ModerationStats,
    PolicyOut,
    QueueResponse,
)
from app.moderation.service import ModerationService

router = APIRouter()

PageDep = Annotated[PageParams, Depends(page_params)]


@router.get("/policy", response_model=PolicyOut, summary="Public moderation policy")
def policy() -> PolicyOut:
    return PolicyOut(
        reporting=[
            "Anyone can report a post, reply or account. Each report opens a case for a human moderator.",
            "Reporting never hides content automatically, and the reported author is not told who reported them.",
            "False or repeated reporting is itself a moderation offence.",
        ],
        actions=[
            {"action": "note", "effect": "Adds a private note; content stays visible."},
            {"action": "dismiss", "effect": "Closes the case with no change to the content."},
            {
                "action": "hide",
                "effect": "Content is hidden from feeds but remains visible to its author and moderators.",
            },
            {
                "action": "remove",
                "effect": "Content is removed from the platform; the author is notified with the reason.",
            },
            {
                "action": "warn_author",
                "effect": "The author receives a warning that is recorded on the case.",
            },
            {
                "action": "restrict_author",
                "effect": "Temporary or permanent restriction on posting; audited.",
            },
        ],
        corrections=[
            "Incorrect but honestly-shared farming information is corrected, not deleted: a correction is linked "
            "to the original post so other farmers can see the revision.",
            "Expert-verified corrections carry the Expert information label; official-source corrections carry the "
            "Official information label.",
        ],
        ai_limits=[
            "Automated signals only rank cases for human review (spam/contact solicitation, payment or document "
            "requests, unsourced chemical dosage claims, duplication, volume).",
            "No automated system decides that an agricultural claim is scientifically false; that requires an "
            "evidence workflow with a human expert.",
            "Trust labels describe provenance (farmer/expert/official/AI), never popularity.",
        ],
        appeals=[
            "Every moderation action notifies the author with the reason and a link to the case.",
            "Authors can reply to that notification to request a review; a different moderator reviews it.",
            "Moderators cannot act on their own content, and every action is written to an append-only audit log.",
        ],
    )


@router.get("/queue", response_model=QueueResponse, summary="Moderation queue (moderator/admin)")
def queue(
    db: DbSession,
    user: StaffUser,
    request: Request,
    params: PageDep,
    status_filter: Annotated[ReportStatus | None, Query(alias="status")] = ReportStatus.OPEN,
    target_type: Annotated[ReportTargetType | None, Query()] = None,
    reason: Annotated[ReportReason | None, Query()] = None,
    assigned_to: Annotated[uuid.UUID | None, Query()] = None,
    min_priority: Annotated[int, Query(ge=0, le=100)] = 0,
    order: Annotated[str, Query(pattern="^(priority|recent)$")] = "priority",
) -> QueueResponse:
    enforce_rate_limit(request, "read")
    service = ModerationService(db)
    items, total = service.queue(
        status=status_filter,
        target_type=target_type,
        reason=reason,
        assigned_to=assigned_to,
        min_priority=min_priority,
        limit=params.limit,
        offset=params.offset,
        order=order,
    )
    total_pages = max(1, (total + params.page_size - 1) // params.page_size) if total else 0
    return QueueResponse(
        items=[CaseOut(**item) for item in items],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=total_pages,
        has_next=params.page * params.page_size < total,
        stats=service.stats(),
    )


@router.get("/stats", response_model=ModerationStats, summary="Moderation workload")
def stats(db: DbSession, user: StaffUser) -> ModerationStats:
    return ModerationStats(**ModerationService(db).stats())


@router.get(
    "/cases/{case_id}", response_model=CaseOut, summary="Case detail (with target snapshot)"
)
def case_detail(case_id: uuid.UUID, db: DbSession, user: StaffUser) -> CaseOut:
    return CaseOut(**ModerationService(db).case_detail(ModerationService(db).get_case(case_id)))


@router.post("/cases/{case_id}/assign", response_model=CaseOut, summary="Assign a case to yourself")
def assign(case_id: uuid.UUID, db: DbSession, user: StaffUser, request: Request) -> CaseOut:
    enforce_rate_limit(request, "write")
    service = ModerationService(db)
    case = service.assign(case_id=case_id, moderator_id=user.id)
    return CaseOut(**service.case_detail(case))


@router.post(
    "/cases/{case_id}/actions", response_model=CaseOut, summary="Record a moderation decision"
)
def apply_action(
    case_id: uuid.UUID,
    payload: ActionRequest,
    db: DbSession,
    user: StaffUser,
    request: Request,
    meta: Annotated[dict | None, Depends(client_metadata)] = None,  # type: ignore[assignment]
    session_id: Annotated[uuid.UUID | None, Depends(current_session_id)] = None,
) -> CaseOut:
    enforce_rate_limit(request, "write")
    if payload.action.value in {"remove", "restrict_author"} and not user.has_role("admin"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError(
            "Removing content or restricting an account requires an administrator.",
            details={"required_role": "admin", "your_roles": user.role_names},
        )
    result = ModerationService(db).apply_action(
        case_id=case_id,
        action=payload.action,
        reason=payload.reason,
        moderator_id=user.id,
        moderator_role=user.primary_role.value,
        target_type=payload.target_type,
        target_id=payload.target_id,
        restriction_hours=payload.restriction_hours,
        resolution_note=payload.resolution_note,
        actor_ip=(meta or {}).get("ip_address"),
        request_id=str(session_id) if session_id else None,
    )
    return CaseOut(**result)


@router.post(
    "/cases/{case_id}/correction", response_model=CaseOut, summary="Link a correction to a case"
)
def link_correction(
    case_id: uuid.UUID,
    payload: CorrectionRequest,
    db: DbSession,
    user: StaffUser,
    request: Request,
) -> CaseOut:
    enforce_rate_limit(request, "write")
    return CaseOut(
        **ModerationService(db).record_correction(
            case_id=case_id,
            corrected_target_type=payload.corrected_target_type,
            corrected_target_id=payload.corrected_target_id,
            note=payload.note,
            actor_id=user.id,
            actor_role=user.primary_role.value,
        )
    )


@router.post(
    "/cases/{case_id}/expert-review",
    response_model=CaseOut,
    summary="Route a case to the expert queue",
)
def request_expert_review(
    case_id: uuid.UUID,
    payload: ExpertReviewRequest,
    db: DbSession,
    user: StaffUser,
    request: Request,
) -> CaseOut:
    enforce_rate_limit(request, "write")
    return CaseOut(
        **ModerationService(db).request_expert_review(
            case_id=case_id, actor_id=user.id, note=payload.note
        )
    )


@router.get("/audit", response_model=list[AuditEntryOut], summary="Audit trail (admin only)")
def audit(
    db: DbSession,
    user: AdminUser,
    target_type: Annotated[str | None, Query(max_length=32)] = None,
    target_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEntryOut]:
    rows = ModerationService(db).audit_trail(
        target_type=target_type, target_id=target_id, limit=limit
    )
    return [
        AuditEntryOut(
            id=row.id,
            actor_id=row.actor_id,
            actor_role=row.actor_role,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            reason=row.reason,
            before=row.before,
            after=row.after,
            ip_address=row.ip_address,
            request_id=row.request_id,
            created_at=row.created_at,
        )
        for row in rows
    ]
