"""Farmer profile logic: profile management, completeness scoring, privacy
projection and the dashboard aggregation used by the Home tab."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import CropStage, CropStatus, Language
from app.core.errors import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.units import from_hectares, to_hectares
from app.crops.models import Crop, CropCatalog
from app.farmers.models import FarmerProfile
from app.farmers.repository import FarmerRepository
from app.farmers.schemas import (
    FarmerDashboard,
    FarmerProfileOut,
    PublicFarmerProfile,
)
from app.farms.models import Farm
from app.farms.repository import FarmRepository
from app.users.models import User

logger = get_logger(__name__)

PROFILE_FIELDS_WEIGHTED = {
    "display_name": 10,
    "village": 10,
    "district": 10,
    "state": 10,
    "pincode": 5,
    "farming_experience_years": 10,
    "primary_crops": 15,
    "interests": 5,
    "total_land_area": 10,
    "bio": 5,
    "location": 10,  # latitude + longitude
}


def completeness(profile: FarmerProfile) -> int:
    score = 0
    for field, weight in PROFILE_FIELDS_WEIGHTED.items():
        if field == "location":
            if profile.latitude is not None and profile.longitude is not None:
                score += weight
            continue
        value = getattr(profile, field, None)
        if value not in (None, "", []):
            score += weight
    return min(100, score)


class FarmerService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = FarmerRepository(db)
        self.farms = FarmRepository(db)

    # ------------------------------------------------------------- profile
    def get_or_create(self, user: User) -> FarmerProfile:
        profile = self.repo.get_by_user(user.id)
        if profile is None:
            profile = self.repo.create(
                user_id=user.id,
                display_name=user.full_name,
                primary_crops=[],
                interests=[],
                state=None,
            )
            self.db.commit()
            self.db.refresh(profile)
        return profile

    def to_out(self, profile: FarmerProfile) -> FarmerProfileOut:
        """Single-pass conversion: computed fields are supplied *to* validation.

        `FarmerProfileOut.preferred_language` and `.profile_completeness` are required
        fields that live on the user and in a computation rather than on the profile
        row. A previous version validated the ORM object first and patched them
        afterwards, so validation raised before the patch could run and every call to
        `GET /api/v1/farmers/me` (and the dashboard that uses it) returned 500.
        """
        language = profile.user.preferred_language if profile.user else Language.EN
        payload = {
            **profile.to_dict(),
            "preferred_language": language,
            "profile_completeness": completeness(profile),
        }
        return FarmerProfileOut.model_validate(payload)

    def update(self, user: User, payload: dict) -> FarmerProfile:
        profile = self.get_or_create(user)
        if payload.get("display_name"):
            profile.display_name = payload["display_name"].strip()
            user.full_name = payload["display_name"].strip()
        for field in (
            "village",
            "taluka",
            "district",
            "state",
            "pincode",
            "latitude",
            "longitude",
            "farming_experience_years",
            "primary_crops",
            "interests",
            "total_land_area",
            "total_land_unit",
            "bio",
            "organisation",
            "is_public",
        ):
            if field in payload and payload[field] is not None:
                setattr(profile, field, payload[field])
        # Deriving the state from the pincode is not attempted: guessing a state
        # from a partial postcode range would risk wrong scheme recommendations.
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def public_profile(self, profile_id: uuid.UUID) -> PublicFarmerProfile:
        profile = self.repo.get(profile_id)
        if profile is None or not profile.is_public:
            raise NotFoundError("That farmer profile could not be found.")
        user = self.db.get(User, profile.user_id)
        if user is None:
            raise NotFoundError("That farmer profile could not be found.")
        active_stages = [
            row[0]
            for row in self.db.execute(
                select(Crop.stage)
                .join(Farm, Farm.id == Crop.farm_id)
                .where(Farm.owner_id == user.id, Crop.status == CropStatus.ACTIVE)
            ).all()
        ]
        return PublicFarmerProfile(
            id=profile.id,
            display_name=profile.display_name,
            village=profile.village,
            district=profile.district,
            state=profile.state,
            farming_experience_years=profile.farming_experience_years,
            primary_crops=profile.primary_crops,
            interests=profile.interests,
            bio=profile.bio,
            organisation=profile.organisation,
            is_expert=user.has_role("expert", "moderator", "admin"),
            active_crop_stages=list(dict.fromkeys(active_stages)),
            member_since=profile.created_at,
        )

    # ----------------------------------------------------------- dashboard
    def dashboard(self, user: User) -> FarmerDashboard:
        profile = self.get_or_create(user)
        farms = self.farms.list_for_owner(user.id)
        active_crops: list[dict] = []
        stage_counts: dict[str, int] = {}
        total_ha = 0.0
        for farm in farms:
            total_ha += to_hectares(float(farm.area_value), farm.area_unit)
            for crop in farm.crops:
                if crop.deleted_at is not None:
                    continue
                stage_counts[crop.stage.value] = stage_counts.get(crop.stage.value, 0) + 1
                if crop.status == CropStatus.ACTIVE:
                    active_crops.append(self._crop_row(crop, farm))
        catalog = {
            row.code: row
            for row in self.db.execute(
                select(CropCatalog).where(
                    CropCatalog.code.in_([c["crop_code"] for c in active_crops] or ["__none__"])
                )
            )
            .scalars()
            .all()
        }
        for row in active_crops:
            entry = catalog.get(row["crop_code"])
            row["crop_name"] = entry.name_en if entry else row["crop_code"]
            row["disease_model_supported"] = bool(entry.disease_model_labels) if entry else False

        today = date.today()
        reminders: list[str] = []
        for crop in active_crops:
            if (
                crop["days_to_expected_harvest"] is not None
                and 0 <= crop["days_to_expected_harvest"] <= 14
            ):
                reminders.append(
                    f"{crop['crop_name']} on {crop['farm_name']} is expected to be ready for harvest "
                    f"in about {crop['days_to_expected_harvest']} day(s)."
                )
            if crop["sowing_date"] and crop["stage"] in (
                CropStage.PLANNED.value,
                CropStage.LAND_PREPARATION.value,
            ):
                age = (today - date.fromisoformat(crop["sowing_date"])).days
                if age > 10:
                    reminders.append(
                        f"Update the growth stage for {crop['crop_name']} on {crop['farm_name']} "
                        f"(sown {age} days ago) so recommendations stay accurate."
                    )
        if not farms:
            reminders.append(
                "Add your first farm to get weather, market and AI features tailored to your land."
            )
        elif completeness(profile) < 60:
            reminders.append(
                "Complete your profile (village, district, crops) for better local recommendations."
            )

        land_summary = {
            "total_farms": len(farms),
            "total_area_hectares": round(total_ha, 3),
            "total_area_acres": round(from_hectares(total_ha, "acre"), 3),
            "active_crop_count": len(active_crops),
            "harvested_crop_count": sum(
                1 for f in farms for c in f.crops if c.status == CropStatus.HARVESTED
            ),
        }
        return FarmerDashboard(
            profile=self.to_out(profile),
            land_summary=land_summary,
            crop_stage_counts=stage_counts,
            active_crops=active_crops,
            reminders=reminders[:5],
            data_freshness={
                "profile_updated_at": profile.updated_at.isoformat(),
                "note": "Weather and market sections fetch live provider data separately; "
                "their freshness is reported with each response.",
            },
        )

    @staticmethod
    def _crop_row(crop: Crop, farm) -> dict:
        days_to_harvest = (
            (crop.expected_harvest_date - date.today()).days if crop.expected_harvest_date else None
        )
        return {
            "crop_id": str(crop.id),
            "crop_code": crop.crop_code,
            "variety": crop.variety,
            "farm_id": str(farm.id),
            "farm_name": farm.name,
            "stage": crop.stage.value,
            "status": crop.status.value,
            "sowing_date": crop.sowing_date.isoformat() if crop.sowing_date else None,
            "expected_harvest_date": crop.expected_harvest_date.isoformat()
            if crop.expected_harvest_date
            else None,
            "days_to_expected_harvest": days_to_harvest,
            "area_value": float(crop.area_value) if crop.area_value else None,
            "area_unit": crop.area_unit.value if crop.area_unit else None,
            "irrigation_method": crop.irrigation_method.value if crop.irrigation_method else None,
        }

    def validate_crop_codes(self, codes: list[str]) -> list[str]:
        if not codes:
            return []
        known = set(
            self.db.execute(select(CropCatalog.code).where(CropCatalog.code.in_(codes))).scalars()
        )
        unknown = [c for c in codes if c not in known]
        if unknown:
            raise ValidationError(
                "Some crops are not in the crop catalog.",
                details={"unknown_crop_codes": unknown},
            )
        return codes
