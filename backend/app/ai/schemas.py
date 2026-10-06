"""AI feature API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import AIRequestKind, FeedbackVerdict


class ModelCardSummary(BaseModel):
    name: str
    version: str
    display_name: str | None = None
    task: str | None = None
    framework: str | None = None
    stage: str
    is_active: bool = False
    installed_on_disk: bool = Field(
        description="Whether an artefact for this version exists under ML_MODELS_DIR (the registry alone is "
        "not enough to serve a model)."
    )
    metrics: dict[str, Any] = {}
    training_data: dict[str, Any] = {}
    trained_at: datetime | None = None
    mlflow_run_id: str | None = None
    notes: str | None = None
    model_card_url: str | None = None


class ModelsOverview(BaseModel):
    models: list[ModelCardSummary]
    artifacts_dir: str
    registry_note: str = (
        "A version is listed as installed only when its artefact directory contains a model file. Registry rows "
        "without artefacts are shown so operators can see what was trained where."
    )


class CropRecommendationRequest(BaseModel):
    nitrogen: float | None = Field(
        default=None, ge=0, le=200, description="Available soil nitrogen (kg/ha)"
    )
    phosphorus: float | None = Field(default=None, ge=0, le=200)
    potassium: float | None = Field(default=None, ge=0, le=250)
    temperature_c: float | None = Field(
        default=None, ge=-5, le=50, description="Mean temperature (°C)"
    )
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    ph: float | None = Field(default=None, ge=0, le=14)
    rainfall_mm: float | None = Field(
        default=None, ge=0, le=4000, description="Rainfall over the window (mm)"
    )
    soil_type: str | None = Field(
        default=None,
        max_length=40,
        description="Optional: used only to fill missing soil values from documented lookup defaults, which "
        "are then labelled as estimates in the response.",
    )
    top_k: int = Field(default=3, ge=1, le=10)
    farm_id: uuid.UUID | None = Field(
        default=None,
        description="Optional: read the latest soil test from your farm to fill soil values (reported in "
        "input_sources).",
    )
    season: str | None = Field(
        default=None, max_length=24, description="Recorded with the request for history."
    )

    @model_validator(mode="after")
    def _needs_something(self) -> CropRecommendationRequest:
        provided = [
            self.nitrogen,
            self.phosphorus,
            self.potassium,
            self.temperature_c,
            self.humidity_percent,
            self.ph,
            self.rainfall_mm,
        ]
        if all(value is None for value in provided) and self.farm_id is None:
            raise ValueError(
                "Provide at least one soil/climate value, or a farm_id whose soil test should be used."
            )
        return self


class RankedCrop(BaseModel):
    crop_code: str
    name_en: str
    name_mr: str | None = None
    name_hi: str | None = None
    rank: int
    score: float
    score_display: float
    typical_envelope: dict[str, list[float]] = {}
    envelope_note: str


class CropRecommendationResponse(BaseModel):
    data_class: Literal["model_output"] = "model_output"
    model_name: str
    model_version: str
    score_type: str
    score_type_note: str
    confidence_interpretation: str
    top_margin: float | None = None
    ranked: list[RankedCrop]
    inputs_used: dict[str, float]
    input_sources: dict[str, str] = Field(
        description="Where each value came from: provided | soil_test | soil_type_default | weather_average."
    )
    input_units: dict[str, str] = {}
    warnings: list[str] = []
    limitations: list[str] = []
    disclaimer: str
    is_demo_dataset: bool = False
    latency_ms: int
    request_id: uuid.UUID | None = None


class DiseaseDetectionRequest(BaseModel):
    media_id: uuid.UUID = Field(
        description="Media uploaded via /media; the image itself never enters the database."
    )
    crop_code: str | None = Field(default=None, max_length=48)
    farm_id: uuid.UUID | None = None
    plant_part: str | None = Field(
        default=None, max_length=40, description="leaf | stem | fruit | root …"
    )
    note: str | None = Field(default=None, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class DiseasePredictionOut(BaseModel):
    label: str
    score: float
    score_display: float
    rank: int


class DiseaseDetectionResponse(BaseModel):
    data_class: Literal["model_output"] = "model_output"
    model_name: str
    model_version: str
    predictions: list[DiseasePredictionOut] = []
    model_trained_classes: list[str] = []
    score_type: str | None = None
    confidence: float | None = None
    confidence_interpretation: str
    inconclusive: bool
    quality_gate_failed: bool = False
    image_quality: dict[str, Any]
    crop_coverage_note: str | None = None
    recommendation: str
    extra_context: list[str] = []
    related_knowledge: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Knowledge-base passages about the top label, with source links.",
    )
    similar_community_posts: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer: str
    latency_ms: int
    request_id: uuid.UUID | None = None


class YieldPredictionRequest(BaseModel):
    crop_code: str = Field(min_length=2, max_length=48)
    area_hectares: float = Field(gt=0, le=100)
    soil_ph: float | None = Field(default=None, ge=3.5, le=10)
    nitrogen: float | None = Field(default=None, ge=0, le=250)
    phosphorus: float | None = Field(default=None, ge=0, le=250)
    potassium: float | None = Field(default=None, ge=0, le=300)
    rainfall_mm: float | None = Field(default=None, ge=0, le=4000)
    temperature_mean_c: float | None = Field(default=None, ge=-5, le=50)
    irrigation_type: str | None = Field(default=None, max_length=24)
    farm_id: uuid.UUID | None = None


class YieldPredictionResponse(BaseModel):
    data_class: Literal["model_output"] = "model_output"
    model_name: str
    model_version: str
    crop_code: str
    unit: str
    estimate: float
    range: dict[str, float] | None = None
    range_basis: str
    inputs_used: dict[str, float]
    score_type: str
    confidence_interpretation: str
    limitations: list[str] = []
    disclaimer: str
    latency_ms: int | None = None
    request_id: uuid.UUID | None = None


class PriceEstimateRequest(BaseModel):
    crop_code: str = Field(min_length=2, max_length=48)
    market_code: str | None = Field(default=None, max_length=64)
    horizon_days: int = Field(default=3, ge=1, le=14)


class PriceEstimateResponse(BaseModel):
    data_class: Literal["model_output"] = "model_output"
    available: bool
    crop_code: str
    market_code: str | None = None
    horizon_days: int
    unit: str = "INR_per_quintal"
    points: list[dict[str, Any]] = []
    history: dict[str, Any] = {}
    model_name: str | None = None
    model_version: str | None = None
    confidence_interpretation: str
    reason: str | None = None
    disclaimer: str
    request_id: uuid.UUID | None = None


class RiskRequest(BaseModel):
    farm_id: uuid.UUID | None = None
    crop_id: uuid.UUID | None = None
    language: str = Field(default="en", pattern="^(en|mr|hi)$")


class RiskFlagOut(BaseModel):
    code: str
    level: Literal["low", "moderate", "high"]
    title: str
    detail: str
    triggered_by: dict[str, Any]
    suggested_action: str


class RiskResponse(BaseModel):
    data_class: Literal["derived"] = "derived"
    method: str
    method_note: str
    level: str
    score: int
    score_interpretation: str
    flags: list[RiskFlagOut] = []
    inputs_used: dict[str, Any] = {}
    missing_inputs: list[str] = []
    weather_provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider, retrieval time and demo flag of the weather data used.",
    )
    disclaimer: str


class FeedbackRequest(BaseModel):
    ai_request_id: uuid.UUID
    verdict: FeedbackVerdict
    comment: str | None = Field(default=None, max_length=1000)
    corrected_label: str | None = Field(default=None, max_length=160)
    correction_details: str | None = Field(default=None, max_length=1500)
    consent_to_train: bool = Field(
        default=False,
        description="Explicit opt-in. Feedback is never used for training without this flag and a human review.",
    )

    @model_validator(mode="after")
    def _correction_needs_details(self) -> FeedbackRequest:
        if self.verdict in {FeedbackVerdict.INCORRECT, FeedbackVerdict.REPORT} and not (
            self.correction_details or self.comment
        ):
            raise ValueError("Please describe what was wrong so a reviewer can act on it.")
        return self


class FeedbackResponse(BaseModel):
    status: str
    feedback_id: uuid.UUID
    message: str
    consent_to_train: bool
    review_note: str = (
        "Corrections are reviewed by a human before any use. They are never fed back into a model "
        "automatically."
    )


class PredictionHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: AIRequestKind
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    crop_code: str | None = None
    label: str | None = None
    score: float | None = None
    result: dict[str, Any] = {}
    model_name: str
    model_version: str
    is_demo: bool
    created_at: datetime


class HistoryResponse(BaseModel):
    items: list[PredictionHistoryItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    retention_note: str = "Your AI history is kept so you can review past results. You can delete individual entries at any time."


class AIHealth(BaseModel):
    llm: dict[str, Any]
    embeddings: dict[str, Any]
    vector_index: dict[str, Any]
    models: list[dict[str, Any]]
    rag: dict[str, Any]
    notes: list[str] = []


class FeedbackQueueItem(BaseModel):
    id: uuid.UUID
    model_name: str
    verdict: str
    comment: str | None = None
    corrected_label: str | None = None
    correction_details: str | None = None
    consent_to_train: bool
    used_in_training: bool
    reviewed_by_id: uuid.UUID | None = None
    created_at: datetime
    user_id: uuid.UUID | None = None


class FeedbackReviewRequest(BaseModel):
    used_in_training: bool | None = Field(
        default=None,
        description="Only an admin can set this, and only for feedback with consent_to_train=True and a "
        "completed review.",
    )
    note: str | None = Field(default=None, max_length=1000)


class FeedbackReviewResponse(BaseModel):
    feedback_id: uuid.UUID
    status: str
    reviewed_by_id: uuid.UUID
    used_in_training: bool
    message: str


class TrainingDataSummary(BaseModel):
    """What the platform would (and would not) use for training."""

    collected_labels: dict[str, int]
    reviewed_corrections: int
    pending_review: int
    consenting: int
    policy: list[str]


class SeasonPlanRequest(BaseModel):
    farm_id: uuid.UUID
    season: str = Field(max_length=24)
    include_risk: bool = True


class SeasonPlanResponse(BaseModel):
    data_class: Literal["derived"] = "derived"
    farm_id: uuid.UUID
    season: str
    steps: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    ai_outputs: list[dict[str, Any]]
    notices: list[str]
