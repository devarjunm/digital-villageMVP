"""Farm endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.analytics.service import AnalyticsService
from app.auth.dependencies import CurrentUser, DbSession
from app.core.errors import not_found
from app.crops.schemas import CropCreate, CropOut
from app.crops.service import CropService
from app.farms.schemas import (
    FarmCreate,
    FarmOut,
    FarmSummary,
    FarmUpdate,
    SoilTestCreate,
    SoilTestOut,
)
from app.farms.service import FarmService

router = APIRouter()


@router.get("", response_model=list[FarmOut], summary="My farms")
def list_farms(user: CurrentUser, db: DbSession) -> list[FarmOut]:
    return FarmService(db).list(user)


@router.post(
    "", response_model=FarmOut, status_code=status.HTTP_201_CREATED, summary="Create a farm"
)
def create_farm(payload: FarmCreate, user: CurrentUser, db: DbSession) -> FarmOut:
    service = FarmService(db)
    farm = service.create(user, payload.model_dump())
    AnalyticsService(db).record_event(
        name="farm_created",
        user_id=user.id,
        props={
            "area_unit": payload.area_unit.value,
            "soil_type": payload.soil_type.value,
            "irrigation_type": payload.irrigation_type.value,
        },
        is_demo=user.is_demo,
    )
    return service.to_out(farm)


@router.get("/{farm_id}", response_model=FarmOut, summary="Farm detail")
def get_farm(farm_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FarmOut:
    """Farm detail for its owner (staff may read any farm for moderation).

    Ownership failures answer 404, exactly like a farm that does not exist — see
    `app.core.errors.not_found` for why.
    """
    service = FarmService(db)
    farm = service.repo.get(farm_id)
    if farm is None or (farm.owner_id != user.id and not user.has_role("admin", "moderator")):
        not_found()
    return service.to_out(farm)


@router.patch("/{farm_id}", response_model=FarmOut, summary="Update a farm")
def update_farm(
    farm_id: uuid.UUID, payload: FarmUpdate, user: CurrentUser, db: DbSession
) -> FarmOut:
    service = FarmService(db)
    farm = service.update(user, farm_id, payload.model_dump(exclude_unset=True))
    return service.to_out(farm)


@router.delete(
    "/{farm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a farm (soft)",
)
def delete_farm(farm_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    FarmService(db).delete(user, farm_id)


@router.get(
    "/{farm_id}/summary", response_model=FarmSummary, summary="Farm summary for the My Farm tab"
)
def farm_summary(farm_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FarmSummary:
    return FarmService(db).summary(user, farm_id)


@router.post(
    "/{farm_id}/soil-tests",
    response_model=SoilTestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a soil test",
)
def add_soil_test(
    farm_id: uuid.UUID, payload: SoilTestCreate, user: CurrentUser, db: DbSession
) -> SoilTestOut:
    return FarmService(db).add_soil_test(user, farm_id, payload.model_dump())


@router.get("/{farm_id}/crops", response_model=list[CropOut], summary="Crops on a farm")
def farm_crops(farm_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[CropOut]:
    return CropService(db).list_for_farm(user, farm_id)


@router.post(
    "/{farm_id}/crops",
    response_model=CropOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a crop to a farm",
)
def create_crop(
    farm_id: uuid.UUID, payload: CropCreate, user: CurrentUser, db: DbSession
) -> CropOut:
    service = CropService(db)
    crop = service.create(user, farm_id, payload.model_dump())
    AnalyticsService(db).record_event(
        name="crop_created",
        user_id=user.id,
        props={
            "crop": payload.crop_code,
            "stage": payload.stage.value,
            "season": payload.season.value,
        },
        is_demo=user.is_demo,
    )
    return service.to_out(crop)
