"""AI endpoints.

Shape of this router:

  * `/models` is the honest inventory: what was trained, what is installed on this
    deployment, and what is therefore servable right now.
  * feature endpoints return results with model name/version, score type,
    confidence interpretation, limitations and disclaimer — or HTTP 503 with
    installation instructions when the model is not installed. There is no
    "demo answer" fallback.
  * `/history` and `/feedback` make results reviewable by the farmer and correctable
    by experts, with training use gated on explicit consent and human review.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.ai.schemas import (
    AIHealth,
    CropRecommendationRequest,
    CropRecommendationResponse,
    DiseaseDetectionRequest,
    DiseaseDetectionResponse,
    FeedbackQueueItem,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackReviewRequest,
    FeedbackReviewResponse,
    HistoryResponse,
    ModelsOverview,
    PredictionHistoryItem,
    PriceEstimateRequest,
    PriceEstimateResponse,
    RiskRequest,
    RiskResponse,
    SeasonPlanRequest,
    SeasonPlanResponse,
    TrainingDataSummary,
    YieldPredictionRequest,
    YieldPredictionResponse,
)
from app.ai.service import AIService
from app.auth.dependencies import AdminUser, CurrentUser, DbSession, StaffUser
from app.core.enums import AIRequestKind, FeedbackVerdict
from app.core.pagination import PageParams, page_params
from app.core.ratelimit import enforce_rate_limit

router = APIRouter()

PageDep = Annotated[PageParams, Depends(page_params)]


def _history_item(row) -> PredictionHistoryItem:
    return PredictionHistoryItem(
        id=row.id,
        kind=row.kind,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        crop_code=row.crop_code,
        label=row.label,
        score=float(row.score) if row.score is not None else None,
        result=row.result or {},
        model_name=row.model_name,
        model_version=row.model_version,
        is_demo=row.is_demo,
        created_at=row.created_at,
    )


@router.get("/models", response_model=ModelsOverview, summary="Installed and registered models")
def models(db: DbSession, user: CurrentUser) -> ModelsOverview:
    return ModelsOverview(**AIService(db).models_overview())


@router.get(
    "/health", response_model=AIHealth, summary="AI subsystem health (providers, index, models)"
)
def health(db: DbSession, user: StaffUser) -> AIHealth:
    return AIHealth(**AIService(db).health())


@router.post(
    "/crop-recommendation",
    response_model=CropRecommendationResponse,
    summary="Crop suitability ranking (AI-assisted)",
)
def crop_recommendation(
    payload: CropRecommendationRequest, db: DbSession, user: CurrentUser, request: Request
) -> CropRecommendationResponse:
    enforce_rate_limit(request, "ai")
    return CropRecommendationResponse(
        **AIService(db).crop_recommendation(user=user, payload=payload)
    )


@router.post(
    "/disease-detection",
    response_model=DiseaseDetectionResponse,
    summary="Disease/pest observation from a photo (AI-assisted, not a diagnosis)",
)
def disease_detection(
    payload: DiseaseDetectionRequest, db: DbSession, user: CurrentUser, request: Request
) -> DiseaseDetectionResponse:
    enforce_rate_limit(request, "ai")
    return DiseaseDetectionResponse(**AIService(db).disease_detection(user=user, payload=payload))


@router.post(
    "/yield-prediction",
    response_model=YieldPredictionResponse,
    summary="Yield estimate (AI-assisted)",
)
def yield_prediction(
    payload: YieldPredictionRequest, db: DbSession, user: CurrentUser, request: Request
) -> YieldPredictionResponse:
    enforce_rate_limit(request, "ai")
    return YieldPredictionResponse(**AIService(db).yield_prediction(user=user, payload=payload))


@router.post(
    "/price-estimate",
    response_model=PriceEstimateResponse,
    summary="Forward price estimate (reports 'not installed' honestly when unavailable)",
)
def price_estimate(
    payload: PriceEstimateRequest, db: DbSession, user: CurrentUser, request: Request
) -> PriceEstimateResponse:
    enforce_rate_limit(request, "ai")
    return PriceEstimateResponse(**AIService(db).price_estimate(user=user, payload=payload))


@router.post(
    "/risk-assessment",
    response_model=RiskResponse,
    summary="Rule-based risk screening for a farm/crop (not a model)",
)
def risk_assessment(
    payload: RiskRequest, db: DbSession, user: CurrentUser, request: Request
) -> RiskResponse:
    enforce_rate_limit(request, "ai")
    return RiskResponse(**AIService(db).risk_assessment(user=user, payload=payload))


@router.post(
    "/season-plan",
    response_model=SeasonPlanResponse,
    summary="Assemble a season plan from schemes, knowledge and risk screening",
)
def season_plan(
    payload: SeasonPlanRequest, db: DbSession, user: CurrentUser, request: Request
) -> SeasonPlanResponse:
    enforce_rate_limit(request, "ai")
    return SeasonPlanResponse(**AIService(db).season_plan(user=user, payload=payload))


@router.get("/history", response_model=HistoryResponse, summary="Your AI result history")
def history(
    db: DbSession,
    user: CurrentUser,
    params: PageDep,
    kind: Annotated[AIRequestKind | None, Query()] = None,
) -> HistoryResponse:
    rows, total = AIService(db).history(
        user=user, kind=kind, limit=params.limit, offset=params.offset
    )
    total_pages = max(1, (total + params.page_size - 1) // params.page_size) if total else 0
    return HistoryResponse(
        items=[_history_item(row) for row in rows],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=total_pages,
        has_next=params.page * params.page_size < total,
    )


@router.delete(
    "/history/{prediction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete one of your AI history entries",
)
def delete_history(prediction_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    AIService(db).delete_history_item(user=user, prediction_id=prediction_id)


@router.get(
    "/requests/{request_id}", summary="Full record of one AI request (input, output, evidence)"
)
def request_record(request_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    return AIService(db).output_for(user=user, request_id=request_id)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Correct or rate an AI result",
)
def feedback(
    payload: FeedbackRequest, db: DbSession, user: CurrentUser, request: Request
) -> FeedbackResponse:
    enforce_rate_limit(request, "write")
    body, _row = AIService(db).submit_feedback(user=user, payload=payload)
    return FeedbackResponse(**body)


@router.get(
    "/feedback/queue",
    response_model=list[FeedbackQueueItem],
    summary="Corrections awaiting review (staff)",
)
def feedback_queue(
    db: DbSession,
    user: StaffUser,
    params: PageDep,
    verdict: Annotated[FeedbackVerdict | None, Query()] = None,
) -> list[FeedbackQueueItem]:
    rows, _total = AIService(db).feedback_queue(
        verdict=verdict, limit=params.limit, offset=params.offset
    )
    return [
        FeedbackQueueItem(
            id=row.id,
            model_name=(
                row.ai_output.model_name
                if getattr(row, "ai_output", None) is not None
                else "unknown"
            ),
            verdict=row.verdict.value,
            comment=row.comment,
            corrected_label=row.corrected_label,
            correction_details=row.correction_details,
            consent_to_train=row.consent_to_train,
            used_in_training=row.used_in_training,
            reviewed_by_id=row.reviewed_by_id,
            created_at=row.created_at,
            user_id=row.user_id,
        )
        for row in rows
    ]


@router.post(
    "/feedback/{feedback_id}/review",
    response_model=FeedbackReviewResponse,
    summary="Record a review decision on feedback (admin)",
)
def review_feedback(
    feedback_id: uuid.UUID,
    payload: FeedbackReviewRequest,
    db: DbSession,
    user: AdminUser,
    request: Request,
) -> FeedbackReviewResponse:
    enforce_rate_limit(request, "write")
    result = AIService(db).review_feedback(
        feedback_id=feedback_id,
        reviewer=user,
        used_in_training=payload.used_in_training,
        note=payload.note,
    )
    return FeedbackReviewResponse(**result)


@router.get(
    "/training-data",
    response_model=TrainingDataSummary,
    summary="What could be used for training (consent + review status)",
)
def training_data(db: DbSession, user: AdminUser) -> TrainingDataSummary:
    return TrainingDataSummary(**AIService(db).training_data_summary())
