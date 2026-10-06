"""Scheme API contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import VerificationStatus


class SchemeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    benefits: str | None = None
    eligibility_summary: str | None = None
    application_process: str | None = None
    documents_required: list[str] = []
    category: str
    level: str
    state_codes: list[str] = []
    crop_codes: list[str] = []
    official_source_name: str
    official_source_url: str
    application_url: str | None = None
    helpline: str | None = None
    last_verified_on: date | None = None
    verification_status: VerificationStatus
    is_demo: bool
    content_notice: str | None = Field(
        default=None,
        description="Present when the record is a development placeholder that must be verified before use.",
    )
    updated_at: datetime


class SchemeListOut(BaseModel):
    items: list[SchemeOut]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool


class RuleOutcomeOut(BaseModel):
    field: str
    operator: str
    required_value: object = None
    actual_value: object = None
    status: str
    is_hard_requirement: bool
    explanation: str
    source_reference: str | None = None


class EligibilityCheckOut(BaseModel):
    scheme_slug: str
    scheme_name: str
    status: str
    confidence: str
    passed: list[RuleOutcomeOut]
    failed: list[RuleOutcomeOut]
    unknown: list[RuleOutcomeOut]
    missing_inputs: list[str]
    configuration_warnings: list[str] = Field(
        default_factory=list,
        description="Scheme rules that could not be evaluated because their stored value is unusable. "
        "Reported to staff for correction; never counted as a failed requirement.",
    )
    explanation: str
    official_source_name: str
    official_source_url: str
    last_verified_on: date | None
    verification_status: str
    disclaimer: str
    data_class: str = "derived"


class EligibilityFactorIn(BaseModel):
    """Optional extra inputs (self-reported). Never inferred silently."""

    has_kcc: bool | None = None
    age_years: int | None = Field(default=None, ge=15, le=110)
    annual_income_inr: float | None = Field(default=None, ge=0, le=100_000_000)
    is_tenant_farmer: bool | None = None
    category_caste: str | None = Field(default=None, max_length=40)


class RecommendationItem(BaseModel):
    scheme: SchemeOut
    match_score: int = Field(
        ge=0, le=100, description="Deterministic score from rule outcomes, not a probability."
    )
    status: str
    reasons: list[str]
    missing_inputs: list[str]


class SchemeRecommendationsOut(BaseModel):
    items: list[RecommendationItem]
    evaluated_schemes: int
    note: str
    data_class: str = "derived"
