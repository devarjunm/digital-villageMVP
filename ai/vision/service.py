"""Serving-side crop disease/pest detection from a photo.

Honesty rules baked into this module:

  * the model only ever reports the labels it was trained on — the label set is read
    from the installed model card and returned with every prediction, and an
    untrained crop is reported as "no trained classes" instead of being forced into
    a label;
  * a result is always presented as an AI-assisted observation with a confidence
    range, never as a diagnosis; the API adds "confirm with an expert / KVK" and, for
    pesticide questions, refuses to invent dosages;
  * image quality is checked *before* inference (resolution, blur, exposure) because
    a blurry photo is the most common cause of a wrong result; a poor photo returns a
    quality warning instead of a confident label;
  * if no artefact is installed the service raises `ModelUnavailableError`, and the
    API answers 503 with installation instructions. It never returns a random label.

Two artefact layouts are supported, decided by the model card:
  * `torch`  — `model.pt` (state dict) + `architecture` + `image_size` + `classes`
  * `sklearn` — `model.joblib` expecting flattened, resized image features (used by
    the deterministic baseline so the whole path can be exercised without a GPU).
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any

MODEL_NAME = "disease-detection"

AI_DISCLAIMER = (
    "AI-assisted observation — not a confirmed diagnosis. A photo cannot replace a laboratory test or an "
    "expert's inspection. Confirm before spending money on treatment."
)
FUNGAL_HUMIDITY_NOTE = (
    "If the crop has been exposed to long humid periods, scouting and expert confirmation matter more than "
    "any single photo result."
)


@dataclass(slots=True)
class ImageQuality:
    acceptable: bool
    width: int
    height: int
    brightness: float
    sharpness: float
    problems: list[str]
    warnings: list[str]


def assess_image_quality(
    image_bytes: bytes, *, min_side: int = 300, min_sharpness: float = 60.0
) -> ImageQuality:
    """Cheap, deterministic quality gate.

    Sharpness is the variance of a Laplacian-style edge response (PIL FIND_EDGES is a
    fixed 3x3 kernel), which is enough to reject motion-blurred or out-of-focus
    photos. Thresholds are documented constants, not learned values.
    """
    from PIL import Image, ImageFilter, ImageOps, ImageStat

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return ImageQuality(
            acceptable=False,
            width=0,
            height=0,
            brightness=0.0,
            sharpness=0.0,
            problems=[
                f"The file could not be read as an image ({type(exc).__name__})."
            ],
            warnings=[],
        )

    width, height = image.size
    gray = image.convert("L")
    brightness = float(ImageStat.Stat(gray).mean[0])
    edges = gray.filter(ImageFilter.FIND_EDGES)
    sharpness = float(ImageStat.Stat(edges).var[0])

    problems: list[str] = []
    warnings: list[str] = []
    if min(width, height) < min_side:
        problems.append(
            f"The photo is too small ({width}×{height}px). Take it again with at least {min_side}px on the "
            "shorter side so the leaf texture is visible."
        )
    if sharpness < min_sharpness:
        problems.append(
            "The photo looks blurred. Hold the phone steady, tap to focus on the affected part and avoid "
            "shadows."
        )
    if brightness < 35:
        warnings.append("The photo is quite dark; detail in the shadows may be lost.")
    if brightness > 225:
        warnings.append("The photo looks over-exposed; bright areas may hide symptoms.")
    return ImageQuality(
        acceptable=not problems,
        width=width,
        height=height,
        brightness=round(brightness, 2),
        sharpness=round(sharpness, 2),
        problems=problems,
        warnings=warnings,
    )


class VisionDiseaseService:
    def __init__(self, *, db: Any | None = None, version: str | None = None) -> None:
        self.db = db
        self.version = version
        self._handle = None
        self._model = None

    # ------------------------------------------------------------- artefact
    def handle(self):
        if self._handle is None:
            from app.ai.registry import load_model_handle

            self._handle = load_model_handle(
                MODEL_NAME, version=self.version, db=self.db
            )
        return self._handle

    def card(self) -> dict[str, Any]:
        import json

        path = self.handle().artifact_dir / "model_card.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    def classes(self) -> list[str]:
        card = self.card()
        labels = card.get("classes") or card.get("labels") or []
        if labels:
            return [str(label) for label in labels]
        import json

        path = self.handle().artifact_dir / "labels.json"
        if path.exists():
            return [str(label) for label in json.loads(path.read_text())]
        return []

    def is_trained_for(self, crop_code: str | None) -> tuple[bool, str | None]:
        """Does this model know anything about the given crop?

        The mapping lives in the model card (`crop_labels`), because only the training
        run knows which crops it covers.
        """
        if not crop_code:
            return True, None
        card = self.card()
        mapping = card.get("crop_labels") or {}
        if not mapping:
            return True, None
        if crop_code not in mapping:
            return False, (
                f"The installed model was not trained on {crop_code}. It knows: {', '.join(sorted(mapping))}. "
                "No label will be shown for this crop."
            )
        return True, None

    def _load(self):  # noqa: ANN202
        if self._model is not None:
            return self._model
        import joblib

        card = self.card()
        framework = str(card.get("framework", "unknown")).lower()
        directory = self.handle().artifact_dir
        torch_file = directory / "model.pt"
        sklearn_file = directory / "model.joblib"

        if "torch" in framework and torch_file.exists():
            import torch  # imported lazily: CPU inference only, and optional in dev

            architecture = card.get("architecture")
            if not architecture:
                from app.core.errors import ModelUnavailableError

                raise ModelUnavailableError(
                    "The installed vision model card does not declare an architecture, so it cannot be loaded "
                    "safely.",
                    details={"model_card_keys": sorted(card)[:20]},
                )
            model = _build_torch_model(architecture, classes=len(self.classes()))
            state = torch.load(torch_file, map_location="cpu")
            model.load_state_dict(state)
            model.eval()
            self._model = ("torch", model)
        elif sklearn_file.exists():
            self._model = ("sklearn", joblib.load(sklearn_file))
        else:
            from app.core.errors import ModelUnavailableError

            raise ModelUnavailableError(
                "The installed disease-detection artefact has no loadable model file.",
                details={
                    "artifact_dir": str(directory),
                    "expected": ["model.pt", "model.joblib"],
                },
            )
        return self._model

    # ------------------------------------------------------------ inference
    def detect(
        self,
        *,
        image_bytes: bytes,
        crop_code: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        quality = assess_image_quality(image_bytes)
        card = self.card()
        classes = self.classes()
        trained_for_crop, crop_note = self.is_trained_for(crop_code)

        result: dict[str, Any] = {
            "data_class": "model_output",
            "model_name": self.handle().name,
            "model_version": self.handle().version,
            "model_trained_classes": classes,
            "training_data": card.get("dataset", {}),
            "is_demo_dataset": bool(
                card.get("dataset", {}).get("is_synthetic_sample", False)
            ),
            "image_quality": {
                "acceptable": quality.acceptable,
                "width": quality.width,
                "height": quality.height,
                "brightness": quality.brightness,
                "sharpness": quality.sharpness,
                "problems": quality.problems,
                "warnings": quality.warnings,
            },
            "crop_code": crop_code,
            "crop_coverage_note": crop_note,
            "disclaimer": AI_DISCLAIMER,
            "latency_ms": 0,
        }

        if not quality.acceptable:
            result.update(
                {
                    "predictions": [],
                    "confidence": None,
                    "confidence_interpretation": "No prediction was made: the photo did not pass the quality check.",
                    "inconclusive": True,
                    "quality_gate_failed": True,
                    "recommendation": (
                        "Retake the photo in good light, filling the frame with one affected leaf or plant part."
                    ),
                }
            )
            result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return result

        if not trained_for_crop:
            result.update(
                {
                    "predictions": [],
                    "confidence": None,
                    "confidence_interpretation": "No prediction was made for this crop.",
                    "inconclusive": True,
                    "recommendation": (
                        "This crop is not covered by the installed model. Upload a photo in the community and "
                        "tag an expert, or contact your local KVK."
                    ),
                }
            )
            result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return result

        if not classes:
            result.update(
                {
                    "predictions": [],
                    "confidence": None,
                    "confidence_interpretation": "The installed model declares no label set.",
                    "inconclusive": True,
                    "recommendation": "The model artefact is incomplete; an administrator must reinstall it.",
                }
            )
            result["latency_ms"] = int((time.perf_counter() - started) * 1000)
            return result

        probabilities, predicted_labels = self._predict(
            image_bytes, class_labels=classes, card=card
        )
        ranked = sorted(
            zip(probabilities, predicted_labels), key=lambda pair: -pair[0]
        )[: max(1, top_k)]
        calibrated = bool(card.get("calibration", {}).get("calibrated", False))
        top_score = float(ranked[0][0])
        result.update(
            {
                "predictions": [
                    {
                        "label": label,
                        "score": round(float(score), 4),
                        "score_display": round(float(score) * 100, 1),
                        "rank": index,
                    }
                    for index, (score, label) in enumerate(ranked, start=1)
                ],
                "score_type": "calibrated_probability"
                if calibrated
                else "relative_model_score",
                "confidence": top_score,
                "confidence_interpretation": (
                    f"Top label '{ranked[0][1]}' scored {top_score:.2f}. "
                    + (
                        "Scores are relative model scores, not probabilities."
                        if not calibrated
                        else "Scores come from a calibration step recorded in the model card."
                    )
                    + (
                        " The top two labels are close, so treat this as inconclusive between them."
                        if len(ranked) > 1 and top_score - float(ranked[1][0]) < 0.15
                        else ""
                    )
                ),
                "inconclusive": top_score < 0.55,
                "recommendation": (
                    "Treat this as a starting point: confirm the symptom on several plants, and share photos in "
                    "the community for an expert opinion. If the crop is at a sensitive stage or the spread is "
                    "fast, contact your local agriculture officer or KVK."
                ),
                "extra_context": [FUNGAL_HUMIDITY_NOTE]
                if (card.get("humidity_note", True))
                else [],
            }
        )
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    def _predict(
        self, image_bytes: bytes, *, class_labels: list[str], card: dict[str, Any]
    ) -> tuple[list[float], list[str]]:
        kind, model = self._load()
        image_size = int(card.get("image_size", 128))
        if kind == "torch":
            import numpy as np
            import torch
            from PIL import Image, ImageOps

            image = ImageOps.exif_transpose(
                Image.open(io.BytesIO(image_bytes))
            ).convert("RGB")
            image = image.resize((image_size, image_size))
            array = np.asarray(image, dtype="float32") / 255.0
            tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
            with torch.no_grad():
                logits = model(tensor)
                probabilities = torch.softmax(logits, dim=1)[0].tolist()
            return probabilities, class_labels

        import numpy as np
        from PIL import Image, ImageOps

        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert(
            "RGB"
        )
        image = image.resize((image_size, image_size))
        features = (np.asarray(image, dtype="float32") / 255.0).reshape(1, -1)
        probabilities = model.predict_proba(features)[0].tolist()
        labels = [str(label) for label in getattr(model, "classes_", class_labels)]
        return probabilities, labels


def _build_torch_model(architecture: str, *, classes: int):  # noqa: ANN202
    """Small CNN used by the training pipeline (ai/vision/train.py).

    Kept here as well so serving and training cannot drift; the architecture string
    is stored in the model card and validated on load.
    """
    import torch.nn as nn

    if architecture != "small_cnn_v1":
        from app.core.errors import ModelUnavailableError

        raise ModelUnavailableError(
            f"Unknown vision architecture '{architecture}' in the model card; refusing to guess a network.",
        )

    class SmallCNN(nn.Module):
        def __init__(self, num_classes: int) -> None:
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(3, 24, 3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Conv2d(24, 48, 3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.Conv2d(48, 96, 3, padding=1),
                nn.ReLU(),
                nn.MaxPool2d(2),
                nn.AdaptiveAvgPool2d(1),
            )
            self.classifier = nn.Linear(96, num_classes)

        def forward(self, x):  # noqa: ANN001
            return self.classifier(self.features(x).flatten(1))

    return SmallCNN(num_classes=classes)
