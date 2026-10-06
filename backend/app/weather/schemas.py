"""Weather API contracts.

Provenance fields are part of every response on purpose: `provider`, `source`,
`is_demo`, `demo_notice`, `retrieved_at`, `cached`, `age_seconds`. A farmer (or an
auditor) can always tell whether a number came from a live station, a cached
reading, or the deterministic demo provider.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.i18n import t


def demo_notice(language: str = "en") -> str:
    from app.core.i18n import resolve_language

    return t("notice.demo_data", resolve_language(language))


class CurrentWeatherOut(BaseModel):
    latitude: float
    longitude: float
    place_label: str | None = None
    temperature_c: float | None = None
    feels_like_c: float | None = None
    humidity_percent: float | None = None
    rainfall_mm: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    pressure_hpa: float | None = None
    condition_code: str
    condition_text: str
    observed_at: datetime
    provider: str
    source: str
    is_demo: bool = False
    demo_notice: str | None = None
    retrieved_at: datetime
    cached: bool = False
    age_seconds: int | None = Field(
        default=None, description="Seconds since the observation was retrieved/recorded."
    )
    farming_note: str = Field(
        description="Rule-based reading of the conditions (screening thresholds, labelled derived)."
    )
    data_class: Literal["observed", "derived"] = "observed"


class ForecastDayOut(BaseModel):
    forecast_for: datetime
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    humidity_percent: float | None = None
    rainfall_mm: float | None = None
    rainfall_probability_percent: float | None = None
    wind_speed_kmh: float | None = None
    condition_code: str | None = None
    condition_text: str | None = None


class ForecastOut(BaseModel):
    latitude: float
    longitude: float
    days: list[ForecastDayOut]
    provider: str
    source: str
    is_demo: bool = False
    demo_notice: str | None = None
    retrieved_at: datetime
    cached: bool = False
    advisories: list[str] = Field(
        default_factory=list,
        description="Rule-based advisories from screening thresholds — derived, not official warnings.",
    )
    advisories_data_class: Literal["derived"] = "derived"


class WeatherAlertOut(BaseModel):
    event: str
    severity: str
    headline: str
    description: str | None = None
    instruction: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_url: str | None = None
    provider: str
    is_demo: bool = False


class AlertsOut(BaseModel):
    alerts: list[WeatherAlertOut] = []
    provider: str
    is_demo: bool = False
    retrieved_at: datetime
    supported: bool = Field(
        description="False when the configured provider has no public alert feed. Absence of alerts then "
        "means 'unknown', not 'all clear'."
    )
    notice: str | None = None


class FarmWeatherOut(BaseModel):
    farm_id: uuid.UUID
    farm_name: str
    location_source: Literal["farm", "profile", "missing"]
    current: CurrentWeatherOut | None = None
    forecast: ForecastOut | None = None
    alerts: AlertsOut
    error: str | None = None


class WeatherProviderHealth(BaseModel):
    provider: str
    available: bool
    is_demo: bool
    detail: str | None = None
    note: str | None = None


class WeatherHistoryPoint(BaseModel):
    observed_at: datetime
    temperature_c: float | None = None
    humidity_percent: float | None = None
    rainfall_mm: float | None = None
    provider: str


class WeatherHistoryOut(BaseModel):
    latitude: float
    longitude: float
    days: int
    points: list[WeatherHistoryPoint] = []
    count: int
    provider_filter: str | None = None
    note: str = "Stored observations for this location. Demo rows are labelled per point."


class WeatherLocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    language: str = Field(default="en", pattern="^(en|mr|hi)$")


class WeatherFarmQuery(BaseModel):
    language: str = Field(default="en", pattern="^(en|mr|hi)$")
    days: int = Field(default=7, ge=1, le=14)


class WeatherHistoryQuery(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    days: int = Field(default=7, ge=1, le=60)


class WeatherAlertQuery(BaseModel):
    state: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    language: str = Field(default="en", pattern="^(en|mr|hi)$")


class ObservedOn(BaseModel):
    """Small helper used by the history endpoint to group by day."""

    day: date
    points: int
    rainfall_total_mm: float
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
