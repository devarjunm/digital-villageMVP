"""Farmer profile and dashboard endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.analytics.service import AnalyticsService
from app.auth.dependencies import CurrentUser, DbSession, OptionalUser
from app.farmers.schemas import (
    FarmerDashboard,
    FarmerProfileOut,
    FarmerProfileUpdate,
    PublicFarmerProfile,
)
from app.farmers.service import FarmerService

router = APIRouter()


@router.get("/me", response_model=FarmerProfileOut, summary="My farmer profile")
def my_profile(user: CurrentUser, db: DbSession) -> FarmerProfileOut:
    service = FarmerService(db)
    return service.to_out(service.get_or_create(user))


@router.patch("/me", response_model=FarmerProfileOut, summary="Update my farmer profile")
def update_profile(
    payload: FarmerProfileUpdate, user: CurrentUser, db: DbSession, request: Request
) -> FarmerProfileOut:
    service = FarmerService(db)
    data = payload.model_dump(exclude_unset=True)
    if "primary_crops" in data and data["primary_crops"] is not None:
        service.validate_crop_codes(data["primary_crops"])
    profile = service.update(user, data)
    AnalyticsService(db).record_event(
        name="profile_updated",
        user_id=user.id,
        props={"fields": ",".join(sorted(data.keys()))[:120], "source": "app"},
        is_demo=user.is_demo,
    )
    return service.to_out(profile)


@router.get("/me/dashboard", response_model=FarmerDashboard, summary="Home tab aggregation")
def dashboard(user: CurrentUser, db: DbSession) -> FarmerDashboard:
    return FarmerService(db).dashboard(user)


@router.get(
    "/{profile_id}/public",
    response_model=PublicFarmerProfile,
    summary="Public profile (no contact details)",
)
def public_profile(
    profile_id: uuid.UUID, db: DbSession, viewer: OptionalUser
) -> PublicFarmerProfile:
    return FarmerService(db).public_profile(profile_id)
