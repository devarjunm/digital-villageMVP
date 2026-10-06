"""Government scheme endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.analytics.service import AnalyticsService
from app.auth.dependencies import CurrentUser, DbSession, OptionalUser
from app.core.i18n import resolve_language
from app.core.pagination import PageParams, page_params, paginate
from app.core.ratelimit import enforce_rate_limit
from app.schemes.schemas import (
    EligibilityCheckOut,
    EligibilityFactorIn,
    SchemeListOut,
    SchemeOut,
    SchemeRecommendationsOut,
)
from app.schemes.service import SchemeService

router = APIRouter()


@router.get("", response_model=SchemeListOut, summary="Browse government schemes")
def list_schemes(
    db: DbSession,
    request: Request,
    params: Annotated[PageParams, Depends(page_params)],
    state: Annotated[str | None, Query(max_length=120)] = None,
    category: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    language: Annotated[str | None, Query(max_length=8)] = None,
    include_demo: bool = True,
) -> SchemeListOut:
    enforce_rate_limit(request, "read")
    lang = resolve_language(language, request.headers.get("accept-language"))
    items, total = SchemeService(db).list(
        state=state,
        category=category,
        query=q,
        language=lang,
        include_demo=include_demo,
        limit=params.limit,
        offset=params.offset,
    )
    return SchemeListOut(**paginate([i.model_dump(mode="json") for i in items], params, total))


@router.get("/categories", response_model=list[str], summary="Scheme categories")
def categories(db: DbSession) -> list[str]:
    return SchemeService(db).categories()


@router.get(
    "/recommended",
    response_model=SchemeRecommendationsOut,
    summary="Deterministic scheme recommendations",
)
def recommended(
    db: DbSession,
    request: Request,
    user: CurrentUser,
    state: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> SchemeRecommendationsOut:
    enforce_rate_limit(request, "read")
    items, evaluated = SchemeService(db).recommend(user=user, state=state, limit=limit)
    return SchemeRecommendationsOut(
        items=items,
        evaluated_schemes=evaluated,
        note=(
            "Ranking is a deterministic function of your recorded farm/profile data versus each scheme's "
            "published conditions. It is not an approval and not a probability."
        ),
    )


@router.get("/{slug}", response_model=SchemeOut, summary="Scheme detail")
def get_scheme(
    slug: str,
    db: DbSession,
    request: Request,
    viewer: OptionalUser,
    language: Annotated[str | None, Query(max_length=8)] = None,
) -> SchemeOut:
    enforce_rate_limit(request, "read")
    lang = resolve_language(language, request.headers.get("accept-language"))
    scheme = SchemeService(db).get_by_slug(slug, language=lang)
    AnalyticsService(db).record_event(
        name="scheme_viewed",
        user_id=viewer.id if viewer else None,
        props={"scheme_slug": slug, "state": (scheme.state_codes or [None])[0]},
        is_demo=scheme.is_demo,
    )
    return SchemeService(db).to_out(scheme, language=lang)


@router.post(
    "/{slug}/eligibility-check",
    response_model=EligibilityCheckOut,
    summary="Rule-based eligibility screening",
)
def eligibility_check(
    slug: str, payload: EligibilityFactorIn, user: CurrentUser, db: DbSession, request: Request
) -> EligibilityCheckOut:
    enforce_rate_limit(request, "read")
    result = SchemeService(db).check(
        slug=slug, user=user, extra=payload.model_dump(exclude_unset=True)
    )
    return EligibilityCheckOut(
        scheme_slug=result.scheme_slug,
        scheme_name=result.scheme_name,
        status=result.status,
        confidence=result.confidence,
        passed=[asdict(o) for o in result.passed],
        failed=[asdict(o) for o in result.failed],
        unknown=[asdict(o) for o in result.unknown],
        missing_inputs=result.missing_inputs,
        configuration_warnings=result.configuration_warnings,
        explanation=result.explanation,
        official_source_name=result.official_source_name,
        official_source_url=result.official_source_url,
        last_verified_on=result.last_verified_on,
        verification_status=result.verification_status,
        disclaimer=result.disclaimer,
    )
