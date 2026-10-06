"""Serving-side price forecasting.

Rules enforced here:

  * the model consumes **observed** price history only (``MarketService`` returns
    observed rows and a flag saying whether that history is demo data);
  * at least `MIN_HISTORY_DAYS` observations are required — a forecast from five
    points would be noise presented as insight;
  * the response always includes the horizon, the history window, the direction
    signal it was combined with, and the fact that commodity prices are affected by
    arrivals, policy and demand that this model does not observe;
  * a forecast is stored as an *estimate* row (``is_estimate=True``) so it can never
    be mistaken for an observed mandi price.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ai.serving import load_artifact

MODEL_NAME = "price-prediction"
MIN_HISTORY_DAYS = 21
FEATURE_NAMES = [
    "lag_1",
    "lag_7",
    "rolling_mean_7",
    "rolling_mean_21",
    "day_of_year_sin",
    "day_of_year_cos",
    "trend_7",
]


class PriceForecastService:
    def __init__(self, *, db: Any, version: str | None = None) -> None:
        self.db = db
        self.version = version
        self._artifact = None

    def artifact(self):  # noqa: ANN201
        if self._artifact is None:
            self._artifact = load_artifact(MODEL_NAME, db=self.db, version=self.version)
        return self._artifact

    def is_installed(self) -> bool:
        try:
            self.artifact()
            return True
        except Exception:  # noqa: BLE001
            return False

    def forecast(
        self, *, crop_code: str, market_code: str | None, horizon_days: int
    ) -> dict[str, Any]:
        from app.core.errors import ValidationError
        from app.markets.service import MarketService

        market = MarketService(self.db)
        history, dates, is_demo_history = market.price_history_for_model(
            crop_code=crop_code, market_code=market_code, days=365
        )
        if len(history) < MIN_HISTORY_DAYS:
            raise ValidationError(
                "Not enough observed price history to forecast.",
                details={
                    "crop_code": crop_code,
                    "market_code": market_code,
                    "observed_points": len(history),
                    "required_points": MIN_HISTORY_DAYS,
                    "how_to_fix": (
                        "Import more mandi history for this crop/market (see docs/data.md) or pick a market "
                        "with a longer series."
                    ),
                },
            )

        artifact = self.artifact()
        if crop_code not in (artifact.classes or [crop_code]) and artifact.classes:
            raise ValidationError(
                "This crop is not covered by the installed price model.",
                details={"crop_code": crop_code, "model_crops": artifact.classes},
            )

        per_crop_metrics = (artifact.card.get("metrics", {}).get("per_crop") or {}).get(
            crop_code, {}
        )
        points: list[dict[str, Any]] = []
        series = list(history)
        working_dates = list(dates)
        for step in range(1, horizon_days + 1):
            target = (working_dates[-1] if working_dates else date.today()) + timedelta(
                days=1
            )
            features = _features(series, target)
            predicted = float(artifact.payload.predict([features])[0])
            points.append(
                {
                    "for_date": target.isoformat(),
                    "predicted_modal_price": round(predicted, 2),
                    "lower": (
                        round(max(0.0, predicted - per_crop_metrics.get("mae", 0.0)), 2)
                        if per_crop_metrics.get("mae") is not None
                        else None
                    ),
                    "upper": (
                        round(predicted + per_crop_metrics["mae"], 2)
                        if per_crop_metrics.get("mae") is not None
                        else None
                    ),
                    "step": step,
                }
            )
            series.append(predicted)
            working_dates.append(target)

        # Persist as an estimate row so it is queryable later and never confused
        # with an observed price.
        market.save_estimate(
            crop_code=crop_code,
            market_code=market_code,
            state=None,
            price_date=working_dates[-1],
            modal_price=points[-1]["predicted_modal_price"],
            lower=points[-1]["lower"],
            upper=points[-1]["upper"],
            model_name=artifact.name,
            model_version=artifact.version,
        )

        return {
            **artifact.presentation(data_class="model_output"),
            "crop_code": crop_code,
            "market_code": market_code,
            "horizon_days": horizon_days,
            "unit": "INR_per_quintal",
            "points": points,
            "history": {
                "observed_points": len(history),
                "first_date": dates[0].isoformat() if dates else None,
                "last_date": dates[-1].isoformat() if dates else None,
                "is_demo_history": is_demo_history,
                "notice": (
                    "Price history used for this forecast came from the demo provider; the forecast is therefore "
                    "a demonstration, not market information."
                    if is_demo_history
                    else None
                ),
            },
            "confidence_interpretation": (
                "Each point is a model estimate. Arrivals, policy announcements, export rules and demand shocks "
                "are not inputs, so horizon accuracy degrades quickly — treat day 1 as the most reliable point."
            ),
            "disclaimer": (
                "AI-assisted price estimate — not a market guarantee and not mandi data. Do not sell on the "
                "basis of this alone; check live mandi prices and local buyers."
            ),
        }


def _features(series: list[float], target: date) -> list[float]:
    import math

    lag_1 = series[-1]
    lag_7 = series[-7] if len(series) >= 7 else series[0]
    mean_7 = sum(series[-7:]) / min(7, len(series))
    mean_21 = sum(series[-21:]) / min(21, len(series))
    doy = target.timetuple().tm_yday
    trend_7 = lag_1 - (series[-8] if len(series) >= 8 else series[0])
    return [
        lag_1,
        lag_7,
        mean_7,
        mean_21,
        math.sin(2 * math.pi * doy / 365),
        math.cos(2 * math.pi * doy / 365),
        trend_7,
    ]
