"""Moderation workflow.

Guarantees enforced here:

  * every decision is a `ModerationAction` row with an actor (a human moderator or
    admin) and a written reason of at least 10 characters;
  * every decision also writes an `audit_logs` row, so the history of a piece of
    content — and of a moderator's decisions — is reconstructable;
  * content is only hidden/removed by a human action; signals never mutate content;
  * the author is notified (with the reason) unless the decision is `note`/`dismiss`;
  * "correction" is a first-class outcome: an expert/author can post a correction,
    which is recorded on the case so the community sees the claim was revised
    rather than silently deleted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    ContentStatus,
    ModerationActionType,
    NotificationType,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.logging import get_logger
from app.moderation.models import AuditLog, ModerationAction, ModerationCase, UserRestriction

logger = get_logger(__name__)

MIN_REASON_LENGTH = 10


class ModerationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------------- queue
    def queue(
        self,
        *,
        status: ReportStatus | None = ReportStatus.OPEN,
        target_type: ReportTargetType | None = None,
        reason: ReportReason | None = None,
        assigned_to: uuid.UUID | None = None,
        min_priority: int = 0,
        limit: int = 25,
        offset: int = 0,
        order: str = "priority",
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(ModerationCase)
        count_stmt = select(func.count()).select_from(ModerationCase)
        filters = []
        if status is not None:
            filters.append(ModerationCase.status == status)
        if target_type is not None:
            filters.append(ModerationCase.target_type == target_type)
        if reason is not None:
            filters.append(ModerationCase.reason == reason)
        if assigned_to is not None:
            filters.append(ModerationCase.assigned_to_id == assigned_to)
        if min_priority:
            filters.append(ModerationCase.priority >= min_priority)
        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)
        ordering = (
            (ModerationCase.priority.desc(), ModerationCase.created_at.asc())
            if order == "priority"
            else (ModerationCase.created_at.desc(),)
        )
        total = int(self.db.execute(count_stmt).scalar_one())
        rows = list(self.db.execute(stmt.order_by(*ordering).limit(limit).offset(offset)).scalars())
        return [self.case_detail(case, include_target=True) for case in rows], total

    def get_case(self, case_id: uuid.UUID) -> ModerationCase:
        case = self.db.get(ModerationCase, case_id)
        if case is None:
            raise NotFoundError("That moderation case could not be found.")
        return case

    def case_detail(self, case: ModerationCase, *, include_target: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": case.id,
            "target_type": case.target_type.value,
            "target_id": case.target_id,
            "author_id": case.author_id,
            "reason": case.reason.value,
            "status": case.status.value,
            "priority": case.priority,
            "signals": case.ai_signals or {},
            "assigned_to_id": case.assigned_to_id,
            "resolved_by_id": case.resolved_by_id,
            "resolved_at": case.resolved_at,
            "resolution_note": case.resolution_note,
            "created_at": case.created_at,
            "actions": [
                {
                    "id": action.id,
                    "action": action.action.value,
                    "moderator_id": action.moderator_id,
                    "reason": action.reason,
                    "restriction_hours": action.restriction_hours,
                    "notified_author": action.notified_author,
                    "created_at": action.created_at,
                }
                for action in case.actions
            ],
        }
        # Reporter reports for the same target, so a moderator sees the pattern.
        from app.community.models import Report

        reports = list(
            self.db.execute(
                select(Report).where(
                    Report.target_type == case.target_type, Report.target_id == case.target_id
                )
            ).scalars()
        )
        data["reports"] = [
            {
                "id": report.id,
                "reporter_id": report.reporter_id,
                "reason": report.reason.value,
                "details": report.details,
                "status": report.status.value,
                "created_at": report.created_at,
            }
            for report in reports
        ]
        if include_target:
            data["target_snapshot"] = self._snapshot(case.target_type, case.target_id)
        return data

    def _snapshot(
        self, target_type: ReportTargetType, target_id: uuid.UUID
    ) -> dict[str, Any] | None:
        if target_type == ReportTargetType.POST:
            from app.community.models import Post

            post = self.db.get(Post, target_id)
            if post is None:
                return None
            return {
                "kind": "post",
                "id": str(post.id),
                "title": post.title,
                "body": post.body[:2000],
                "author_id": str(post.author_id),
                "status": post.status.value,
                "trust_label": post.trust_label.value,
                "created_at": post.created_at.isoformat(),
                "report_count": post.report_count,
                "is_demo": post.is_demo,
            }
        if target_type == ReportTargetType.COMMENT:
            from app.community.models import Comment

            comment = self.db.get(Comment, target_id)
            if comment is None:
                return None
            return {
                "kind": "comment",
                "id": str(comment.id),
                "body": comment.body[:2000],
                "post_id": str(comment.post_id),
                "author_id": str(comment.author_id),
                "status": comment.status.value,
                "created_at": comment.created_at.isoformat(),
            }
        from app.users.models import User

        user = self.db.get(User, target_id)
        if user is None:
            return None
        profile = user.profile
        return {
            "kind": "user",
            "id": str(user.id),
            "display_name": (profile.display_name if profile else None) or user.full_name,
            "primary_role": user.primary_role.value,
            "roles": user.role_names,
            "is_demo": user.is_demo,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "restrictions": [
                {
                    "capability": restriction.capability,
                    "reason": restriction.reason,
                    "expires_at": restriction.expires_at.isoformat()
                    if restriction.expires_at
                    else None,
                }
                for restriction in user.restrictions
                if restriction.is_active()
            ]
            if hasattr(user, "restrictions")
            else [],
        }

    def assign(self, *, case_id: uuid.UUID, moderator_id: uuid.UUID) -> ModerationCase:
        case = self.get_case(case_id)
        case.assigned_to_id = moderator_id
        if case.status == ReportStatus.OPEN:
            case.status = ReportStatus.IN_REVIEW
        self.db.commit()
        self.db.refresh(case)
        return case

    # --------------------------------------------------------------- actions
    def apply_action(
        self,
        *,
        case_id: uuid.UUID,
        action: ModerationActionType,
        reason: str,
        moderator_id: uuid.UUID,
        moderator_role: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        restriction_hours: int | None = None,
        resolution_note: str | None = None,
        actor_ip: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if len((reason or "").strip()) < MIN_REASON_LENGTH:
            raise ValidationError(
                f"A written reason of at least {MIN_REASON_LENGTH} characters is required for every moderation action."
            )
        case = self.get_case(case_id)
        t_type = target_type or case.target_type.value
        t_id = target_id or case.target_id

        before = self._snapshot(case.target_type, case.target_id)
        notified = False
        if action in {
            ModerationActionType.HIDE,
            ModerationActionType.REMOVE,
            ModerationActionType.WARN_AUTHOR,
            ModerationActionType.RESTRICT_AUTHOR,
        }:
            notified = self._apply_content_effect(
                case=case,
                action=action,
                reason=reason,
                moderator_id=moderator_id,
                restriction_hours=restriction_hours,
            )

        record = ModerationAction(
            case_id=case.id,
            moderator_id=moderator_id,
            action=action,
            target_type=t_type,
            target_id=t_id,
            reason=reason.strip(),
            restriction_hours=restriction_hours,
            notified_author=notified,
        )
        self.db.add(record)
        self._resolve_case(
            case, action=action, moderator_id=moderator_id, note=resolution_note or reason
        )
        self._audit(
            actor_id=moderator_id,
            actor_role=moderator_role,
            action=f"moderation.{action.value}",
            target_type=t_type,
            target_id=t_id,
            before=before,
            after=self._snapshot(case.target_type, case.target_id),
            reason=reason.strip(),
            ip_address=actor_ip,
            request_id=request_id,
        )
        self.db.commit()
        self.db.refresh(case)
        return self.case_detail(case, include_target=True)

    def _apply_content_effect(
        self,
        *,
        case: ModerationCase,
        action: ModerationActionType,
        reason: str,
        moderator_id: uuid.UUID,
        restriction_hours: int | None,
    ) -> bool:
        from app.community.models import Comment, Post
        from app.notifications.service import NotificationService

        notifications = NotificationService(self.db)
        status_map = {
            ModerationActionType.HIDE: ContentStatus.HIDDEN,
            ModerationActionType.REMOVE: ContentStatus.REMOVED,
        }
        author_id = case.author_id
        message = ""

        if case.target_type == ReportTargetType.POST:
            post = self.db.get(Post, case.target_id)
            if post is not None:
                author_id = post.author_id
                if action in status_map:
                    post.status = status_map[action]
                message = f'Your post "{post.title[:60]}"'
        elif case.target_type == ReportTargetType.COMMENT:
            comment = self.db.get(Comment, case.target_id)
            if comment is not None:
                author_id = comment.author_id
                if action in status_map:
                    comment.status = status_map[action]
                message = "Your reply"
        elif case.target_type == ReportTargetType.USER:
            message = "Your account"

        if action == ModerationActionType.RESTRICT_AUTHOR and author_id is not None:
            self.db.add(
                UserRestriction(
                    user_id=author_id,
                    capability="post",
                    reason=reason.strip(),
                    created_by_id=moderator_id,
                    expires_at=(
                        datetime.now(UTC) + timedelta(hours=restriction_hours)
                        if restriction_hours
                        else None
                    ),
                )
            )
            message = message or "Your account"
        elif action == ModerationActionType.WARN_AUTHOR and author_id is not None:
            message = message or "Your content"

        if author_id is None:
            return False
        if not message:
            return False

        body = (
            f"{message} was reviewed by a moderator and marked '{action.value}'. "
            f"Reason: {reason.strip()}. "
            "If you believe this is wrong, reply to the moderation message with your evidence — an expert or "
            "moderator will review it again."
        )
        outcome = notifications.create(
            user_id=author_id,
            type=NotificationType.MODERATION_ACTION,
            title=f"Moderation: {action.value.replace('_', ' ')}",
            body=body[:600],
            subject_type=case.target_type.value,
            subject_id=case.target_id,
            deep_link=f"digitalvillage://moderation/cases/{case.id}",
            payload={"action": action.value, "case_id": str(case.id)},
        )
        return bool(outcome.get("created"))

    def _resolve_case(
        self,
        case: ModerationCase,
        *,
        action: ModerationActionType,
        moderator_id: uuid.UUID,
        note: str | None,
    ) -> None:
        case.resolved_by_id = moderator_id
        case.resolved_at = datetime.now(UTC)
        case.resolution_note = note
        if action == ModerationActionType.DISMISS:
            case.status = ReportStatus.DISMISSED
        elif action == ModerationActionType.NOTE:
            case.status = ReportStatus.IN_REVIEW
        else:
            case.status = ReportStatus.RESOLVED

        from app.community.models import Report

        for report in self.db.execute(
            select(Report).where(
                Report.target_type == case.target_type, Report.target_id == case.target_id
            )
        ).scalars():
            report.status = (
                ReportStatus.DISMISSED
                if action == ModerationActionType.DISMISS
                else ReportStatus.RESOLVED
            )
            report.resolved_by_id = moderator_id
            report.resolved_at = datetime.now(UTC)
            report.resolution_note = note

    # ------------------------------------------------------------ corrections
    def record_correction(
        self,
        *,
        case_id: uuid.UUID,
        corrected_target_type: ReportTargetType,
        corrected_target_id: uuid.UUID,
        note: str,
        actor_id: uuid.UUID,
        actor_role: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Link a correction (a corrected post/comment or an expert reply) to a case.

        Corrections are the preferred outcome for wrong-but-honest agricultural
        information: the claim stays visible with the correction attached, because
        deleting it would hide that the misconception exists.
        """
        if len((note or "").strip()) < MIN_REASON_LENGTH:
            raise ValidationError(
                f"Describe the correction in at least {MIN_REASON_LENGTH} characters."
            )
        case = self.get_case(case_id)
        record = ModerationAction(
            case_id=case.id,
            moderator_id=actor_id,
            action=ModerationActionType.NOTE,
            target_type=corrected_target_type.value,
            target_id=corrected_target_id,
            reason=f"Correction linked: {note.strip()}",
        )
        self.db.add(record)
        signals = dict(case.ai_signals or {})
        corrections = list(signals.get("corrections", []))
        corrections.append(
            {
                "target_type": corrected_target_type.value,
                "target_id": str(corrected_target_id),
                "note": note.strip(),
                "by": str(actor_id),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        signals["corrections"] = corrections
        case.ai_signals = signals
        self._audit(
            actor_id=actor_id,
            actor_role=actor_role,
            action="moderation.correction_linked",
            target_type=case.target_type.value,
            target_id=case.target_id,
            before=None,
            after={"corrected_target_id": str(corrected_target_id), "note": note.strip()},
            reason=note.strip(),
            request_id=request_id,
        )
        self.db.commit()
        return self.case_detail(case)

    def request_expert_review(
        self, *, case_id: uuid.UUID, actor_id: uuid.UUID, note: str
    ) -> dict[str, Any]:
        """Route a case to the expert queue (used for agronomy claims)."""
        if len((note or "").strip()) < MIN_REASON_LENGTH:
            raise ValidationError("Explain what the expert should check (at least 10 characters).")
        case = self.get_case(case_id)
        signals = dict(case.ai_signals or {})
        signals["expert_review_requested"] = {
            "by": str(actor_id),
            "note": note.strip(),
            "at": datetime.now(UTC).isoformat(),
        }
        case.ai_signals = signals
        case.priority = max(case.priority, 60)
        self._audit(
            actor_id=actor_id,
            actor_role="moderator",
            action="moderation.expert_review_requested",
            target_type=case.target_type.value,
            target_id=case.target_id,
            before=None,
            after={"note": note.strip()},
            reason=note.strip(),
        )
        self.db.commit()
        return self.case_detail(case)

    # -------------------------------------------------------------- audit log
    def _audit(
        self,
        *,
        actor_id: uuid.UUID | None,
        actor_role: str | None,
        action: str,
        target_type: str | None,
        target_id: uuid.UUID | None,
        before: dict | None,
        after: dict | None,
        reason: str | None,
        ip_address: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
                reason=reason,
                ip_address=ip_address,
                request_id=request_id,
            )
        )

    def audit_trail(
        self, *, target_type: str | None = None, target_id: uuid.UUID | None = None, limit: int = 50
    ) -> list[AuditLog]:
        stmt = select(AuditLog)
        if target_type:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id:
            stmt = stmt.where(AuditLog.target_id == target_id)
        return list(
            self.db.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit)).scalars()
        )

    # -------------------------------------------------------------- dashboard
    def stats(self) -> dict[str, Any]:
        def count(status: ReportStatus | None) -> int:
            stmt = select(func.count()).select_from(ModerationCase)
            if status is not None:
                stmt = stmt.where(ModerationCase.status == status)
            return int(self.db.execute(stmt).scalar_one())

        oldest_open = self.db.execute(
            select(ModerationCase.created_at)
            .where(ModerationCase.status == ReportStatus.OPEN)
            .order_by(ModerationCase.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        return {
            "open": count(ReportStatus.OPEN),
            "in_review": count(ReportStatus.IN_REVIEW),
            "resolved": count(ReportStatus.RESOLVED),
            "dismissed": count(ReportStatus.DISMISSED),
            "total": count(None),
            "high_priority_open": int(
                self.db.execute(
                    select(func.count())
                    .select_from(ModerationCase)
                    .where(
                        ModerationCase.status == ReportStatus.OPEN, ModerationCase.priority >= 55
                    )
                ).scalar_one()
            ),
            "oldest_open_at": oldest_open,
            "sla_note": (
                "Target: acknowledge high-priority cases (payment/scam signals) within 24 hours. "
                "No automated hiding happens in the meantime."
            ),
        }

    # ------------------------------------------------ restriction enforcement
    def active_restrictions(self, user_id: uuid.UUID, capability: str) -> list[UserRestriction]:
        """Restrictions currently in force for a capability ('post', 'comment', …).

        Leadership note: a restriction is *only* ever created as an action on a
        moderation case, so every restriction can be traced to a report, a stated
        reason and the moderator who decided it. Nothing in the platform applies
        an automatic, unattributable penalty.
        """
        stmt = select(UserRestriction).where(
            UserRestriction.user_id == user_id,
            UserRestriction.active.is_(True),
            UserRestriction.capability.in_([capability, "all"]),
        )
        return [row for row in self.db.execute(stmt).scalars() if row.is_active()]

    def assert_capability(self, user, capability: str) -> None:
        """Raise when the user is currently restricted from `capability`.

        Called by every write path that can be restricted. The message explains
        the outcome and the end time but never reveals which moderator acted.
        """
        restrictions = self.active_restrictions(user.id, capability)
        if not restrictions:
            return
        until = max((row.expires_at for row in restrictions if row.expires_at), default=None)
        raise PermissionDeniedError(
            f"Your account is temporarily restricted from {capability}ing. Reading the community and your "
            "moderation messages still works, and you can contact support if this looks wrong.",
            details={
                "capability": capability,
                "restricted_until": until.isoformat() if until else None,
                "reason": restrictions[0].reason,
            },
        )

    def check_post_permission(self, user) -> None:
        """Backwards-compatible alias used by older call sites."""
        self.assert_capability(user, "post")
