"""Crop schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AreaUnit,
    CropEventType,
    CropStage,
    CropStatus,
    IrrigationType,
    Season,
)


class CropCatalogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_mr: str | None
    name_hi: str | None
    category: str | None
    season: Season
    default_area_unit: AreaUnit
    disease_model_supported: bool = Field(
        description="True when the shipped crop-disease model was trained on classes for this crop."
    )
    typical_yield_per_hectare: float | None = Field(
        default=None,
        description="Reference figure with its source recorded; not a prediction.",
    )
    reference_source: str | None = None


class CropCreate(BaseModel):
    crop_code: str = Field(min_length=2, max_length=48)
    variety: str | None = Field(default=None, max_length=120)
    season: Season = Season.ANY
    sowing_date: date | None = None
    expected_harvest_date: date | None = None
    area_value: float | None = Field(default=None, gt=0, le=100_000)
    area_unit: AreaUnit = AreaUnit.ACRE
    stage: CropStage = CropStage.PLANNED
    irrigation_method: IrrigationType | None = None
    seed_source: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _dates_consistent(self) -> CropCreate:
        if (
            self.sowing_date
            and self.expected_harvest_date
            and self.expected_harvest_date < self.sowing_date
        ):
            raise ValueError("Expected harvest date cannot be before the sowing date.")
        if self.sowing_date and self.sowing_date > date.today():
            raise ValueError("Sowing date cannot be in the future.")
        return self


class CropUpdate(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    variety: str | None = Field(default=None, max_length=120)
    season: Season | None = None
    sowing_date: date | None = None
    expected_harvest_date: date | None = None
    area_value: float | None = Field(default=None, gt=0, le=100_000)
    area_unit: AreaUnit | None = None
    stage: CropStage | None = None
    status: CropStatus | None = None
    irrigation_method: IrrigationType | None = None
    seed_source: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)


class CropEventCreate(BaseModel):
    event_type: CropEventType
    event_date: date
    notes: str | None = Field(default=None, max_length=1000)
    quantity: float | None = Field(default=None, ge=0, le=1_000_000)
    unit: str | None = Field(default=None, max_length=32)
    cost: float | None = Field(default=None, ge=0, le=10_000_000)

    @model_validator(mode="after")
    def _not_future(self) -> CropEventCreate:
        if self.event_date > date.today():
            raise ValueError("Crop events cannot be dated in the future.")
        return self


class CropEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    crop_id: uuid.UUID
    event_type: CropEventType
    event_date: date
    notes: str | None
    quantity: float | None
    unit: str | None
    cost: float | None
    created_at: datetime


class CropOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    crop_code: str
    crop_name: str | None = None
    variety: str | None
    season: Season
    sowing_date: date | None
    expected_harvest_date: date | None
    area_value: float | None
    area_unit: AreaUnit
    stage: CropStage
    status: CropStatus
    irrigation_method: IrrigationType | None
    seed_source: str | None
    notes: str | None
    days_since_sowing: int | None = None
    days_to_expected_harvest: int | None = None
    events: list[CropEventOut] = []
    created_at: datetime
    updated_at: datetime
    is_demo: bool = False
