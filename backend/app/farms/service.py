"""Farm business logic (ownership checks, aggregation)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.enums import CropStatus
from app.core.errors import NotFoundError, ValidationError, not_found
from app.core.units import area_unit_note, to_hectares
from app.crops.models import Crop
from app.farms.models import Farm
from app.farms.repository import FarmRepository
from app.farms.schemas import FarmOut, FarmSummary, SoilTestOut
from app.users.models import User


class FarmService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = FarmRepository(db)

    def _owned(self, user: User, farm_id: uuid.UUID) -> Farm:
        farm = self.repo.get(farm_id)
        if farm is None:
            raise NotFoundError("That farm could not be found.")
        if farm.owner_id != user.id and not user.has_role("admin", "moderator"):
            not_found()
        return farm

    def to_out(self, farm: Farm) -> FarmOut:
        """Project a farm row into the API shape.

        `area_hectares`, `crop_count`, `active_crop_count` and `area_unit_note`
        are *derived* — they are not columns on `farms` — so they are computed
        here (and only here) rather than being expected from the ORM object.
        """
        crops = [c for c in farm.crops if c.deleted_at is None]
        return FarmOut(
            id=farm.id,
            name=farm.name,
            area_value=float(farm.area_value),
            area_unit=farm.area_unit,
            area_hectares=round(to_hectares(float(farm.area_value), farm.area_unit), 4),
            village=farm.village,
            taluka=farm.taluka,
            district=farm.district,
            state=farm.state,
            pincode=farm.pincode,
            latitude=float(farm.latitude) if farm.latitude is not None else None,
            longitude=float(farm.longitude) if farm.longitude is not None else None,
            soil_type=farm.soil_type,
            soil_ph=float(farm.soil_ph) if farm.soil_ph is not None else None,
            irrigation_type=farm.irrigation_type,
            ownership_type=farm.ownership_type,
            water_source_notes=farm.water_source_notes,
            notes=farm.notes,
            created_at=farm.created_at,
            updated_at=farm.updated_at,
            crop_count=len(crops),
            active_crop_count=sum(1 for c in crops if c.status == CropStatus.ACTIVE),
            is_demo=farm.is_demo,
            area_unit_note=area_unit_note(farm.area_unit),
        )

    def list(self, user: User) -> list[FarmOut]:
        return [self.to_out(f) for f in self.repo.list_for_owner(user.id)]

    def create(self, user: User, payload: dict) -> Farm:
        if payload.get("latitude") is None and payload.get("longitude") is None:
            # Fall back to the farmer's profile location so weather works out of
            # the box; still explicit, never invented.
            profile = user.profile
            if profile and profile.latitude is not None and profile.longitude is not None:
                payload["latitude"] = profile.latitude
                payload["longitude"] = profile.longitude
        farm = self.repo.create(owner_id=user.id, **payload)
        self.db.commit()
        self.db.refresh(farm)
        return farm

    def update(self, user: User, farm_id: uuid.UUID, payload: dict) -> Farm:
        farm = self._owned(user, farm_id)
        for field, value in payload.items():
            if value is not None:
                setattr(farm, field, value)
        self.db.commit()
        self.db.refresh(farm)
        return farm

    def delete(self, user: User, farm_id: uuid.UUID) -> None:
        farm = self._owned(user, farm_id)
        self.repo.soft_delete(farm)
        self.db.commit()

    def summary(self, user: User, farm_id: uuid.UUID) -> FarmSummary:
        farm = self._owned(user, farm_id)
        crops = [c for c in farm.crops if c.deleted_at is None]
        stage_counts: dict[str, int] = {}
        rows: list[dict] = []
        for crop in crops:
            stage_counts[crop.stage.value] = stage_counts.get(crop.stage.value, 0) + 1
            rows.append(self._crop_row(crop, farm))
        latest_soil = self.repo.latest_soil_test(farm.id)

        notes: list[str] = []
        if not crops:
            notes.append(
                "No crops recorded for this farm yet — add a crop to unlock stage-specific guidance."
            )
        if farm.soil_ph is None and latest_soil is None:
            notes.append(
                "Soil pH is unknown for this farm. Recording it (or uploading a soil test report) improves "
                "crop and fertiliser recommendations."
            )
        elif farm.soil_ph is not None and not (6.0 <= float(farm.soil_ph) <= 7.5):
            notes.append(
                f"Recorded soil pH is {float(farm.soil_ph):.1f}. Many field crops grow best between 6.0 and 7.5 — "
                "confirm with a soil test before amending."
            )
        if farm.irrigation_type and farm.irrigation_type.value == "rainfed":
            notes.append(
                "This farm is recorded as rainfed: weather forecasts matter more for irrigation planning."
            )
        if latest_soil is not None and latest_soil.tested_on:
            age_days = (date.today() - latest_soil.tested_on).days
            if age_days > 730:
                notes.append(f"The latest soil test is {age_days} days old; consider a fresh test.")

        return FarmSummary(
            farm=self.to_out(farm),
            crops=rows,
            crop_stage_counts=stage_counts,
            latest_soil_test=SoilTestOut.model_validate(latest_soil) if latest_soil else None,
            ai_notes=notes,
        )

    @staticmethod
    def _crop_row(crop: Crop, farm: Farm) -> dict:
        return {
            "crop_id": str(crop.id),
            "crop_code": crop.crop_code,
            "variety": crop.variety,
            "stage": crop.stage.value,
            "status": crop.status.value,
            "season": crop.season.value if crop.season else None,
            "sowing_date": crop.sowing_date.isoformat() if crop.sowing_date else None,
            "expected_harvest_date": crop.expected_harvest_date.isoformat()
            if crop.expected_harvest_date
            else None,
            "days_since_sowing": (date.today() - crop.sowing_date).days
            if crop.sowing_date
            else None,
            "area_value": float(crop.area_value) if crop.area_value else None,
            "area_unit": crop.area_unit.value if crop.area_unit else None,
            "irrigation_method": crop.irrigation_method.value if crop.irrigation_method else None,
            "event_count": len(list(crop.events)),
        }

    def add_soil_test(self, user: User, farm_id: uuid.UUID, payload: dict) -> SoilTestOut:
        farm = self._owned(user, farm_id)
        if payload.get("tested_on") and payload["tested_on"] > date.today():
            raise ValidationError("A soil test date cannot be in the future.")
        test = self.repo.add_soil_test(farm_id=farm.id, **payload)
        self.db.commit()
        self.db.refresh(test)
        return SoilTestOut.model_validate(test)
