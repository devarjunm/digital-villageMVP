"""Scheme catalogue, deterministic recommendations and eligibility checks."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.database.base import array_contains
from app.schemes.eligibility import EligibilityResult, FarmerContext, build_context, evaluate
from app.schemes.models import Scheme
from app.schemes.schemas import RecommendationItem, SchemeOut
from app.users.models import User

logger = get_logger(__name__)

DEMO_CONTENT_NOTICE = (
    "DEVELOPMENT PLACEHOLDER: this record ships for demonstration. The scheme name and official link point to "
    "the real programme, but the summary text has not been verified against the latest government notification "
    "and must be replaced (or verified by a moderator) before production use."
)
LANGUAGE_FIELDS = {
    "mr": (
        "name_mr",
        "description_mr",
        "benefits_mr",
        "eligibility_summary_mr",
        "application_process_mr",
    ),
    "hi": (
        "name_hi",
        "description_hi",
        "benefits_hi",
        "eligibility_summary_hi",
        "application_process_hi",
    ),
    "en": (
        "name_en",
        "description_en",
        "benefits_en",
        "eligibility_summary_en",
        "application_process_en",
    ),
}


class SchemeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ read
    def to_out(self, scheme: Scheme, *, language: str = "en") -> SchemeOut:
        name_field, desc_field, benefits_field, eligibility_field, process_field = (
            LANGUAGE_FIELDS.get(language, LANGUAGE_FIELDS["en"])
        )
        name = getattr(scheme, name_field) or scheme.name_en
        description = getattr(scheme, desc_field) or scheme.description_en
        benefits = getattr(scheme, benefits_field) or scheme.benefits_en
        eligibility = getattr(scheme, eligibility_field) or scheme.eligibility_summary_en
        process = getattr(scheme, process_field) or scheme.application_process_en
        localized_notice = None
        if language != "en" and getattr(scheme, name_field) is None:
            localized_notice = f"The {language} translation of this scheme is not available yet; the English text is shown."
        return SchemeOut(
            id=scheme.id,
            slug=scheme.slug,
            name=name,
            description=description,
            benefits=benefits,
            eligibility_summary=eligibility,
            application_process=process,
            documents_required=scheme.documents_required or [],
            category=scheme.category,
            level=scheme.level,
            state_codes=scheme.state_codes or [],
            crop_codes=scheme.crop_codes or [],
            official_source_name=scheme.official_source_name,
            official_source_url=scheme.official_source_url,
            application_url=scheme.application_url,
            helpline=scheme.helpline,
            last_verified_on=scheme.last_verified_on,
            verification_status=scheme.verification_status,
            is_demo=scheme.is_demo,
            content_notice=(DEMO_CONTENT_NOTICE if scheme.is_demo else None) or localized_notice,
            updated_at=scheme.updated_at,
        )

    def list(
        self,
        *,
        state: str | None = None,
        category: str | None = None,
        query: str | None = None,
        language: str = "en",
        include_demo: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SchemeOut], int]:
        stmt = select(Scheme).where(Scheme.deleted_at.is_(None))
        if not include_demo:
            stmt = stmt.where(Scheme.is_demo.is_(False))
        if state:
            stmt = stmt.where(
                or_(Scheme.level == "central", array_contains(Scheme.state_codes, [state]))
            )
        if category:
            stmt = stmt.where(Scheme.category == category)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Scheme.name_en.ilike(pattern),
                    Scheme.name_mr.ilike(pattern),
                    Scheme.name_hi.ilike(pattern),
                    Scheme.description_en.ilike(pattern),
                )
            )
        total = len(self.db.execute(stmt).scalars().all())
        rows = (
            self.db.execute(
                stmt.options(selectinload(Scheme.eligibility_rules))
                .order_by(Scheme.level, Scheme.name_en)
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [self.to_out(row, language=language) for row in rows], total

    def get_by_slug(self, slug: str, *, language: str = "en") -> Scheme:
        scheme = self.db.execute(
            select(Scheme)
            .options(selectinload(Scheme.eligibility_rules))
            .where(Scheme.slug == slug, Scheme.deleted_at.is_(None))
        ).scalar_one_or_none()
        if scheme is None:
            raise NotFoundError("That scheme could not be found.")
        return scheme

    def categories(self) -> list[str]:
        rows = (
            self.db.execute(
                select(Scheme.category)
                .where(Scheme.deleted_at.is_(None))
                .distinct()
                .order_by(Scheme.category)
            )
            .scalars()
            .all()
        )
        return list(rows)

    # ------------------------------------------------------------ eligibility
    def context_for(self, user: User, extra: dict | None = None) -> FarmerContext:
        from app.farms.repository import FarmRepository

        farms = FarmRepository(self.db).list_for_owner(user.id)
        return build_context(farms=farms, profile=user.profile, extra=extra)

    def check(self, *, slug: str, user: User, extra: dict | None = None) -> EligibilityResult:
        scheme = self.get_by_slug(slug)
        context = self.context_for(user, extra)
        return evaluate(scheme, context)

    def recommend(
        self, *, user: User, state: str | None = None, extra: dict | None = None, limit: int = 10
    ) -> tuple[list[RecommendationItem], int]:
        """Deterministic ranking over rule outcomes.

        Score (documented, not a probability):
          100 × (passed_rules / total_rules) − 25 × (hard failures) − 10 × (missing hard inputs),
        ties broken by "central before state" then alphabetical order.
        """
        context = self.context_for(user, extra)
        stmt = (
            select(Scheme)
            .options(selectinload(Scheme.eligibility_rules))
            .where(Scheme.deleted_at.is_(None))
        )
        if state:
            stmt = stmt.where(
                or_(Scheme.level == "central", array_contains(Scheme.state_codes, [state]))
            )
        elif context.state:
            stmt = stmt.where(
                or_(Scheme.level == "central", array_contains(Scheme.state_codes, [context.state]))
            )
        schemes = self.db.execute(stmt).scalars().all()

        items: list[RecommendationItem] = []
        for scheme in schemes:
            if not scheme.eligibility_rules:
                continue
            result = evaluate(scheme, context)
            total_rules = max(1, len(result.passed) + len(result.failed) + len(result.unknown))
            hard_failures = len([o for o in result.failed if o.is_hard_requirement])
            missing_hard = len(result.missing_inputs)
            score = 100 * len(result.passed) / total_rules - 25 * hard_failures - 10 * missing_hard
            reasons: list[str] = []
            if result.passed:
                reasons.append(f"Meets {len(result.passed)} of {total_rules} recorded conditions.")
            if hard_failures:
                reasons.append(f"{hard_failures} required condition(s) are not met.")
            if missing_hard:
                reasons.append(f"Needs more information: {', '.join(result.missing_inputs[:3])}.")
            if not reasons:
                reasons.append(
                    "No eligibility rules are defined for this scheme yet; check the official source."
                )
            items.append(
                RecommendationItem(
                    scheme=self.to_out(scheme, language=user.preferred_language.value),
                    match_score=int(max(0, min(100, round(score)))),
                    status=result.status,
                    reasons=reasons,
                    missing_inputs=result.missing_inputs,
                )
            )
        items.sort(
            key=lambda i: (-i.match_score, 0 if i.scheme.level == "central" else 1, i.scheme.name)
        )
        return items[:limit], len(schemes)

    # ------------------------------------------------------------------- admin
    def upsert(self, *, actor_id: uuid.UUID, payload: dict, slug: str | None = None) -> Scheme:
        rules = payload.pop("eligibility_rules", None)
        if slug:
            scheme = self.get_by_slug(slug)
        else:
            scheme = Scheme(slug=payload.pop("slug"), **payload)
            self.db.add(scheme)
            self.db.flush()
            self.db.commit()
            self.db.refresh(scheme)
            return scheme
        for field, value in payload.items():
            if value is not None:
                setattr(scheme, field, value)
        if rules is not None:
            scheme.eligibility_rules.clear()
            self.db.flush()
            from app.schemes.models import SchemeEligibilityRule

            for rule in rules:
                scheme.eligibility_rules.append(SchemeEligibilityRule(**rule))
        self.db.commit()
        self.db.refresh(scheme)
        return scheme
