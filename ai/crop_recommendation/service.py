"""Serving-side crop recommendation.

The training pipeline (train.py) writes an artefact directory containing
`model.joblib`, `feature_names.json`, `metrics.json` and `model_card.json`. This
module loads that artefact through the application model registry and exposes an
explicit, well-labelled inference API.

Presenting the output honestly is part of the contract:

  * scores are the model's own scores. They are only described as probabilities
    when the model card records that a calibration step was applied; otherwise
    `score_type` says `relative_model_score` and the interpretation text says so;
  * out-of-range or implausible inputs are rejected with reasons instead of being
    clipped, so the model is never asked a question it was not trained for;
  * missing soil-test values are filled from documented soil-type lookup defaults
    only when the caller asks for it, and every filled value is reported in
    `input_sources` so a farmer/advisor can see it was not measured;
  * the result always carries the model version, the training-data provenance and
    the standard AI disclaimer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ai.crop_recommendation.features import (
    FEATURE_NAMES,
    FEATURE_RANGES,
    FEATURE_SPECS,
    SAMPLE_CROPS,
)

MODEL_NAME = "crop-recommendation"

# Agronomic sanity limits, narrower than the raw feature ranges: values outside
# these are almost certainly unit mistakes (e.g. rainfall in cm, pH as %).
SANITY_LIMITS: dict[str, tuple[float, float]] = {
    "nitrogen": (0, 200),
    "phosphorus": (0, 200),
    "potassium": (0, 250),
    "temperature_c": (-5, 50),
    "humidity_percent": (5, 100),
    "ph": (3.0, 10.5),
    "rainfall_mm": (0, 4000),
}

# Indicative soil-type defaults (kg/ha) used ONLY when a soil test is
# unavailable and the caller opted in. These are coarse national-level textbook
# figures; they are reported as `soil_type_default` and never as measurements.
SOIL_TYPE_DEFAULTS: dict[str, dict[str, float]] = {
    "sandy": {"nitrogen": 40, "phosphorus": 25, "potassium": 45, "ph": 6.8},
    "sandy_loam": {"nitrogen": 55, "phosphorus": 30, "potassium": 55, "ph": 6.8},
    "loam": {"nitrogen": 70, "phosphorus": 35, "potassium": 65, "ph": 6.6},
    "clay_loam": {"nitrogen": 80, "phosphorus": 40, "potassium": 75, "ph": 6.8},
    "clay": {"nitrogen": 85, "phosphorus": 40, "potassium": 80, "ph": 7.0},
    "black": {"nitrogen": 75, "phosphorus": 35, "potassium": 85, "ph": 7.2},
    "red": {"nitrogen": 50, "phosphorus": 30, "potassium": 60, "ph": 6.3},
    "alluvial": {"nitrogen": 75, "phosphorus": 40, "potassium": 70, "ph": 6.9},
    "laterite": {"nitrogen": 45, "phosphorus": 25, "potassium": 50, "ph": 5.8},
    "saline": {"nitrogen": 60, "phosphorus": 30, "potassium": 65, "ph": 8.2},
}

AI_DISCLAIMER = (
    "AI-assisted result — not a confirmed agronomic recommendation. It is produced by a model trained on a "
    "sample dataset and does not account for your local soil test report, water availability, market demand, "
    "rotation history or labour. Discuss it with your local Krishi Vigyan Kendra (KVK) or agriculture officer "
    "before making a planting decision."
)

LIMITATIONS: tuple[str, ...] = (
    "This model was trained on a synthetic sample dataset derived from textbook agronomic envelopes; it has "
    "not been trained or validated on regional field data.",
    "Scores are relative model scores, not calibrated probabilities (see the model card 'calibration' block).",
    "The model returns only the crops present in its training label set; an unlisted crop can never appear.",
    "Market price, water availability, labour, seed availability and rotation are not model inputs.",
)


class InputValidationError(ValueError):
    def __init__(self, problems: list[dict[str, Any]]) -> None:
        self.problems = problems
        super().__init__("; ".join(f"{p['field']}: {p['message']}" for p in problems))


@dataclass(slots=True)
class PreparedInputs:
    values: dict[str, float]
    input_sources: dict[str, str]
    warnings: list[str]


def validate_inputs(
    inputs: dict[str, Any],
    *,
    soil_type: str | None = None,
    allow_soil_type_defaults: bool = True,
) -> PreparedInputs:
    """Validate and complete the feature vector.

    Rejects (never silently clips) values outside the documented plausible range,
    and records where each value came from.
    """
    problems: list[dict[str, Any]] = []
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    warnings: list[str] = []

    for name in FEATURE_NAMES:
        raw = inputs.get(name)
        if raw is None or raw == "":
            if (
                name in ("nitrogen", "phosphorus", "potassium", "ph")
                and allow_soil_type_defaults
            ):
                key = (soil_type or "").strip().lower()
                defaults = SOIL_TYPE_DEFAULTS.get(key)
                if defaults and name in defaults:
                    values[name] = float(defaults[name])
                    sources[name] = "soil_type_default"
                    continue
                problems.append(
                    {
                        "field": name,
                        "message": (
                            "Missing. Provide a soil test value, or send soil_type to use the documented "
                            "soil-type defaults (which will be labelled as estimates)."
                        ),
                    }
                )
                continue
            problems.append({"field": name, "message": "Missing required input."})
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            problems.append({"field": name, "message": "Must be a number."})
            continue
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            problems.append({"field": name, "message": "Must be a finite number."})
            continue
        low, high = SANITY_LIMITS.get(name, FEATURE_RANGES[name])
        if not (low <= value <= high):
            spec = next((s for s in FEATURE_SPECS if s.name == name), None)
            unit = f" {spec.unit}" if spec and spec.unit not in {"pH"} else ""
            problems.append(
                {
                    "field": name,
                    "message": f"Out of plausible range ({low}–{high}{unit}). Check the unit before retrying.",
                }
            )
            continue
        values[name] = value
        sources[name] = "provided"

    if problems:
        raise InputValidationError(problems)

    if any(source == "soil_type_default" for source in sources.values()):
        warnings.append(
            "Some soil values were not measured: they come from documented soil-type lookup defaults and are "
            "labelled as estimates. A soil test will make this result more reliable."
        )
    if values["ph"] < 5.0 or values["ph"] > 8.5:
        warnings.append(
            "Soil pH is outside the range most field crops tolerate well; a laboratory soil test and a "
            "correction plan are recommended before planting."
        )
    if values["rainfall_mm"] < 20 and values["humidity_percent"] < 30:
        warnings.append(
            "Very low rainfall and humidity were entered: irrigation availability is not a model input, so "
            "confirm water supply before relying on this ranking."
        )
    return PreparedInputs(values=values, input_sources=sources, warnings=warnings)


class CropRecommendationService:
    """Thin wrapper around the trained pipeline with honest presentation rules."""

    def __init__(self, *, db: Any | None = None, version: str | None = None) -> None:
        self.db = db
        self.version = version
        self._pipeline = None
        self._handle = None
        self._classes: list[str] = []
        self._calibrated: bool | None = None

    # ------------------------------------------------------------- artefact
    def handle(self):
        if self._handle is None:
            from app.ai.registry import load_model_handle

            self._handle = load_model_handle(
                MODEL_NAME, version=self.version, db=self.db
            )
        return self._handle

    def pipeline(self):
        """The fitted estimator, unwrapped from the artefact bundle.

        `model.joblib` stores a **bundle**, written by
        `ai/crop_recommendation/train.py`:

            {"pipeline": <estimator>, "classes": [...], "features": [...],
             "calibrated": False}

        Keeping the estimator inside a bundle means the label order and the
        calibration flag travel with the weights. Older artefacts may contain the
        bare estimator, so both shapes are accepted; anything else is refused with
        an actionable message instead of failing deep inside predict_proba().
        """
        if self._pipeline is None:
            import joblib

            handle = self.handle()
            model_file = handle.artifact_dir / "model.joblib"
            if not model_file.exists():
                from app.core.errors import ModelUnavailableError

                raise ModelUnavailableError(
                    "The installed crop-recommendation artefact is incomplete (model.joblib missing).",
                    details={"artifact_dir": str(handle.artifact_dir)},
                )
            loaded = joblib.load(model_file)
            if isinstance(loaded, dict):
                bundle = loaded
                estimator = (
                    bundle.get("pipeline")
                    or bundle.get("model")
                    or bundle.get("estimator")
                )
                if estimator is None or not hasattr(estimator, "predict_proba"):
                    from app.core.errors import ModelUnavailableError

                    raise ModelUnavailableError(
                        "The installed crop-recommendation bundle does not contain a usable estimator "
                        "(expected a 'pipeline' entry with predict_proba).",
                        details={
                            "artifact_dir": str(handle.artifact_dir),
                            "bundle_keys": sorted(bundle),
                        },
                    )
                if bundle.get("features") and list(bundle["features"]) != list(
                    FEATURE_NAMES
                ):
                    from app.core.errors import ModelUnavailableError

                    raise ModelUnavailableError(
                        "Feature mismatch between the installed model and this code version; refusing to serve.",
                        details={
                            "model_features": bundle["features"],
                            "expected": FEATURE_NAMES,
                        },
                    )
                self._calibrated = bool(bundle.get("calibrated", False))
                self._pipeline = estimator
            else:
                if not hasattr(loaded, "predict_proba"):
                    from app.core.errors import ModelUnavailableError

                    raise ModelUnavailableError(
                        "The installed crop-recommendation artefact does not expose predict_proba(); refusing to serve.",
                        details={
                            "artifact_dir": str(handle.artifact_dir),
                            "loaded_type": type(loaded).__name__,
                        },
                    )
                self._calibrated = False
                self._pipeline = loaded
        return self._pipeline

    def is_calibrated(self) -> bool:
        """Whether calibration is *recorded* for the artefact actually in use.

        The API uses this to choose between "probability" and "relative model
        score" wording, so the answer is deliberately conservative: it comes from
        the loaded artefact's own metadata first (which is what is being served),
        then from `model_card.json`, and defaults to False. An artefact of unknown
        provenance is never presented as calibrated.

        There is exactly one definition of this method — an earlier duplicate
        `@property` shadowed it and silently read only the model card.
        """
        if self._calibrated is None:
            self.pipeline()  # populates _calibrated as a side effect
        if self._calibrated is None:
            card = self.model_card_json()
            self._calibrated = bool(
                (card.get("calibration") or {}).get("calibrated", False)
            )
        return bool(self._calibrated)

    def feature_order(self) -> list[str]:
        """The input order the installed pipeline was trained with.

        `feature_names.json` has two accepted shapes, because the artefact is also
        the place where documented reference ranges live:

            ["nitrogen", "phosphorus", ...]                        (plain list)
            {"features": [...], "crops": {...}}                    (annotated)

        Either way, the recorded order must match this code exactly. If it does
        not, the model is refused: feeding a pipeline its features in the wrong
        order produces confident nonsense, which is worse than an error.
        """
        import json

        handle = self.handle()
        order_file = handle.artifact_dir / "feature_names.json"
        if not order_file.exists():
            return FEATURE_NAMES
        try:
            recorded = json.loads(order_file.read_text())
        except json.JSONDecodeError as exc:
            from app.core.errors import ModelUnavailableError

            raise ModelUnavailableError(
                "The installed crop-recommendation artefact has an unreadable feature list "
                "(feature_names.json is not valid JSON); refusing to serve.",
                details={"artifact_dir": str(handle.artifact_dir)},
            ) from exc
        features = recorded.get("features") if isinstance(recorded, dict) else recorded
        if (
            isinstance(features, dict)
            or features is None
            or list(features) != list(FEATURE_NAMES)
        ):
            from app.core.errors import ModelUnavailableError

            raise ModelUnavailableError(
                "Feature mismatch between the installed model and this code version; refusing to serve.",
                details={"model_features": features, "expected": FEATURE_NAMES},
            )
        return FEATURE_NAMES

    def classes(self) -> list[str]:
        if not self._classes:
            pipeline = self.pipeline()
            classes = list(getattr(pipeline, "classes_", []))
            if not classes and hasattr(pipeline, "named_steps"):
                classes = list(
                    getattr(
                        pipeline.named_steps[list(pipeline.named_steps)[-1]],
                        "classes_",
                        [],
                    )
                )
            self._classes = [str(item) for item in classes]
        return self._classes

    def model_card_json(self) -> dict[str, Any]:
        """The raw model_card.json written by training (source of truth for
        calibration/provenance statements, which live outside `metrics`)."""
        import json

        path = self.handle().artifact_dir / "model_card.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    def metadata(self) -> dict[str, Any]:
        handle = self.handle()
        card = self.model_card_json() or handle.model_card
        return {
            "model_name": handle.name,
            "model_version": handle.version,
            "framework": handle.framework,
            "task": handle.task,
            "trained_at": card.get("trained_at"),
            "selected_model": card.get("selected_model"),
            "classes": self.classes(),
            "metrics": handle.metrics.get("test") or handle.metrics,
            "calibration": card.get(
                "calibration",
                {"calibrated": False, "note": "No calibration step recorded."},
            ),
            "dataset": card.get("dataset", handle.training_data),
            "mlflow_run_id": handle.mlflow_run_id,
            "artifact_dir": str(handle.artifact_dir),
            "disclaimer": AI_DISCLAIMER,
            "limitations": list(LIMITATIONS),
        }

    # ------------------------------------------------------------ inference
    def recommend(
        self,
        *,
        inputs: dict[str, Any],
        top_k: int = 3,
        soil_type: str | None = None,
        allow_soil_type_defaults: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        prepared = validate_inputs(
            inputs,
            soil_type=soil_type,
            allow_soil_type_defaults=allow_soil_type_defaults,
        )
        order = self.feature_order()
        matrix = [[prepared.values[name] for name in order]]
        pipeline = self.pipeline()
        probabilities = pipeline.predict_proba(matrix)[0]
        classes = self.classes()
        ranked = sorted(
            (
                {"crop_code": code, "score": float(score)}
                for code, score in zip(classes, probabilities)
            ),
            key=lambda item: item["score"],
            reverse=True,
        )[: max(1, top_k)]

        for rank, item in enumerate(ranked, start=1):
            crop = SAMPLE_CROPS.get(item["crop_code"], {})
            item.update(
                {
                    "rank": rank,
                    "name_en": crop.get("name_en", item["crop_code"]),
                    "name_mr": crop.get("name_mr"),
                    "name_hi": crop.get("name_hi"),
                    "score_display": round(item["score"] * 100, 1),
                    "typical_envelope": {
                        key: list(value)
                        for key, value in (crop.get("preferred") or {}).items()
                    },
                    "envelope_note": (
                        "Documented typical envelope used to generate the sample training data. It is context, "
                        "not the model's explanation for this ranking."
                    ),
                }
            )

        margin = None
        if len(ranked) >= 2:
            margin = round(ranked[0]["score"] - ranked[1]["score"], 4)
        calibrated = self.is_calibrated()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "data_class": "model_output",
            "is_demo_dataset": bool(
                self.handle().training_data.get("is_synthetic_sample", False)
            ),
            "model_name": self.handle().name,
            "model_version": self.handle().version,
            "score_type": "calibrated_probability"
            if calibrated
            else "relative_model_score",
            "score_type_note": (
                "Scores are the uncalibrated output of the trained model and are comparable only within this "
                "single response. They are not probabilities."
                if not calibrated
                else "Scores come from a calibration step recorded in the model card."
            ),
            "confidence_interpretation": (
                f"Top choice {ranked[0]['name_en']} scored {ranked[0]['score']:.3f}"
                + (
                    f", only {margin:.3f} ahead of {ranked[1]['name_en']} — treat these as close alternatives."
                    if margin is not None and margin < 0.15
                    else "."
                )
            ),
            "top_margin": margin,
            "ranked": ranked,
            "inputs_used": prepared.values,
            "input_sources": prepared.input_sources,
            "input_units": {spec.name: spec.unit for spec in FEATURE_SPECS},
            "warnings": prepared.warnings,
            "limitations": list(LIMITATIONS),
            "disclaimer": AI_DISCLAIMER,
            "latency_ms": latency_ms,
        }

    # ----------------------------------------------------------- evaluation
    def evaluate_on_holdout(self, *, samples_per_crop: int = 220) -> dict[str, Any]:
        """Re-evaluate the installed model on the deterministic held-out split.

        Used by the `model_evaluation` background job so production monitoring can
        see whether the artefact in the registry still behaves as reported.
        """
        import numpy as np

        from ai.crop_recommendation.dataset import (
            build_sample_dataset,
            dataset_fingerprint,
            load_real_dataset,
        )
        from ai.training_utils import classification_metrics, make_splits

        dataset_path = __import__("os").environ.get("CROP_REC_DATASET_PATH")
        dataset = (
            load_real_dataset(dataset_path)
            if dataset_path
            else build_sample_dataset(samples_per_crop=samples_per_crop)
        )
        order = self.feature_order()
        X = np.array(
            [[row[name] for name in order] for row in dataset.rows], dtype=float
        )
        y = np.array(dataset.labels)
        splits = make_splits(X, y, test_size=0.2, val_size=0.1, seed=42, stratify=True)
        pipeline = self.pipeline()
        predictions = pipeline.predict(splits.X_test)
        metrics = classification_metrics(
            splits.y_test, predictions, labels=sorted(set(dataset.labels))
        )
        metrics.pop("confusion_matrix", None)
        return {
            "model_name": self.handle().name,
            "model_version": self.handle().version,
            "evaluation_type": "holdout_recheck",
            "dataset_version": dataset.version,
            "dataset_fingerprint": dataset_fingerprint(dataset),
            "sample_count": int(len(splits.y_test)),
            "metrics": metrics,
            "is_synthetic_sample": dataset.is_synthetic,
            "notes": (
                "Recomputed on the deterministic test split with the same seed as training; small deviations "
                "from the training report indicate library version drift."
            ),
        }
