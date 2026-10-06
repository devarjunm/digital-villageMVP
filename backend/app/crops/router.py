"""Crop and crop-catalog endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.auth.dependencies import CurrentUser, DbSession
from app.core.enums import CropStatus
from app.crops.schemas import (
    CropCatalogOut,
    CropEventCreate,
    CropEventOut,
    CropOut,
    CropUpdate,
)
from app.crops.service import CropService

router = APIRouter()


@router.get("/catalog", response_model=list[CropCatalogOut], summary="Supported crops (catalog)")
def catalog(
    db: DbSession, q: Annotated[str | None, Query(max_length=60)] = None
) -> list[CropCatalogOut]:
    return CropService(db).catalog(search=q)


@router.get("", response_model=list[CropOut], summary="All my crops across farms")
def my_crops(
    user: CurrentUser,
    db: DbSession,
    status_filter: Annotated[CropStatus | None, Query(alias="status")] = None,
) -> list[CropOut]:
    return CropService(db).list_for_user(user, status=status_filter)


@router.get("/{crop_id}", response_model=CropOut, summary="Crop detail")
def get_crop(crop_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CropOut:
    return CropService(db).get(user, crop_id)


@router.patch("/{crop_id}", response_model=CropOut, summary="Update a crop (stage, status, dates)")
def update_crop(
    crop_id: uuid.UUID, payload: CropUpdate, user: CurrentUser, db: DbSession
) -> CropOut:
    service = CropService(db)
    crop = service.update(user, crop_id, payload.model_dump(exclude_unset=True))
    return service.to_out(crop)


@router.delete(
    "/{crop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a crop (soft)",
)
def delete_crop(crop_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    CropService(db).delete(user, crop_id)


@router.get("/{crop_id}/events", response_model=list[CropEventOut], summary="Crop activity log")
def list_events(crop_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[CropEventOut]:
    return [CropEventOut.model_validate(e) for e in CropService(db).list_events(user, crop_id)]


@router.post(
    "/{crop_id}/events",
    response_model=CropEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log an activity (irrigation, fertiliser, observation…)",
)
def add_event(
    crop_id: uuid.UUID, payload: CropEventCreate, user: CurrentUser, db: DbSession
) -> CropEventOut:
    event = CropService(db).add_event(user, crop_id, payload.model_dump())
    return CropEventOut.model_validate(event)


@router.get("/{crop_id}/stage-guidance", summary="Derived stage guidance (not a model output)")
def stage_guidance(crop_id: uuid.UUID, user: CurrentUser, db: DbSession) -> dict:
    service = CropService(db)
    crop = service._owned_crop(user, crop_id)
    return service.stage_guidance(crop)
