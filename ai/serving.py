"""Shared serving helpers for the agricultural ML models.

Everything the model services need in common:

  * resolve an installed artefact through the application registry and raise
    `ModelUnavailableError` with *actionable* instructions when it is missing;
  * load the sklearn/torch payload with the verification the model card asks for;
  * apply documented feature-order and bounds checks so a model is never fed a
    vector it was not trained for;
  * turn raw scores into an honest presentation block (`score_type`,
    `confidence_interpretation`, limitations, disclaimer).

Nothing here fabricates a prediction: if the artefact is missing, the caller gets an
error and the API returns 503 with the training command to run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import ModelUnavailableError

TRAIN_COMMANDS = {
    "crop-recommendation": "python -m ai.crop_recommendation.train --register",
    "disease-detection": "python -m ai.vision.train --register",
    "yield-prediction": "python -m ai.yield_prediction.train --register",
    "price-prediction": "python -m ai.price_prediction.train --register",
}


@dataclass(slots=True)
class LoadedArtifact:
    name: str
    version: str
    directory: Path
    card: dict[str, Any]
    payload: Any
    features: list[str]
    classes: list[str]

    @property
    def calibrated(self) -> bool:
        return bool(self.card.get("calibration", {}).get("calibrated", False))

    @property
    def is_synthetic_training_data(self) -> bool:
        return bool(self.card.get("dataset", {}).get("is_synthetic_sample", False))

    def presentation(self, *, data_class: str = "model_output") -> dict[str, Any]:
        return {
            "data_class": data_class,
            "model_name": self.name,
            "model_version": self.version,
            "framework": self.card.get("framework"),
            "task": self.card.get("task"),
            "score_type": "calibrated_probability"
            if self.calibrated
            else "relative_model_score",
            "score_type_note": (
                "Scores are the model's own outputs and are comparable only within one response; they are not "
                "probabilities."
                if not self.calibrated
                else "Scores come from a calibration step recorded in the model card."
            ),
            "is_demo_dataset": self.is_synthetic_training_data,
            "dataset": self.card.get("dataset", {}),
            "metrics": self.card.get("metrics", {}),
            "limitations": self.card.get("known_limitations", []),
            "disclaimer": self.card.get("disclaimer")
            or "AI-assisted result — not a verified prediction. Confirm important decisions with a professional.",
        }


def load_artifact(
    name: str,
    *,
    db: Any | None = None,
    version: str | None = None,
    require_model_file: str = "model.joblib",
) -> LoadedArtifact:
    from app.ai.registry import load_model_handle

    handle = load_model_handle(name, version=version, db=db)
    directory = handle.artifact_dir
    card_path = directory / "model_card.json"
    if not card_path.exists():
        raise ModelUnavailableError(
            f"The installed artefact for '{name}' has no model_card.json, so its provenance cannot be verified.",
            details={
                "artifact_dir": str(directory),
                "how_to_fix": f"Re-export the model: {TRAIN_COMMANDS.get(name, 'see docs/ml.md')}",
            },
        )
    card = json.loads(card_path.read_text())
    model_path = directory / require_model_file
    if not model_path.exists():
        raise ModelUnavailableError(
            f"The installed artefact for '{name}' is missing {require_model_file}.",
            details={
                "artifact_dir": str(directory),
                "how_to_fix": f"Re-export the model: {TRAIN_COMMANDS.get(name, 'see docs/ml.md')}",
            },
        )

    import joblib

    payload = (
        joblib.load(model_path) if require_model_file.endswith(".joblib") else None
    )
    features_path = directory / "feature_names.json"
    features = (
        json.loads(features_path.read_text())
        if features_path.exists()
        else card.get("features", [])
    )
    return LoadedArtifact(
        name=handle.name,
        version=handle.version,
        directory=directory,
        card=card,
        payload=payload,
        features=list(features),
        classes=[str(label) for label in (card.get("classes") or [])],
    )


def missing_model_response(name: str, *, reason: str | None = None) -> dict[str, Any]:
    """Body returned when a model is not installed yet (HTTP 503 payload shape)."""
    return {
        "error": "model_unavailable",
        "code": "model_unavailable",
        "model": name,
        "message": reason
        or (
            f"No trained '{name}' model is installed on this deployment, so no prediction can be made. "
            "The endpoint will start returning results as soon as a model artefact is installed."
        ),
        "how_to_install": TRAIN_COMMANDS.get(name),
        "docs": "docs/ml.md",
    }


def check_feature_order(artifact: LoadedArtifact, expected: list[str]) -> None:
    if artifact.features and list(artifact.features) != list(expected):
        raise ModelUnavailableError(
            "Feature mismatch between the installed model and this code version; refusing to serve.",
            details={"model_features": artifact.features, "expected": expected},
        )


def in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]
