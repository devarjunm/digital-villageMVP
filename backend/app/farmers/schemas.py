"""Farmer profile schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AreaUnit, CropStage, Language, SoilType


class FarmerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    village: str | None
    taluka: str | None
    district: str | None
    state: str | None
    pincode: str | None
    latitude: float | None
    longitude: float | None
    farming_experience_years: int | None
    primary_crops: list[str]
    interests: list[str]
    total_land_area: float | None
    total_land_unit: AreaUnit | None
    bio: str | None
    organisation: str | None
    is_public: bool
    preferred_language: Language
    profile_completeness: int = Field(
        description="0-100 score computed from filled fields; used by the app to nudge profile completion."
    )
    created_at: datetime
    updated_at: datetime


class FarmerProfileUpdate(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    village: str | None = Field(default=None, max_length=120)
    taluka: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, pattern=r"^\d{4,10}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    farming_experience_years: int | None = Field(default=None, ge=0, le=100)
    primary_crops: list[str] | None = Field(default=None, max_length=20)
    interests: list[str] | None = Field(default=None, max_length=20)
    total_land_area: float | None = Field(default=None, gt=0, le=100_000)
    total_land_unit: AreaUnit | None = None
    bio: str | None = Field(default=None, max_length=1000)
    organisation: str | None = Field(default=None, max_length=160)
    is_public: bool | None = None


class FarmContextSummary(BaseModel):
    """Compact farm context used by the AI assistant and recommendation engine."""

    farm_id: uuid.UUID
    name: str
    area_hectares: float
    area_display: str
    soil_type: SoilType
    soil_ph: float | None
    irrigation_type: str
    state: str | None
    district: str | None
    active_crops: list[dict]
    crop_stages: dict[str, int]


class FarmerDashboard(BaseModel):
    profile: FarmerProfileOut
    land_summary: dict
    crop_stage_counts: dict[str, int]
    active_crops: list[dict]
    reminders: list[str]
    data_freshness: dict[str, str | None] = Field(
        default_factory=dict,
        description="When each dashboard section last received real data (no fabricated 'live' claims).",
    )


class PublicFarmerProfile(BaseModel):
    """Privacy-preserving projection: no phone, email, exact coordinates or pincode."""

    id: uuid.UUID
    display_name: str
    village: str | None
    district: str | None
    state: str | None
    farming_experience_years: int | None
    primary_crops: list[str]
    interests: list[str]
    bio: str | None
    organisation: str | None
    is_expert: bool
    active_crop_stages: list[CropStage] = []
    member_since: datetime
