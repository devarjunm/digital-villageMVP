"""Weather service: provider orchestration, caching, persistence and fallbacks.

Caching: Redis (falling back to an in-process dict) with a short TTL
(CACHE_TTL_WEATHER_SECONDS, default 15 min) keyed by rounded coordinates, so we
do not hammer an upstream provider for every dashboard load. The cache entry
keeps `retrieved_at`, so a cached response is displayed with its true age rather
than being presented as fresh.

Fallback: if the provider fails, the last stored observation for that grid cell
is returned with `stale_fallback=true` and a clear message; if nothing is stored,
the endpoint returns a 503 error envelope rather than fake weather.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import settings
from app.core.errors import ProviderUnavailableError
from app.core.logging import get_logger
from app.core.observability import observe_provider_call
from app.providers.weather import (
    WeatherAlertItem,
    WeatherForecastResult,
    WeatherNow,
    get_weather_provider,
)
from app.weather.models import WeatherAlert, WeatherForecast, WeatherObservation
from app.weather.schemas import (
    AlertsOut,
    CurrentWeatherOut,
    ForecastDayOut,
    ForecastOut,
    WeatherAlertOut,
    demo_notice,
)

logger = get_logger(__name__)
SOURCE_LABELS = {
    "mock": "Demo weather provider (deterministic sample data)",
    "openweathermap": "OpenWeatherMap current weather & 5-day/3-hour forecast API",
}


def _grid(value: float) -> float:
    """Round coordinates to ~1 km so nearby farms share one cache entry."""
    return round(value, 3)


class WeatherService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.provider = get_weather_provider()
        self.cache = get_cache()

    # ------------------------------------------------------------------ current
    def current(
        self, *, latitude: float, longitude: float, language: str = "en", allow_stale: bool = True
    ) -> CurrentWeatherOut:
        lat, lon = _grid(latitude), _grid(longitude)
        cache_key = f"dv:weather:current:{lat}:{lon}:{self.provider.name}"
        cached = self.cache.get_json(cache_key)
        if cached:
            payload = CurrentWeatherOut(**cached)
            payload.cached = True
            payload.age_seconds = int((datetime.now(UTC) - payload.retrieved_at).total_seconds())
            return payload

        try:
            with observe_provider_call(self.provider.name, "current"):
                now: WeatherNow = self.provider.current(latitude=lat, longitude=lon)
        except ProviderUnavailableError:
            if allow_stale:
                stale = self._last_stored_observation(lat, lon)
                if stale is not None:
                    return stale
            raise
        payload = self._to_current_out(
            now, latitude=latitude, longitude=longitude, language=language
        )
        self.cache.set_json(
            cache_key, payload.model_dump(mode="json"), ttl=settings.cache_ttl_weather_seconds
        )
        self._store_observation(payload, lat, lon)
        return payload

    def forecast(
        self, *, latitude: float, longitude: float, days: int = 7, language: str = "en"
    ) -> ForecastOut:
        lat, lon = _grid(latitude), _grid(longitude)
        cache_key = f"dv:weather:forecast:{lat}:{lon}:{days}:{self.provider.name}"
        cached = self.cache.get_json(cache_key)
        if cached:
            payload = ForecastOut(**cached)
            payload.cached = True
            return payload

        with observe_provider_call(self.provider.name, "forecast"):
            result: WeatherForecastResult = self.provider.forecast(
                latitude=lat, longitude=lon, days=max(1, min(days, 14))
            )
        advisories = self._advisories(result, language=language)
        payload = ForecastOut(
            latitude=latitude,
            longitude=longitude,
            days=[
                ForecastDayOut(
                    forecast_for=day.forecast_for,
                    temp_min_c=day.temp_min_c,
                    temp_max_c=day.temp_max_c,
                    humidity_percent=day.humidity_percent,
                    rainfall_mm=day.rainfall_mm,
                    rainfall_probability_percent=day.rainfall_probability_percent,
                    wind_speed_kmh=day.wind_speed_kmh,
                    condition_code=day.condition_code,
                    condition_text=day.condition_text,
                )
                for day in result.days
            ],
            provider=result.provider,
            source=SOURCE_LABELS.get(result.provider, result.provider),
            is_demo=result.is_demo,
            demo_notice=demo_notice(language) if result.is_demo else None,
            retrieved_at=result.retrieved_at,
            advisories=advisories,
        )
        self.cache.set_json(
            cache_key, payload.model_dump(mode="json"), ttl=settings.cache_ttl_weather_seconds
        )
        self._store_forecast(result, lat, lon)
        return payload

    def alerts(
        self, *, state: str | None = None, district: str | None = None, language: str = "en"
    ) -> AlertsOut:
        cache_key = f"dv:weather:alerts:{state or '*'}:{district or '*'}:{self.provider.name}"
        cached = self.cache.get_json(cache_key)
        if cached:
            return AlertsOut(**cached)
        with observe_provider_call(self.provider.name, "alerts"):
            items: list[WeatherAlertItem] = self.provider.alerts(state=state, district=district)
        payload = AlertsOut(
            alerts=[
                WeatherAlertOut(
                    event=item.event,
                    severity=item.severity,
                    headline=item.headline,
                    description=item.description,
                    instruction=item.instruction,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    source_url=item.source_url,
                    provider=item.provider,
                    is_demo=item.is_demo,
                )
                for item in items
            ],
            provider=self.provider.name,
            is_demo=self.provider.is_demo,
            retrieved_at=datetime.now(UTC),
            supported=bool(items) or not self.provider.is_demo,
            notice=(
                None
                if items
                else (
                    "No public alert feed is configured for the active provider, so no alerts are shown. "
                    "This is not a statement that there are no warnings in your area."
                )
            ),
        )
        self.cache.set_json(
            cache_key, payload.model_dump(mode="json"), ttl=settings.cache_ttl_weather_seconds
        )
        return payload

    def for_farm(self, farm, *, language: str = "en"):
        """Combined farm weather used by the Home tab and the agent tool."""
        from app.weather.schemas import FarmWeatherOut

        latitude = float(farm.latitude) if farm.latitude is not None else None
        longitude = float(farm.longitude) if farm.longitude is not None else None
        location_source = "farm"
        if latitude is None or longitude is None:
            profile = farm.owner.profile if hasattr(farm, "owner") and farm.owner else None
            if profile is None:
                from app.farmers.models import FarmerProfile

                profile = self.db.execute(
                    select(FarmerProfile).where(FarmerProfile.user_id == farm.owner_id)
                ).scalar_one_or_none()
            if profile and profile.latitude is not None and profile.longitude is not None:
                latitude, longitude = float(profile.latitude), float(profile.longitude)
                location_source = "profile"
            else:
                return FarmWeatherOut(
                    farm_id=farm.id,
                    farm_name=farm.name,
                    location_source="missing",
                    current=None,
                    forecast=None,
                    alerts=AlertsOut(
                        alerts=[],
                        provider=self.provider.name,
                        is_demo=self.provider.is_demo,
                        retrieved_at=datetime.now(UTC),
                        supported=False,
                    ),
                    error=(
                        "This farm has no location yet. Add the village coordinates (or set them in your "
                        "profile) to see weather for this farm."
                    ),
                )
        current = None
        forecast = None
        error = None
        try:
            current = self.current(latitude=latitude, longitude=longitude, language=language)
        except ProviderUnavailableError as exc:
            error = exc.message
        try:
            forecast = self.forecast(latitude=latitude, longitude=longitude, language=language)
        except ProviderUnavailableError as exc:
            error = error or exc.message
        return FarmWeatherOut(
            farm_id=farm.id,
            farm_name=farm.name,
            location_source=location_source,
            current=current,
            forecast=forecast,
            alerts=self.alerts(state=farm.state, district=farm.district, language=language),
            error=error,
        )

    # ---------------------------------------------------------------- helpers
    def _to_current_out(
        self, now: WeatherNow, *, latitude: float, longitude: float, language: str
    ) -> CurrentWeatherOut:
        return CurrentWeatherOut(
            latitude=latitude,
            longitude=longitude,
            place_label=now.place_label,
            temperature_c=now.temperature_c,
            feels_like_c=now.feels_like_c,
            humidity_percent=now.humidity_percent,
            rainfall_mm=now.rainfall_mm,
            wind_speed_kmh=now.wind_speed_kmh,
            wind_direction_deg=now.wind_direction_deg,
            pressure_hpa=now.pressure_hpa,
            condition_code=now.condition_code,
            condition_text=now.condition_text,
            observed_at=now.observed_at,
            provider=now.provider,
            source=SOURCE_LABELS.get(now.provider, now.provider),
            is_demo=now.is_demo,
            demo_notice=demo_notice(language) if now.is_demo else None,
            retrieved_at=datetime.now(UTC),
            farming_note=self._farming_note(now),
        )

    @staticmethod
    def _farming_note(now: WeatherNow) -> str:
        """Deterministic plain-language reading of the current observation."""
        notes: list[str] = []
        if now.rainfall_mm and now.rainfall_mm >= 2:
            notes.append(
                f"Rain recorded ({now.rainfall_mm:.1f} mm in the last hour): pause spraying and check drainage in low-lying plots."
            )
        if now.humidity_percent and now.humidity_percent >= 80:
            notes.append(
                "High humidity (80%+) favours fungal leaf diseases — scout the crop canopy and keep leaves dry where possible."
            )
        if now.temperature_c is not None and now.temperature_c >= 38:
            notes.append(
                "High temperature: irrigate early morning or evening and avoid midday spraying."
            )
        if now.wind_speed_kmh and now.wind_speed_kmh >= 20:
            notes.append("Windy conditions: spraying will drift. Wait for calmer conditions.")
        if not notes:
            notes.append(
                "Conditions look ordinary for spraying and field work; still check the forecast before planning."
            )
        return " ".join(notes)

    @staticmethod
    def _advisories(result: WeatherForecastResult, *, language: str) -> list[str]:
        advisories: list[str] = []
        heavy = [d for d in result.days if (d.rainfall_mm or 0) >= 20]
        dry_spell = 0
        for day in result.days:
            if (day.rainfall_probability_percent or 0) < 20:
                dry_spell += 1
            else:
                dry_spell = 0
        if heavy:
            first = heavy[0].forecast_for.date().isoformat()
            advisories.append(
                f"Heavy rain (≥20 mm) is forecast around {first}: secure harvested produce, check field drainage, "
                "and postpone fertiliser top-dressing until the soil drains."
            )
        if dry_spell >= 3:
            advisories.append(
                "A run of dry days is forecast: plan irrigation and mulch to reduce moisture loss, especially for "
                "young transplants."
            )
        hot = [d for d in result.days if (d.temp_max_c or 0) >= 40]
        if hot:
            advisories.append(
                "Very high maximum temperatures are forecast: irrigate in the early morning or evening and provide "
                "shade for nursery beds."
            )
        if result.is_demo:
            advisories.append(
                "Advisories are computed from demo weather data and are provided to show how the feature behaves — "
                "do not plan field operations from them."
            )
        return advisories

    # ------------------------------------------------------------- persistence
    def _store_observation(self, payload: CurrentWeatherOut, lat: float, lon: float) -> None:
        try:
            existing = self.db.execute(
                select(WeatherObservation).where(
                    WeatherObservation.lat_key == lat,
                    WeatherObservation.lon_key == lon,
                    WeatherObservation.observed_at == payload.observed_at,
                    WeatherObservation.provider == payload.provider,
                )
            ).scalar_one_or_none()
            if existing:
                return
            self.db.add(
                WeatherObservation(
                    lat_key=lat,
                    lon_key=lon,
                    place_label=payload.place_label,
                    observed_at=payload.observed_at,
                    temperature_c=payload.temperature_c,
                    feels_like_c=payload.feels_like_c,
                    humidity_percent=payload.humidity_percent,
                    rainfall_mm=payload.rainfall_mm,
                    wind_speed_kmh=payload.wind_speed_kmh,
                    wind_direction_deg=payload.wind_direction_deg,
                    pressure_hpa=payload.pressure_hpa,
                    condition_code=payload.condition_code,
                    condition_text=payload.condition_text,
                    provider=payload.provider,
                    retrieved_at=payload.retrieved_at,
                    is_demo=payload.is_demo,
                )
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                "weather_persist_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )

    def _store_forecast(self, result: WeatherForecastResult, lat: float, lon: float) -> None:
        try:
            for day in result.days:
                existing = self.db.execute(
                    select(WeatherForecast).where(
                        WeatherForecast.lat_key == lat,
                        WeatherForecast.lon_key == lon,
                        WeatherForecast.forecast_for == day.forecast_for,
                        WeatherForecast.provider == result.provider,
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.temp_min_c = day.temp_min_c
                    existing.temp_max_c = day.temp_max_c
                    existing.humidity_percent = day.humidity_percent
                    existing.rainfall_mm = day.rainfall_mm
                    existing.rainfall_probability_percent = day.rainfall_probability_percent
                    existing.wind_speed_kmh = day.wind_speed_kmh
                    existing.condition_code = day.condition_code
                    existing.condition_text = day.condition_text
                    existing.retrieved_at = result.retrieved_at
                    continue
                self.db.add(
                    WeatherForecast(
                        lat_key=lat,
                        lon_key=lon,
                        forecast_for=day.forecast_for,
                        temp_min_c=day.temp_min_c,
                        temp_max_c=day.temp_max_c,
                        humidity_percent=day.humidity_percent,
                        rainfall_mm=day.rainfall_mm,
                        rainfall_probability_percent=day.rainfall_probability_percent,
                        wind_speed_kmh=day.wind_speed_kmh,
                        condition_code=day.condition_code,
                        condition_text=day.condition_text,
                        provider=result.provider,
                        retrieved_at=result.retrieved_at,
                        is_demo=result.is_demo,
                    )
                )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                "weather_forecast_persist_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )

    def _last_stored_observation(self, lat: float, lon: float) -> CurrentWeatherOut | None:
        row = (
            self.db.execute(
                select(WeatherObservation)
                .where(WeatherObservation.lat_key == lat, WeatherObservation.lon_key == lon)
                .order_by(WeatherObservation.observed_at.desc())
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        age = int((datetime.now(UTC) - row.observed_at).total_seconds())
        if age > 6 * 3600:  # older than 6h is not useful, even as a fallback
            return None
        return CurrentWeatherOut(
            latitude=float(row.lat_key),
            longitude=float(row.lon_key),
            place_label=row.place_label,
            temperature_c=row.temperature_c,
            feels_like_c=row.feels_like_c,
            humidity_percent=row.humidity_percent,
            rainfall_mm=row.rainfall_mm,
            wind_speed_kmh=row.wind_speed_kmh,
            wind_direction_deg=row.wind_direction_deg,
            pressure_hpa=row.pressure_hpa,
            condition_code=row.condition_code or "unknown",
            condition_text=row.condition_text or "Unknown",
            observed_at=row.observed_at,
            provider=row.provider,
            source=f"{SOURCE_LABELS.get(row.provider, row.provider)} (last stored reading)",
            is_demo=row.is_demo,
            demo_notice=demo_notice("en") if row.is_demo else None,
            retrieved_at=row.retrieved_at,
            cached=True,
            age_seconds=age,
            farming_note=(
                f"The weather service is currently unavailable. This reading is {age // 60} minute(s) old."
            ),
        )

    def store_alerts(self, items: list[WeatherAlertItem]) -> int:
        """Persist alerts (used by the alert-scan job)."""
        stored = 0
        for item in items:
            exists = self.db.execute(
                select(WeatherAlert).where(
                    WeatherAlert.provider == item.provider,
                    WeatherAlert.event == item.event,
                    WeatherAlert.headline == item.headline,
                    WeatherAlert.valid_from == item.valid_from,
                )
            ).scalar_one_or_none()
            if exists:
                continue
            self.db.add(
                WeatherAlert(
                    provider=item.provider,
                    event=item.event,
                    severity=item.severity,
                    headline=item.headline,
                    description=item.description,
                    instruction=item.instruction,
                    valid_from=item.valid_from,
                    valid_to=item.valid_to,
                    retrieved_at=datetime.now(UTC),
                    is_demo=item.is_demo,
                    source_url=item.source_url,
                )
            )
            stored += 1
        if stored:
            self.db.commit()
        return stored

    def active_alerts_from_db(self, *, state: str | None = None) -> list[WeatherAlert]:
        now = datetime.now(UTC)
        stmt = select(WeatherAlert).where(
            (WeatherAlert.valid_to.is_(None)) | (WeatherAlert.valid_to >= now)
        )
        if state:
            stmt = stmt.where(WeatherAlert.state == state)
        return list(self.db.execute(stmt.order_by(WeatherAlert.valid_from.desc())).scalars().all())

    def health(self) -> dict:
        """Provider status, shaped for the API schema.

        `is_demo` travels with the status so a client can badge the whole weather
        surface, not just individual responses. `note` states in words what the
        provider is, because "provider: mock" is easy to overlook.
        """
        from dataclasses import asdict

        payload = asdict(self.provider.health())
        extra = payload.pop("extra", None) or {}
        is_demo = bool(payload.get("is_demo"))
        note = extra.get("note")
        if not note:
            if is_demo:
                note = (
                    "Sample weather for development and demonstration. Figures are deterministic "
                    "per place and date and must not be used for farming decisions."
                )
            elif not payload.get("available"):
                note = "The live weather provider is not configured; weather endpoints will fail explicitly."
            else:
                note = None
        payload["note"] = note
        return payload
