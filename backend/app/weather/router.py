"""Weather endpoints.

Every response carries provider provenance. `location_source` tells the app
whether coordinates came from the farm, the farmer's profile, or were missing
(in which case the app must ask for a location instead of guessing one).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.auth.dependencies import CurrentUser, DbSession
from app.core.ratelimit import enforce_rate_limit
from app.farms.repository import FarmRepository
from app.weather.schemas import (
    AlertsOut,
    CurrentWeatherOut,
    FarmWeatherOut,
    ForecastOut,
    WeatherProviderHealth,
)
from app.weather.service import WeatherService

router = APIRouter()


@router.get(
    "/current", response_model=CurrentWeatherOut, summary="Current conditions for a location"
)
def current(
    db: DbSession,
    request: Request,
    user: CurrentUser,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    language: Annotated[str, Query(pattern="^(en|mr|hi)$")] = "en",
) -> CurrentWeatherOut:
    enforce_rate_limit(request, "read")
    return WeatherService(db).current(latitude=latitude, longitude=longitude, language=language)


@router.get(
    "/forecast", response_model=ForecastOut, summary="Multi-day forecast with rule-based advisories"
)
def forecast(
    db: DbSession,
    request: Request,
    user: CurrentUser,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    days: Annotated[int, Query(ge=1, le=14)] = 7,
    language: Annotated[str, Query(pattern="^(en|mr|hi)$")] = "en",
) -> ForecastOut:
    enforce_rate_limit(request, "read")
    return WeatherService(db).forecast(
        latitude=latitude, longitude=longitude, days=days, language=language
    )


@router.get(
    "/alerts",
    response_model=AlertsOut,
    summary="Weather alerts (may be unsupported by the provider)",
)
def alerts(
    db: DbSession,
    request: Request,
    user: CurrentUser,
    state: Annotated[str | None, Query(max_length=120)] = None,
    district: Annotated[str | None, Query(max_length=120)] = None,
    language: Annotated[str, Query(pattern="^(en|mr|hi)$")] = "en",
) -> AlertsOut:
    enforce_rate_limit(request, "read")
    return WeatherService(db).alerts(state=state, district=district, language=language)


@router.get(
    "/farm/{farm_id}",
    response_model=FarmWeatherOut,
    summary="Weather for one of your farms (farm coordinates, falling back to your profile)",
)
def farm_weather(
    farm_id: uuid.UUID,
    db: DbSession,
    request: Request,
    user: CurrentUser,
    language: Annotated[str, Query(pattern="^(en|mr|hi)$")] = "en",
) -> FarmWeatherOut:
    enforce_rate_limit(request, "read")
    from app.core.errors import NotFoundError

    farm = FarmRepository(db).get(farm_id)
    if farm is None or farm.owner_id != user.id:
        raise NotFoundError("Farm not found.")
    return WeatherService(db).for_farm(farm, language=language)


@router.get("/provider", response_model=WeatherProviderHealth, summary="Weather provider status")
def provider(db: DbSession) -> WeatherProviderHealth:
    health = WeatherService(db).health()
    return WeatherProviderHealth(**health)
