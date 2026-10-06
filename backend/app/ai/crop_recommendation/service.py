"""Crop recommendation inference service.

Pipeline: validated inputs → feature assembly (from the request plus the farmer's
farm/soil data) → model inference (scikit-learn pipeline trained in
ai/crop_recommendation/train.py) → ranked recommendations → explanation, ranked
features and limitations.

Honesty rules implemented here:
  * the model version comes from the artefact, never from a constant;
  * scores are returned as `score` with an explicit
    `confidence_interpretation` stating whether they are calibrated probabilities
    (the shipped model reports `predict_proba` from a soft-voting ensemble, which
    is *not* calibrated unless the artefact says so);
  * if no artefact exists the service raises ModelUnavailableError → HTTP 503, so
    the UI shows "model not available" instead of a fabricated recommendation;
  * the response includes the training-data provenance so the caller can see the
    scope (which crops, which features, how many samples).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.ai.registry import load_model_handle
from app.core.contracts import AI_DISCLAIMER
from app.core.errors import ModelUnavailableError, ValidationError
from app.core.logging import get_logger
from app.core.observability import observe_model_call
from app.farms.repository import FarmRepository
from app.users.models import User

logger = get_logger(__name__)
MODEL_NAME = "crop-recommendation"

# Feature contract shared with the training pipeline (ai/crop_recommendation/features.py).
FEATURES = [
    "nitrogen",
    "phosphorus",
    "potassium",
    "temperature_c",
    "humidity_percent",
    "ph",
    "rainfall_mm",
]

# Plausible-input guards. Values outside these ranges are rejected rather than
# silently clipped, because a wrong extreme value would produce a confident but
# meaningless recommendation.
BOUNDS: dict[str, tuple[float, float]] = {
    "nitrogen": (0.0, 200.0),
    "phosphorus": (0.0, 200.0),
    "potassium": (0.0, 250.0),
    "temperature_c": (-10.0, 55.0),
    "humidity_percent": (0.0, 100.0),
    "ph": (0.0, 14.0),
    "rainfall_mm": (0.0, 4000.0),
}


@dataclass(slots=True)
class Recommendation:
    crop_code: str
    crop_name: str
    score: float
    rank: int
    reasons: list[str]


class CropRecommendationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ inputs
    def assemble_features(
        self, *, payload: dict[str, Any], user: User | None, farm_id: Any = None
    ) -> tuple[dict[str, float], dict[str, Any], list[str]]:
        """Merge request values with stored farm/soil data.

        Request values always win; anything filled from the database is reported
        in `sources` so the response explains where each number came from.
        """
        features: dict[str, float] = {}
        sources: dict[str, Any] = {}
        missing_hints: list[str] = []

        farm = None
        if farm_id is not None and user is not None:
            farm = FarmRepository(self.db).get(farm_id)
            if farm is None or (farm.owner_id != user.id and not user.has_role("admin")):
                raise ValidationError("That farm could not be found in your account.")

        soil_test = None
        if farm is not None:
            soil_test = FarmRepository(self.db).latest_soil_test(farm.id)

        for name in FEATURES:
            value = payload.get(name)
            if value is not None:
                sources[name] = "request"
            # Fill only from data the farmer actually recorded, and record which
            # record it came from so the response can explain itself.
            if value is None and farm is not None and name == "ph" and farm.soil_ph is not None:
                value = float(farm.soil_ph)
                sources[name] = "farm.soil_ph (recorded on the farm profile)"
            if value is None and soil_test is not None:
                from_soil_test = {
                    "nitrogen": soil_test.nitrogen_kg_per_ha,
                    "phosphorus": soil_test.phosphorus_kg_per_ha,
                    "potassium": soil_test.potassium_kg_per_ha,
                    "ph": soil_test.ph,
                }.get(name)
                if from_soil_test is not None:
                    value = float(from_soil_test)
                    sources[name] = (
                        f"soil_test.{name} recorded on {soil_test.tested_on.isoformat()}"
                    )
            if value is None:
                missing_hints.append(name)
                continue
            low, high = BOUNDS[name]
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(
                    f"'{name}' must be a number.", details={"field": name, "received": str(value)}
                ) from exc
            if not (low <= numeric <= high):
                raise ValidationError(
                    f"'{name}' is outside the plausible range [{low}, {high}].",
                    details={"field": name, "value": numeric, "range": [low, high]},
                )
            features[name] = numeric
            sources.setdefault(name, "request")
        return features, sources, missing_hints

    # ----------------------------------------------------------------- predict
    def recommend(
        self,
        *,
        payload: dict[str, Any],
        user: User | None = None,
        farm_id: Any = None,
        top_k: int = 3,
        season: str | None = None,
        soil_type: str | None = None,
    ) -> dict[str, Any]:
        handle = load_model_handle(MODEL_NAME, db=self.db)
        features, sources, missing = self.assemble_features(
            payload=payload, user=user, farm_id=farm_id
        )
        if missing:
            raise ValidationError(
                "Some required inputs are missing and could not be filled from your farm data.",
                details={
                    "missing": missing,
                    "hint": "Provide soil N/P/K and pH (a soil test helps) plus local temperature, humidity and rainfall.",
                },
            )

        started = time.perf_counter()
        with observe_model_call(MODEL_NAME, handle.version):
            result = self._run_model(handle, features, top_k=top_k)
        latency_ms = int((time.perf_counter() - started) * 1000)

        crops = {row["code"]: row for row in handle.training_data.get("crops", [])}
        recommendations = []
        for rank, (label, score) in enumerate(result["ranked"], start=1):
            meta = crops.get(label, {})
            recommendations.append(
                Recommendation(
                    crop_code=label,
                    crop_name=meta.get("name_en", label.replace("_", " ").title()),
                    score=score,
                    rank=rank,
                    reasons=self._reasons(features, label, meta),
                ).__dict__
            )

        limitations = [
            "Recommendations are based on the soil and climate inputs listed above; they do not account for "
            "market demand, labour, water availability or your rotation plan.",
            "The model was trained on a fixed set of crops and cannot suggest crops outside that set.",
            "If a value was entered approximately (for example rainfall from memory), the ranking is only as "
            "good as that estimate — a soil test gives far better inputs.",
        ]
        if handle.training_data.get("is_synthetic_sample"):
            limitations.insert(
                0,
                "The bundled model was trained on a documented synthetic sample dataset so the pipeline is "
                "runnable end-to-end; treat its output as a demonstration, not agronomic advice.",
            )
        if missing:
            limitations.append(f"Missing inputs: {', '.join(missing)}")

        return {
            "recommendations": recommendations,
            "inputs": features,
            "input_sources": sources,
            "season": season,
            "soil_type": soil_type,
            "model_name": handle.name,
            "model_version": handle.version,
            "model_framework": handle.framework,
            "model_metrics": handle.metrics,
            "training_data": handle.training_data,
            "confidence_interpretation": result["confidence_interpretation"],
            "score_type": result["score_type"],
            "latency_ms": latency_ms,
            "generated_at": datetime.now(UTC).isoformat(),
            "limitations": limitations,
            "disclaimer": AI_DISCLAIMER,
            "data_class": "model_output",
        }

    def _run_model(self, handle, features: dict[str, float], *, top_k: int) -> dict[str, Any]:
        import joblib
        import numpy as np

        artifact = handle.artifact_dir / "model.joblib"
        if not artifact.exists():
            raise ModelUnavailableError(
                "The crop recommendation artefact is incomplete (model.joblib missing).",
                details={"model": handle.name, "version": handle.version, "path": str(artifact)},
            )
        bundle = joblib.load(artifact)
        pipeline = bundle["pipeline"]
        classes = list(bundle["classes"])
        feature_order = list(bundle.get("features", FEATURES))
        row = np.array([[features[name] for name in feature_order]], dtype=float)

        if hasattr(pipeline, "predict_proba"):
            probabilities = pipeline.predict_proba(row)[0]
        else:  # regressor-style artefact: convert scores to a comparable scale
            raw = np.atleast_1d(pipeline.predict(row)).astype(float)
            if raw.size == 1:
                raw = np.array([raw[0]])
            shifted = raw - raw.min()
            probabilities = (
                shifted / shifted.sum() if shifted.sum() > 0 else np.ones_like(raw) / raw.size
            )
        order = np.argsort(probabilities)[::-1][: max(1, top_k)]
        ranked = [(classes[i], round(float(probabilities[i]), 4)) for i in order]
        calibrated = bool(bundle.get("calibrated", False))
        return {
            "ranked": ranked,
            "score_type": "calibrated_probability" if calibrated else "ensemble_softmax_score",
            "confidence_interpretation": (
                "Scores are class probabilities from a calibrated model."
                if calibrated
                else "Scores are relative model scores from an uncalibrated ensemble: use them to compare "
                "candidates, not as the probability that the crop will succeed."
            ),
        }

    @staticmethod
    def _reasons(features: dict[str, float], crop_code: str, meta: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        preferred = meta.get("preferred") if isinstance(meta, dict) else None
        if isinstance(preferred, dict):
            for key, (low, high) in preferred.items():
                if key in features and low is not None and high is not None:
                    value = features[key]
                    if low <= value <= high:
                        reasons.append(
                            f"{key.replace('_', ' ')} {value:g} is within this crop's usual range ({low:g}–{high:g})."
                        )
                    else:
                        reasons.append(
                            f"{key.replace('_', ' ')} {value:g} is outside this crop's usual range ({low:g}–{high:g}) — "
                            "verify before deciding."
                        )
        if not reasons:
            reasons.append("Ranked by the trained model from the provided soil and climate values.")
        return reasons[:4]
