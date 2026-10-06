"""Serving-side yield estimation.

The model is a per-crop regressor trained on documented sample data; it produces a
*relative* estimate with an explicit range, and it refuses to answer outside the
feature envelope it was trained on.

Presentation rules:
  * never a single number without a range;
  * never "guaranteed", never a promise of income — yields depend on weather,
    pests, water, variety and management that no model in this repository sees;
  * the model version, dataset provenance and measured error metrics (from the
    training run) travel with every response.
"""

from __future__ import annotations

from typing import Any

from ai.serving import check_feature_order, load_artifact

MODEL_NAME = "yield-prediction"

# Expected feature order — training writes feature_names.json and serving verifies it.
FEATURE_NAMES = [
    "area_hectares",
    "soil_ph",
    "nitrogen",
    "phosphorus",
    "potassium",
    "rainfall_mm",
    "temperature_mean_c",
    "irrigation_score",
]

BOUNDS: dict[str, tuple[float, float]] = {
    "area_hectares": (0.01, 100.0),
    "soil_ph": (3.5, 10.0),
    "nitrogen": (0.0, 250.0),
    "phosphorus": (0.0, 250.0),
    "potassium": (0.0, 300.0),
    "rainfall_mm": (0.0, 4000.0),
    "temperature_mean_c": (-5.0, 50.0),
    "irrigation_score": (0.0, 1.0),
}

IRRIGATION_SCORES = {
    "drip": 1.0,
    "sprinkler": 0.85,
    "canal": 0.7,
    "borewell": 0.7,
    "open_well": 0.6,
    "rainfed": 0.2,
    "none": 0.2,
    "mixed": 0.6,
}


class YieldPredictionService:
    def __init__(self, *, db: Any | None = None, version: str | None = None) -> None:
        self.db = db
        self.version = version
        self._artifact = None

    def artifact(self):  # noqa: ANN201
        if self._artifact is None:
            self._artifact = load_artifact(MODEL_NAME, db=self.db, version=self.version)
            check_feature_order(self._artifact, FEATURE_NAMES)
        return self._artifact

    def is_installed(self) -> bool:
        try:
            self.artifact()
            return True
        except Exception:  # noqa: BLE001 - availability probe must not raise
            return False

    def predict(
        self,
        *,
        crop_code: str,
        features: dict[str, float],
        area_unit: str = "hectare",
    ) -> dict[str, Any]:
        artifact = self.artifact()
        problems: list[dict[str, str]] = []
        values: dict[str, float] = {}
        for name in FEATURE_NAMES:
            raw = features.get(name)
            if raw is None:
                problems.append({"field": name, "message": "Missing required input."})
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                problems.append({"field": name, "message": "Must be a number."})
                continue
            low, high = BOUNDS[name]
            if not (low <= value <= high):
                problems.append(
                    {
                        "field": name,
                        "message": f"Out of the supported range ({low} – {high}). Check the unit.",
                    }
                )
                continue
            values[name] = value
        if problems:
            from app.core.errors import ValidationError

            raise ValidationError(
                "Yield inputs are outside the model's supported range.",
                details={"problems": problems},
            )

        if crop_code and crop_code not in artifact.classes and artifact.classes:
            from app.core.errors import ValidationError

            raise ValidationError(
                "This crop is not covered by the installed yield model.",
                details={"crop_code": crop_code, "model_crops": artifact.classes},
            )

        matrix = [[values[name] for name in FEATURE_NAMES]]
        estimate = float(artifact.payload.predict(matrix)[0])
        # Interval from the model card's measured error (MAE from training); if the
        # card has none, no interval is reported rather than inventing one.
        mae = _mae_from_card(artifact.card, crop_code)
        lower = upper = None
        if mae is not None:
            lower, upper = max(0.0, estimate - mae), estimate + mae

        return {
            **artifact.presentation(),
            "crop_code": crop_code,
            "unit": "tonnes_per_hectare",
            "estimate": round(estimate, 3),
            "range": {"lower": round(lower, 3), "upper": round(upper, 3)}
            if lower is not None
            else None,
            "range_basis": (
                "Range is estimate ± the mean absolute error measured on the held-out test split "
                "(see metrics in the model card); it is not a formal confidence interval."
                if lower is not None
                else "No measured error was found in the model card, so no range is reported."
            ),
            "inputs_used": values,
            "area_unit_input": area_unit,
            "confidence_interpretation": (
                f"Estimate {estimate:.2f} t/ha"
                + (
                    f" with a measured MAE of {mae:.2f} t/ha."
                    if mae is not None
                    else "."
                )
                + " Yields vary with variety, weather during the season, pest pressure and management — treat "
                "this as planning support, not a forecast."
            ),
        }


def _mae_from_card(card: dict[str, Any], crop_code: str | None) -> float | None:
    metrics = card.get("metrics", {})
    test = metrics.get("test") or metrics
    if crop_code:
        per_crop = test.get("per_crop") or {}
        entry = per_crop.get(crop_code)
        if isinstance(entry, dict) and entry.get("mae") is not None:
            return float(entry["mae"])
    for key in ("mae", "mean_absolute_error"):
        if test.get(key) is not None:
            return float(test[key])
    return None
