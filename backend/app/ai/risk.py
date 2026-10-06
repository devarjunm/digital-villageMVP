"""Rule-based crop risk screening.

This is **not** a machine-learning model and the API labels it accordingly
(`data_class="derived"`, `method="rule_based"`). It combines the farmer's own
records (crop stage, irrigation, soil pH) with weather forecasts to surface
conditions that commonly deserve attention.

Rules are deliberately conservative and each one states the condition that fired,
so a farmer or an extension officer can disagree with the reasoning instead of
being handed an unexplained score. Nothing here is a diagnosis, a yield forecast
or an official advisory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RISK_LEVELS = ("low", "moderate", "high")


@dataclass(slots=True)
class RiskFlag:
    code: str
    level: str
    title: str
    detail: str
    triggered_by: dict[str, Any]
    suggested_action: str


@dataclass(slots=True)
class RiskAssessment:
    level: str
    score: int
    flags: list[RiskFlag] = field(default_factory=list)
    inputs_used: dict[str, Any] = field(default_factory=dict)
    missing_inputs: list[str] = field(default_factory=list)
    method: str = "rule_based_screening_v1"


# Stage-specific vulnerability: young and flowering stages are more sensitive.
SENSITIVE_STAGES = {"sowing", "germination", "transplanting", "flowering", "fruit_set"}


def assess_risk(
    *,
    crop_stage: str | None,
    irrigation_type: str | None,
    soil_ph: float | None,
    forecast: list[dict[str, Any]] | None,
    advisories: list[str] | None = None,
    crop_code: str | None = None,
) -> RiskAssessment:
    """Screen conditions and return explainable flags.

    `forecast` items are plain dicts with the fields the weather module produces
    (temp_min_c, temp_max_c, rainfall_mm, rainfall_probability_percent,
    humidity_percent, wind_speed_kmh, forecast_for).
    """
    flags: list[RiskFlag] = []
    inputs: dict[str, Any] = {
        "crop_stage": crop_stage,
        "irrigation_type": irrigation_type,
        "soil_ph": soil_ph,
        "forecast_days": len(forecast or []),
        "crop_code": crop_code,
    }
    missing: list[str] = []
    if not forecast:
        missing.append("forecast")
    if crop_stage is None:
        missing.append("crop_stage")
    if irrigation_type is None:
        missing.append("irrigation_type")

    days = forecast or []
    stage_is_sensitive = (crop_stage or "").lower() in SENSITIVE_STAGES

    heavy_rain = [d for d in days if (d.get("rainfall_mm") or 0) >= 20]
    if heavy_rain:
        first = heavy_rain[0]
        flags.append(
            RiskFlag(
                code="heavy_rain",
                level="high" if stage_is_sensitive else "moderate",
                title="Heavy rain forecast",
                detail=(
                    f"{first.get('rainfall_mm'):.0f} mm is forecast around "
                    f"{str(first.get('forecast_for'))[:10]}"
                    + (" while the crop is at a sensitive stage." if stage_is_sensitive else ".")
                ),
                triggered_by={
                    "rainfall_mm": first.get("rainfall_mm"),
                    "day": str(first.get("forecast_for"))[:10],
                },
                suggested_action=(
                    "Check field drainage, postpone fertiliser top-dressing and spraying, and secure harvested "
                    "produce."
                ),
            )
        )

    dry_run = 0
    for day in days:
        if (day.get("rainfall_probability_percent") or 0) < 20:
            dry_run += 1
        else:
            dry_run = 0
    if dry_run >= 3:
        level = "high" if irrigation_type in (None, "rainfed") else "moderate"
        flags.append(
            RiskFlag(
                code="dry_spell",
                level=level,
                title="Dry spell",
                detail=f"{dry_run} consecutive days with a low chance of rain in the forecast.",
                triggered_by={"consecutive_dry_days": dry_run, "irrigation_type": irrigation_type},
                suggested_action=(
                    "Plan irrigation and mulch to reduce moisture loss; rainfed plots are most exposed."
                    if irrigation_type in (None, "rainfed")
                    else "Check that scheduled irrigation can cover the dry spell."
                ),
            )
        )

    hot = [d for d in days if (d.get("temp_max_c") or 0) >= 40]
    if hot:
        flags.append(
            RiskFlag(
                code="heat_stress",
                level="high" if stage_is_sensitive else "moderate",
                title="Heat stress conditions",
                detail=f"Maximum temperature is forecast to reach {hot[0].get('temp_max_c'):.0f} °C.",
                triggered_by={"temp_max_c": hot[0].get("temp_max_c")},
                suggested_action="Irrigate in the early morning or evening and protect nursery beds with shade.",
            )
        )

    humid = [d for d in days if (d.get("humidity_percent") or 0) >= 85]
    if humid and stage_is_sensitive:
        flags.append(
            RiskFlag(
                code="humidity_disease_pressure",
                level="moderate",
                title="High humidity during a sensitive stage",
                detail=(
                    "Sustained humidity above 85% during a sensitive stage increases fungal disease pressure."
                ),
                triggered_by={
                    "humidity_percent": humid[0].get("humidity_percent"),
                    "stage": crop_stage,
                },
                suggested_action=(
                    "Scout the canopy for early symptoms and keep foliage dry where practical. This is a "
                    "screening flag, not a diagnosis — confirm symptoms with an expert or a lab."
                ),
            )
        )

    windy = [d for d in days if (d.get("wind_speed_kmh") or 0) >= 25]
    if windy:
        flags.append(
            RiskFlag(
                code="wind",
                level="moderate",
                title="Windy conditions",
                detail=f"Wind speed is forecast to reach {windy[0].get('wind_speed_kmh'):.0f} km/h.",
                triggered_by={"wind_speed_kmh": windy[0].get("wind_speed_kmh")},
                suggested_action=(
                    "Avoid spraying (drift risk), support tall or lodged-prone crops and secure shade nets."
                ),
            )
        )

    if soil_ph is not None and (soil_ph < 5.5 or soil_ph > 8.0):
        flags.append(
            RiskFlag(
                code="soil_ph",
                level="moderate",
                title="Soil pH outside the comfortable range",
                detail=f"Recorded soil pH is {soil_ph}.",
                triggered_by={"soil_ph": soil_ph},
                suggested_action=(
                    "Get a laboratory soil test and discuss a correction plan (liming/gypsum) with your KVK or "
                    "agriculture officer before the next season."
                ),
            )
        )

    score = sum({"low": 10, "moderate": 25, "high": 45}[flag.level] for flag in flags)
    score = min(100, score)
    if score >= 60:
        level = "high"
    elif score >= 25:
        level = "moderate"
    else:
        level = "low"
    if not days:
        level = "unknown"

    return RiskAssessment(
        level=level,
        score=score,
        flags=flags,
        inputs_used=inputs,
        missing_inputs=missing,
    )


def assessment_to_dict(assessment: RiskAssessment) -> dict[str, Any]:
    return {
        "data_class": "derived",
        "method": assessment.method,
        "method_note": (
            "Rule-based screening of your own crop records against the weather forecast. Not a model, not a "
            "diagnosis, and not an official advisory."
        ),
        "level": assessment.level,
        "score": assessment.score,
        "score_interpretation": (
            "The score is the sum of triggered rule weights (low 10, moderate 25, high 45, capped at 100). It is "
            "not a probability that damage will occur."
        ),
        "flags": [
            {
                "code": flag.code,
                "level": flag.level,
                "title": flag.title,
                "detail": flag.detail,
                "triggered_by": flag.triggered_by,
                "suggested_action": flag.suggested_action,
            }
            for flag in assessment.flags
        ],
        "inputs_used": assessment.inputs_used,
        "missing_inputs": assessment.missing_inputs,
        "disclaimer": (
            "This is a screening aid built from your records and the weather forecast. Confirm anything "
            "consequential with your local agriculture officer or Krishi Vigyan Kendra (KVK)."
        ),
    }
