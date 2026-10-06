"""Farm schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AreaUnit, IrrigationType, OwnershipType, SoilType


class FarmBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    area_value: float = Field(gt=0, le=100_000, description="Area in `area_unit`")
    area_unit: AreaUnit
    village: str | None = Field(default=None, max_length=120)
    taluka: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, pattern=r"^\d{4,10}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    soil_type: SoilType = SoilType.UNKNOWN
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    irrigation_type: IrrigationType = IrrigationType.RAINFED
    ownership_type: OwnershipType = OwnershipType.OWNED
    water_source_notes: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class FarmCreate(FarmBase):
    pass


class FarmUpdate(BaseModel):
    # PATCH bodies are strict: a mistyped field name used to be silently ignored
    # (HTTP 200, nothing changed), which makes client bugs invisible. Rejecting
    # unknown keys turns that into a 422 naming the offending field.
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    area_value: float | None = Field(default=None, gt=0, le=100_000)
    area_unit: AreaUnit | None = None
    village: str | None = Field(default=None, max_length=120)
    taluka: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    pincode: str | None = Field(default=None, pattern=r"^\d{4,10}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    soil_type: SoilType | None = None
    soil_ph: float | None = Field(default=None, ge=0, le=14)
    irrigation_type: IrrigationType | None = None
    ownership_type: OwnershipType | None = None
    water_source_notes: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class FarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    area_value: float
    area_unit: AreaUnit
    area_hectares: float
    village: str | None
    taluka: str | None
    district: str | None
    state: str | None
    pincode: str | None
    latitude: float | None
    longitude: float | None
    soil_type: SoilType
    soil_ph: float | None
    irrigation_type: IrrigationType
    ownership_type: OwnershipType
    water_source_notes: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    crop_count: int = 0
    active_crop_count: int = 0
    is_demo: bool = False
    area_unit_note: str | None = Field(
        default=None,
        description="Present when the selected unit is not standardised (e.g. bigha differs by state).",
    )


class SoilTestCreate(BaseModel):
    tested_on: date
    ph: float | None = Field(default=None, ge=0, le=14)
    nitrogen_kg_per_ha: float | None = Field(default=None, ge=0, le=1000)
    phosphorus_kg_per_ha: float | None = Field(default=None, ge=0, le=1000)
    potassium_kg_per_ha: float | None = Field(default=None, ge=0, le=1000)
    organic_carbon_percent: float | None = Field(default=None, ge=0, le=20)
    electrical_conductivity: float | None = Field(default=None, ge=0, le=50)
    lab_name: str | None = Field(default=None, max_length=160)
    report_media_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)


class SoilTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    tested_on: date
    ph: float | None
    nitrogen_kg_per_ha: float | None
    phosphorus_kg_per_ha: float | None
    potassium_kg_per_ha: float | None
    organic_carbon_percent: float | None
    electrical_conductivity: float | None
    lab_name: str | None
    report_media_id: uuid.UUID | None
    notes: str | None
    created_at: datetime


class FarmSummary(BaseModel):
    """Aggregated farm view for the 'My Farm' tab. Weather/market sections are
    filled by their own providers and carry their own provenance fields."""

    farm: FarmOut
    crops: list[dict]
    crop_stage_counts: dict[str, int]
    latest_soil_test: SoilTestOut | None
    ai_notes: list[str] = Field(
        default_factory=list,
        description="Plain-language observations derived only from recorded farm/crop data "
        "(no model inference is claimed here).",
    )
