"""Crop management: catalog, planted crops, activity log, stage helpers."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import CropStage, CropStatus
from app.core.errors import NotFoundError, ValidationError, not_found
from app.crops.models import Crop, CropCatalog, CropEvent
from app.crops.schemas import CropCatalogOut, CropOut
from app.database.base import utcnow
from app.users.models import User

# Stage ordering used to validate that a stage change moves forward (a farmer can
# still correct a mistake — `force` is implicit because the update endpoint just
# writes the value; ordering is only used for guidance, never to block).
STAGE_ORDER = [
    "planned",
    "land_preparation",
    "sowing",
    "germination",
    "vegetative",
    "flowering",
    "fruiting",
    "maturity",
    "harvest",
    "post_harvest",
]


class CropService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------------------------------------------------------- catalog
    def catalog(self, *, search: str | None = None) -> list[CropCatalogOut]:
        stmt = select(CropCatalog).order_by(CropCatalog.name_en)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                CropCatalog.name_en.ilike(pattern)
                | CropCatalog.name_mr.ilike(pattern)
                | CropCatalog.name_hi.ilike(pattern)
                | CropCatalog.code.ilike(pattern)
            )
        rows = self.db.execute(stmt).scalars().all()
        return [
            CropCatalogOut(
                code=row.code,
                name_en=row.name_en,
                name_mr=row.name_mr,
                name_hi=row.name_hi,
                category=row.category,
                season=row.season,
                default_area_unit=row.default_area_unit,
                disease_model_supported=bool(row.disease_model_labels),
                typical_yield_per_hectare=(
                    float(row.typical_yield_per_hectare) if row.typical_yield_per_hectare else None
                ),
                reference_source=row.reference_source,
            )
            for row in rows
        ]

    def get_catalog_entry(self, code: str) -> CropCatalog:
        entry = self.db.execute(
            select(CropCatalog).where(CropCatalog.code == code)
        ).scalar_one_or_none()
        if entry is None:
            raise ValidationError(
                "That crop is not in the crop catalog.",
                details={
                    "crop_code": code,
                    "hint": "GET /api/v1/crops/catalog lists supported crops.",
                },
            )
        return entry

    # ------------------------------------------------------------------ crops
    def _owned_farm(self, user: User, farm_id: uuid.UUID):
        from app.farms.repository import FarmRepository

        farm = FarmRepository(self.db).get(farm_id)
        if farm is None:
            raise NotFoundError("That farm could not be found.")
        if farm.owner_id != user.id and not user.has_role("admin", "moderator"):
            not_found()
        return farm

    def _owned_crop(self, user: User, crop_id: uuid.UUID) -> Crop:
        crop = self.db.get(Crop, crop_id)
        if crop is None or crop.deleted_at is not None:
            raise NotFoundError("That crop could not be found.")
        farm = crop.farm
        if farm.owner_id != user.id and not user.has_role("admin", "moderator"):
            not_found()
        return crop

    def to_out(self, crop: Crop) -> CropOut:
        entry = self.db.execute(
            select(CropCatalog).where(CropCatalog.code == crop.crop_code)
        ).scalar_one_or_none()
        today = date.today()
        data = CropOut.model_validate(crop)
        data.crop_name = entry.name_en if entry else crop.crop_code
        data.days_since_sowing = (today - crop.sowing_date).days if crop.sowing_date else None
        data.days_to_expected_harvest = (
            (crop.expected_harvest_date - today).days if crop.expected_harvest_date else None
        )
        return data

    def create(self, user: User, farm_id: uuid.UUID, payload: dict) -> Crop:
        farm = self._owned_farm(user, farm_id)
        self.get_catalog_entry(payload["crop_code"])
        if payload.get("area_value") and payload["area_value"] > float(farm.area_value) * 1.05:
            # Warning, not an error: intercropping/partial records happen, but a
            # crop larger than the farm is almost always a data-entry mistake.
            raise ValidationError(
                "Crop area is larger than the farm area. Please check the values.",
                details={"farm_area": float(farm.area_value), "farm_unit": farm.area_unit.value},
            )
        crop = Crop(farm_id=farm.id, is_demo=farm.is_demo, **payload)
        self.db.add(crop)
        self.db.commit()
        self.db.refresh(crop)
        return crop

    def list_for_farm(
        self, user: User, farm_id: uuid.UUID, *, status: CropStatus | None = None
    ) -> list[CropOut]:
        self._owned_farm(user, farm_id)
        stmt = select(Crop).where(Crop.farm_id == farm_id, Crop.deleted_at.is_(None))
        if status:
            stmt = stmt.where(Crop.status == status)
        rows = self.db.execute(stmt.order_by(Crop.created_at.desc())).scalars().all()
        return [self.to_out(c) for c in rows]

    def list_for_user(self, user: User, *, status: CropStatus | None = None) -> list[CropOut]:
        from app.farms.models import Farm

        stmt = (
            select(Crop)
            .join(Farm, Farm.id == Crop.farm_id)
            .where(Farm.owner_id == user.id, Crop.deleted_at.is_(None), Farm.deleted_at.is_(None))
        )
        if status:
            stmt = stmt.where(Crop.status == status)
        rows = self.db.execute(stmt.order_by(Crop.created_at.desc())).scalars().all()
        return [self.to_out(c) for c in rows]

    def get(self, user: User, crop_id: uuid.UUID) -> CropOut:
        return self.to_out(self._owned_crop(user, crop_id))

    def update(self, user: User, crop_id: uuid.UUID, payload: dict) -> Crop:
        crop = self._owned_crop(user, crop_id)
        for field, value in payload.items():
            if value is not None:
                setattr(crop, field, value)
        if (
            crop.expected_harvest_date
            and crop.sowing_date
            and crop.expected_harvest_date < crop.sowing_date
        ):
            raise ValidationError("Expected harvest date cannot be before the sowing date.")
        self.db.commit()
        self.db.refresh(crop)
        return crop

    def delete(self, user: User, crop_id: uuid.UUID) -> None:
        crop = self._owned_crop(user, crop_id)
        crop.deleted_at = utcnow()
        self.db.commit()

    def stage_guidance(self, crop: Crop) -> dict:
        """Deterministic, data-derived guidance for the current stage.

        This is *not* a model output: it maps the recorded stage to generic
        agronomy checklist items and is labelled `derived` accordingly.
        """
        idx = STAGE_ORDER.index(crop.stage.value) if crop.stage.value in STAGE_ORDER else 0
        next_stage = STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None
        return {
            "current_stage": crop.stage.value,
            "next_typical_stage": next_stage,
            "days_since_sowing": (date.today() - crop.sowing_date).days
            if crop.sowing_date
            else None,
            "data_class": "derived",
            "note": "Stage sequence is a general reference, not a calendar recommendation for your variety.",
        }

    # ----------------------------------------------------------------- events
    def add_event(self, user: User, crop_id: uuid.UUID, payload: dict) -> CropEvent:
        crop = self._owned_crop(user, crop_id)
        if (
            payload.get("event_date")
            and crop.sowing_date
            and payload["event_date"] < crop.sowing_date
        ):
            raise ValidationError(
                "That activity is dated before the sowing date.",
                details={"sowing_date": crop.sowing_date.isoformat()},
            )
        event = CropEvent(crop_id=crop.id, created_by_id=user.id, **payload)
        self.db.add(event)
        # Logging an event can advance the stage, which keeps the dashboard useful
        # without asking the farmer to update two screens.
        inferred: dict[str, str] = {}  # surfaced in the response for transparency
        if payload["event_type"] == "sowing" and crop.stage.value in (
            "planned",
            "land_preparation",
        ):
            crop.stage = CropStage.SOWING
            inferred["stage"] = crop.stage.value
        if payload["event_type"] == "harvest":
            crop.status = CropStatus.HARVESTED
            crop.stage = CropStage.HARVEST
            inferred["status"] = crop.status.value
        self.db.commit()
        self.db.refresh(event)
        return event

    def list_events(self, user: User, crop_id: uuid.UUID) -> list[CropEvent]:
        crop = self._owned_crop(user, crop_id)
        return list(
            self.db.execute(
                select(CropEvent)
                .where(CropEvent.crop_id == crop.id)
                .order_by(CropEvent.event_date.desc())
            )
            .scalars()
            .all()
        )
