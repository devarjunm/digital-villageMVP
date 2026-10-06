"""Weather providers.

`WEATHER_PROVIDER=mock` (default) serves deterministic, clearly-labelled demo
weather so the whole product works offline; `WEATHER_PROVIDER=openweathermap`
uses the real API and requires WEATHER_API_KEY. The API layer always carries
`provider`, `is_demo` and `retrieved_at`, so a demo forecast can never be shown
as a live observation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.errors import ProviderUnavailableError

PROVIDER_DETAIL = "Weather provider"


@dataclass(slots=True)
class WeatherNow:
    temperature_c: float | None
    feels_like_c: float | None
    humidity_percent: float | None
    rainfall_mm: float | None
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    pressure_hpa: float | None
    condition_code: str
    condition_text: str
    observed_at: datetime
    provider: str
    is_demo: bool
    place_label: str | None = None


@dataclass(slots=True)
class ForecastDay:
    forecast_for: datetime
    temp_min_c: float | None
    temp_max_c: float | None
    humidity_percent: float | None
    rainfall_mm: float | None
    rainfall_probability_percent: float | None
    wind_speed_kmh: float | None
    condition_code: str
    condition_text: str


@dataclass(slots=True)
class WeatherForecastResult:
    days: list[ForecastDay]
    provider: str
    is_demo: bool
    retrieved_at: datetime
    place_label: str | None = None


@dataclass(slots=True)
class WeatherAlertItem:
    event: str
    severity: str
    headline: str
    description: str | None
    instruction: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    source_url: str | None = None
    provider: str = "mock"
    is_demo: bool = True


@dataclass(slots=True)
class ProviderHealth:
    provider: str
    available: bool
    is_demo: bool = False
    detail: str | None = None
    extra: dict = field(default_factory=dict)


class WeatherProvider(Protocol):
    name: str
    is_demo: bool

    def current(self, *, latitude: float, longitude: float) -> WeatherNow: ...

    def forecast(
        self, *, latitude: float, longitude: float, days: int = 7
    ) -> WeatherForecastResult: ...

    def alerts(
        self, *, state: str | None = None, district: str | None = None
    ) -> list[WeatherAlertItem]: ...

    def health(self) -> ProviderHealth: ...


# --------------------------------------------------------------------------- mock
class MockWeatherProvider:
    """Deterministic pseudo-weather derived from coordinates and date.

    Deterministic (same input ⇒ same output) so tests and demos are reproducible,
    and labelled DEMO everywhere it surfaces. It models a plausible seasonal
    cycle rather than random noise, but it is *not* a forecast of anything.
    """

    name = "mock"
    is_demo = True

    def _seed(self, latitude: float, longitude: float, when: datetime) -> float:
        raw = f"{latitude:.3f}:{longitude:.3f}:{when:%Y-%m-%d}"
        digest = hashlib.sha256(raw.encode()).digest()
        return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF

    def _seasonal_base(self, latitude: float, when: datetime) -> float:
        # Northern hemisphere monsoon-influenced pattern, coarse on purpose.
        month = when.month
        base = 27.5 - abs(latitude - 20.0) * 0.25
        if month in (12, 1, 2):
            base -= 6.5
        elif month in (3, 4, 5):
            base += 3.0
        elif month in (6, 7, 8, 9):
            base -= 1.5
        else:
            base -= 3.0
        return base

    def current(self, *, latitude: float, longitude: float) -> WeatherNow:
        now = datetime.now(UTC)
        seed = self._seed(latitude, longitude, now)
        base = self._seasonal_base(latitude, now)
        temp = base + (seed - 0.5) * 4
        humidity = 45 + seed * 45
        monsoon = now.month in (6, 7, 8, 9)
        rainfall = round(max(0.0, (seed - (0.55 if monsoon else 0.85)) * 40), 1)
        if rainfall > 6:
            code, text = "rain", "Moderate rain"
        elif rainfall > 0.5:
            code, text = "drizzle", "Light drizzle"
        elif humidity > 70:
            code, text = "clouds", "Cloudy"
        else:
            code, text = "clear", "Clear sky"
        return WeatherNow(
            temperature_c=round(temp, 1),
            feels_like_c=round(temp + (humidity - 50) * 0.03, 1),
            humidity_percent=round(humidity, 0),
            rainfall_mm=rainfall,
            wind_speed_kmh=round(4 + seed * 16, 1),
            wind_direction_deg=round((seed * 360) % 360, 0),
            pressure_hpa=round(1005 + (1 - seed) * 12, 0),
            condition_code=code,
            condition_text=text,
            observed_at=now,
            provider=self.name,
            is_demo=True,
            place_label=None,
        )

    def forecast(
        self, *, latitude: float, longitude: float, days: int = 7
    ) -> WeatherForecastResult:
        now = datetime.now(UTC)
        out: list[ForecastDay] = []
        for offset in range(1, days + 1):
            target = (now + timedelta(days=offset)).replace(
                hour=12, minute=0, second=0, microsecond=0
            )
            seed = self._seed(latitude, longitude, target)
            base = self._seasonal_base(latitude, target)
            spread = 4 + seed * 4
            monsoon = target.month in (6, 7, 8, 9)
            rain_prob = int(min(95, max(0, (seed * 100) if monsoon else (seed - 0.35) * 100)))
            rainfall = round(rain_prob / 100 * (18 if monsoon else 8) * (0.4 + seed), 1)
            out.append(
                ForecastDay(
                    forecast_for=target,
                    temp_min_c=round(base - spread, 1),
                    temp_max_c=round(base + spread * 0.6, 1),
                    humidity_percent=round(min(95, 40 + seed * 50), 0),
                    rainfall_mm=rainfall,
                    rainfall_probability_percent=rain_prob,
                    wind_speed_kmh=round(5 + seed * 18, 1),
                    condition_code="rain"
                    if rain_prob > 55
                    else ("clouds" if rain_prob > 30 else "clear"),
                    condition_text="Rain likely"
                    if rain_prob > 55
                    else ("Partly cloudy" if rain_prob > 30 else "Mostly clear"),
                )
            )
        return WeatherForecastResult(days=out, provider=self.name, is_demo=True, retrieved_at=now)

    def alerts(
        self, *, state: str | None = None, district: str | None = None
    ) -> list[WeatherAlertItem]:
        """No alerts are invented. The demo provider returns an empty list and the
        UI displays 'demo provider — no alert feed configured'."""
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            available=True,
            is_demo=True,
            detail="Demo provider: deterministic sample weather derived from place and date, not live data.",
        )


# ---------------------------------------------------------------- openweathermap
class OpenWeatherMapProvider:
    """Real provider. Requires WEATHER_API_KEY; raises ProviderUnavailableError
    when the key is missing or the API fails, so callers can degrade explicitly."""

    name = "openweathermap"
    is_demo = False

    def __init__(self) -> None:
        self.api_key = settings.weather_api_key
        self.base_url = settings.weather_api_base_url.rstrip("/")

    def _require_key(self) -> str:
        if not self.api_key:
            raise ProviderUnavailableError(
                "Live weather is not configured on this deployment.",
                details={"provider": self.name, "missing": ["WEATHER_API_KEY"]},
            )
        return self.api_key

    def _get(self, path: str, params: dict) -> dict:
        key = self._require_key()
        params = {**params, "appid": key, "units": "metric"}
        try:
            response = httpx.get(f"{self.base_url}/{path}", params=params, timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailableError(
                "The weather service rejected the request.",
                details={"provider": self.name, "status": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The weather service could not be reached.", details={"provider": self.name}
            ) from exc
        return response.json()

    def current(self, *, latitude: float, longitude: float) -> WeatherNow:
        payload = self._get("weather", {"lat": latitude, "lon": longitude})
        main = payload.get("main", {})
        wind = payload.get("wind", {})
        rain = payload.get("rain", {})
        weather = (payload.get("weather") or [{}])[0]
        return WeatherNow(
            temperature_c=main.get("temp"),
            feels_like_c=main.get("feels_like"),
            humidity_percent=main.get("humidity"),
            rainfall_mm=rain.get("1h", 0.0),
            wind_speed_kmh=round(wind.get("speed", 0) * 3.6, 1)
            if wind.get("speed") is not None
            else None,
            wind_direction_deg=wind.get("deg"),
            pressure_hpa=main.get("pressure"),
            condition_code=weather.get("main", "unknown").lower(),
            condition_text=weather.get("description", "Unknown").capitalize(),
            observed_at=datetime.fromtimestamp(payload.get("dt", 0), tz=UTC),
            provider=self.name,
            is_demo=False,
            place_label=payload.get("name"),
        )

    def forecast(
        self, *, latitude: float, longitude: float, days: int = 7
    ) -> WeatherForecastResult:
        payload = self._get(
            "forecast", {"lat": latitude, "lon": longitude, "cnt": min(days * 8, 40)}
        )
        buckets: dict[str, dict] = {}
        for entry in payload.get("list", []):
            day_key = entry["dt_txt"][:10]
            bucket = buckets.setdefault(
                day_key,
                {
                    "temps": [],
                    "humidity": [],
                    "rain": 0.0,
                    "pops": [],
                    "wind": [],
                    "codes": [],
                    "texts": [],
                },
            )
            bucket["temps"].append(entry["main"]["temp"])
            bucket["humidity"].append(entry["main"]["humidity"])
            bucket["rain"] += float(entry.get("rain", {}).get("3h", 0.0) or 0.0)
            bucket["pops"].append(entry.get("pop", 0))
            bucket["wind"].append(entry.get("wind", {}).get("speed", 0))
            condition = (entry.get("weather") or [{}])[0]
            bucket["codes"].append(condition.get("main", "unknown").lower())
            bucket["texts"].append(condition.get("description", ""))

        days_out: list[ForecastDay] = []
        for day_key in sorted(buckets)[:days]:
            bucket = buckets[day_key]
            codes = bucket["codes"]
            dominant = max(set(codes), key=codes.count) if codes else "unknown"
            text = bucket["texts"][codes.index(dominant)] if codes else ""
            days_out.append(
                ForecastDay(
                    forecast_for=datetime.fromisoformat(day_key).replace(tzinfo=UTC),
                    temp_min_c=round(min(bucket["temps"]), 1),
                    temp_max_c=round(max(bucket["temps"]), 1),
                    humidity_percent=round(sum(bucket["humidity"]) / len(bucket["humidity"]), 0),
                    rainfall_mm=round(bucket["rain"], 1),
                    rainfall_probability_percent=round(max(bucket["pops"]) * 100, 0),
                    wind_speed_kmh=round(sum(bucket["wind"]) / len(bucket["wind"]) * 3.6, 1),
                    condition_code=dominant,
                    condition_text=text.capitalize(),
                )
            )
        return WeatherForecastResult(
            days=days_out,
            provider=self.name,
            is_demo=False,
            retrieved_at=datetime.now(UTC),
            place_label=payload.get("city", {}).get("name"),
        )

    def alerts(
        self, *, state: str | None = None, district: str | None = None
    ) -> list[WeatherAlertItem]:
        # OpenWeatherMap's free tier has no public alert feed for India; the
        # production design uses IMD via a configured gateway (see docs/deployment.md).
        return []

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            available=bool(self.api_key),
            is_demo=False,
            detail=None if self.api_key else "WEATHER_API_KEY is not set",
        )


def get_weather_provider() -> WeatherProvider:
    if settings.weather_provider == "openweathermap":
        return OpenWeatherMapProvider()
    return MockWeatherProvider()
