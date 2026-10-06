"""Dataset builder for the crop-recommendation sample model.

IMPORTANT — provenance and honesty:

There is no single openly licensed, free-to-redistribute dataset that maps
(N, P, K, temperature, humidity, pH, rainfall) → crop recommendation for Indian
conditions. The widely circulated "Crop Recommendation" dataset on Kaggle is
derived from a 2017 study and its redistribution terms are unclear, so it is NOT
bundled here.

What this module does instead:

  * `build_sample_dataset()` generates a **synthetic** dataset from the documented
    agronomic envelopes in `features.SAMPLE_CROPS` (a wide, textbook range per
    crop) plus correlated noise. It exists so the full ML path — training,
    evaluation, export, serving, monitoring — is runnable and testable end to end.
  * `load_real_dataset()` is the plug-in point for a real dataset: point
    `CROP_REC_DATASET_PATH` at a CSV with the same 7 feature columns plus a
    `label` column (and optionally `lat`/`lon`/`state`), and training will use it.

Every artefact exports `training_data.is_synthetic_sample=true` when the sample
generator was used, and the API surfaces that as a limitation in the response, so
no user is shown a demonstration model's output as agronomic advice.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai.crop_recommendation.features import FEATURE_NAMES, FEATURE_RANGES, SAMPLE_CROPS

DATASET_VERSION_SAMPLE = "synthetic-agronomic-envelope-v1"
RANDOM_SEED = 20260215  # documented so the sample dataset is reproducible


@dataclass(slots=True)
class Dataset:
    rows: list[dict[str, float]]
    labels: list[str]
    version: str
    description: str
    is_synthetic: bool
    label_counts: dict[str, int]
    path: str | None = None


def _gaussian_clipped(
    mean: float, sigma: float, low: float, high: float, rng: random.Random
) -> float:
    value = rng.gauss(mean, sigma)
    return max(low, min(high, value))


def build_sample_dataset(
    *, samples_per_crop: int = 220, seed: int = RANDOM_SEED
) -> Dataset:
    """Deterministic synthetic dataset from the documented envelopes."""
    rng = random.Random(seed)
    rows: list[dict[str, float]] = []
    labels: list[str] = []
    for crop, meta in SAMPLE_CROPS.items():
        for _ in range(samples_per_crop):
            row: dict[str, float] = {}
            for feature, (low, high) in meta["preferred"].items():
                span = high - low
                # centre-biased Gaussian inside the envelope, clipped to the
                # global plausible range for the feature
                mean = (low + high) / 2
                sigma = span / 4.5
                global_low, global_high = FEATURE_RANGES[feature]
                row[feature] = round(
                    _gaussian_clipped(
                        mean,
                        sigma,
                        max(low - span * 0.4, global_low),
                        min(high + span * 0.4, global_high),
                        rng,
                    ),
                    2,
                )
            rows.append(row)
            labels.append(crop)
    counts = {crop: labels.count(crop) for crop in SAMPLE_CROPS}
    return Dataset(
        rows=rows,
        labels=labels,
        version=DATASET_VERSION_SAMPLE,
        description=(
            "Synthetic dataset generated from documented textbook agronomic envelopes "
            f"(seed={seed}, {samples_per_crop} samples per crop, {len(SAMPLE_CROPS)} crops). "
            "It exercises the whole pipeline but is NOT a substitute for regional field data."
        ),
        is_synthetic=True,
        label_counts=counts,
    )


def load_real_dataset(path: str | Path) -> Dataset:
    """Load a real dataset CSV: 7 feature columns + `label` (optional `state`)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Dataset not found at {path}. Download an openly licensed dataset and set "
            "CROP_REC_DATASET_PATH, or run training without it to use the synthetic sample."
        )
    rows: list[dict[str, float]] = []
    labels: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [
            name for name in FEATURE_NAMES if name not in (reader.fieldnames or [])
        ]
        if missing or "label" not in (reader.fieldnames or []):
            raise ValueError(
                f"Dataset must contain columns {FEATURE_NAMES} plus 'label'. Missing: {missing}"
            )
        for record in reader:
            try:
                rows.append({name: float(record[name]) for name in FEATURE_NAMES})
            except (TypeError, ValueError):
                continue  # skip malformed lines rather than poisoning training
            labels.append(str(record["label"]).strip().lower())
    if not rows:
        raise ValueError("Dataset contained no usable rows.")
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return Dataset(
        rows=rows,
        labels=labels,
        version=f"file:{path.name}:{datetime.now(UTC).date().isoformat()}",
        description=f"Real dataset loaded from {path} ({len(rows)} rows, {len(counts)} classes).",
        is_synthetic=False,
        label_counts=counts,
        path=str(path),
    )


def dataset_fingerprint(dataset: Dataset) -> str:
    """Stable fingerprint of feature values + labels (dataset versioning without
    storing the whole dataset in MLflow)."""
    import hashlib

    hasher = hashlib.sha256()
    for row, label in zip(dataset.rows, dataset.labels):
        for name in FEATURE_NAMES:
            hasher.update(f"{row[name]:.4f}".encode())
        hasher.update(label.encode())
    return hasher.hexdigest()[:32]


def write_sample_csv(dataset: Dataset, destination: str | Path) -> Path:
    """Persist the sample dataset so data/ carries the exact training input."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*FEATURE_NAMES, "label"])
        writer.writeheader()
        for row, label in zip(dataset.rows, dataset.labels):
            writer.writerow({**row, "label": label})
    return destination


def class_balance_report(dataset: Dataset) -> dict[str, object]:
    counts = dataset.label_counts
    total = sum(counts.values())
    return {
        "total": total,
        "classes": len(counts),
        "counts": counts,
        "min_per_class": min(counts.values()),
        "max_per_class": max(counts.values()),
        "imbalance_ratio": round(
            max(counts.values()) / max(1, min(counts.values())), 3
        ),
        "entropy": round(
            -sum((c / total) * math.log(c / total) for c in counts.values() if c)
            / math.log(len(counts)),
            4,
        )
        if len(counts) > 1
        else 0.0,
    }
