"""Weather mirror tables.

Cache-first design: the provider is the source of truth, the DB keeps a copy so
the app can serve the last known value while an upstream provider is down — and
`retrieved_at` + `provider` make the age and origin of that copy explicit.
"""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, DemoFlagMixin, TimestampMixin, UUIDPrimaryKeyMixin


class WeatherObservation(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "weather_observations"
    __table_args__ = (
        sa.UniqueConstraint(
            "lat_key",
            "lon_key",
            "observed_at",
            "provider",
            name="uq_weather_obs_place_time_provider",
        ),
        sa.Index("ix_weather_observations_place", "lat_key", "lon_key", "observed_at"),
    )

    lat_key: Mapped[float] = mapped_column(sa.Numeric(6, 3), nullable=False)
    lon_key: Mapped[float] = mapped_column(sa.Numeric(6, 3), nullable=False)
    place_label: Mapped[str | None] = mapped_column(sa.String(200))
    observed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    feels_like_c: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    humidity_percent: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    rainfall_mm: Mapped[float | None] = mapped_column(sa.Numeric(8, 2))
    wind_speed_kmh: Mapped[float | None] = mapped_column(sa.Numeric(6, 2))
    wind_direction_deg: Mapped[float | None] = mapped_column(sa.Numeric(6, 2))
    pressure_hpa: Mapped[float | None] = mapped_column(sa.Numeric(7, 2))
    condition_code: Mapped[str | None] = mapped_column(sa.String(48))
    condition_text: Mapped[str | None] = mapped_column(sa.String(160))
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class WeatherForecast(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "weather_forecasts"
    __table_args__ = (
        sa.UniqueConstraint(
            "lat_key",
            "lon_key",
            "forecast_for",
            "provider",
            name="uq_weather_forecast_place_time_provider",
        ),
        sa.Index("ix_weather_forecasts_place", "lat_key", "lon_key", "forecast_for"),
    )

    lat_key: Mapped[float] = mapped_column(sa.Numeric(6, 3), nullable=False)
    lon_key: Mapped[float] = mapped_column(sa.Numeric(6, 3), nullable=False)
    forecast_for: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    temp_min_c: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    temp_max_c: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    humidity_percent: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    rainfall_mm: Mapped[float | None] = mapped_column(sa.Numeric(8, 2))
    rainfall_probability_percent: Mapped[float | None] = mapped_column(sa.Numeric(5, 2))
    wind_speed_kmh: Mapped[float | None] = mapped_column(sa.Numeric(6, 2))
    condition_code: Mapped[str | None] = mapped_column(sa.String(48))
    condition_text: Mapped[str | None] = mapped_column(sa.String(160))
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)


class WeatherAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin, DemoFlagMixin):
    __tablename__ = "weather_alerts"
    __table_args__ = (
        sa.Index("ix_weather_alerts_state_window", "state", "valid_from", "valid_to"),
    )

    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    provider_alert_id: Mapped[str | None] = mapped_column(sa.String(128))
    state: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    district: Mapped[str | None] = mapped_column(sa.String(120), index=True)
    event: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(32), default="minor", nullable=False)
    headline: Mapped[str] = mapped_column(sa.String(400), nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    instruction: Mapped[str | None] = mapped_column(sa.Text)
    valid_from: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    issued_on: Mapped[date | None] = mapped_column(sa.Date)
    source_url: Mapped[str | None] = mapped_column(sa.String(1024))
    retrieved_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    is_demo: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
