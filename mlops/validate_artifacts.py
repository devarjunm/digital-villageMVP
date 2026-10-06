#!/usr/bin/env python
"""Validate every model artefact on disk before it is deployed.

Run this in CI and in the release runbook (`docs/deployment.md` §5). It fails, with
a non-zero exit code, when an artefact would be served without being able to
answer: what is it, what was it trained on, how well did it do, and are its
scores calibrated?

    python mlops/validate_artifacts.py                 # validate everything found
    python mlops/validate_artifacts.py crop-recommendation
    python mlops/validate_artifacts.py --models-dir ./artifacts/models

Deliberately *not* done here: no training, no downloads, no network. Validation
must be safe to run in a restricted environment, minutes before a deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = REPO_ROOT / "artifacts" / "models"
ARTEFACT_SUFFIXES = (".joblib", ".pt", ".pkl", ".onnx")
REQUIRED_CARD_KEYS = ("name", "version", "task", "framework", "trained_at")
SCORE_HINTS = ("accuracy", "f1", "precision", "recall", "auc", "brier", "mae", "rmse")


@dataclass
class Finding:
    level: str  # "error" | "warning"
    where: str
    message: str


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from exc


def _metric_ranges(payload: object, prefix: str = "") -> list[Finding]:
    """Any published score must sit in a sane range and be traceable to an evaluation."""
    findings: list[Finding] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            findings.extend(_metric_ranges(value, f"{prefix}{key}."))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            findings.extend(_metric_ranges(value, f"{prefix}{index}."))
    elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
        name = prefix.rsplit(".", 2)[-2] if "." in prefix else prefix
        if any(hint in name.lower() for hint in SCORE_HINTS):
            # Accuracy-like scores live in [0, 1]; error-like scores (mae/rmse) may
            # be any positive number, so only sanity-check the bounded ones.
            if any(
                hint in name.lower()
                for hint in ("accuracy", "f1", "precision", "recall", "auc")
            ):
                if not 0.0 <= float(payload) <= 1.0:
                    findings.append(
                        Finding(
                            "error",
                            prefix.rstrip("."),
                            f"score {payload} is outside [0, 1]",
                        )
                    )
            elif float(payload) < 0:
                findings.append(
                    Finding("error", prefix.rstrip("."), f"score {payload} is negative")
                )
    return findings


def validate_version(model_dir: Path, version_dir: Path) -> list[Finding]:
    label = f"{model_dir.name}/{version_dir.name}"
    findings: list[Finding] = []

    artefact_files = [p for p in version_dir.iterdir() if p.suffix in ARTEFACT_SUFFIXES]
    if not artefact_files:
        findings.append(
            Finding(
                "error",
                label,
                f"no model file (expected one of {', '.join(ARTEFACT_SUFFIXES)})",
            )
        )

    card_path = version_dir / "model_card.json"
    if not card_path.exists():
        findings.append(Finding("error", label, "model_card.json is missing"))
        return findings  # nothing else can be checked

    try:
        card = _load(card_path)
    except ValueError as exc:
        findings.append(Finding("error", label, str(exc)))
        return findings

    for key in REQUIRED_CARD_KEYS:
        if not card.get(key):
            findings.append(Finding("error", label, f"model card is missing '{key}'"))
    if card.get("name") and card["name"] != model_dir.name:
        findings.append(
            Finding(
                "error",
                label,
                f"card name '{card['name']}' != directory '{model_dir.name}'",
            )
        )
    if card.get("version") and card["version"] != version_dir.name:
        findings.append(
            Finding(
                "error",
                label,
                f"card version '{card['version']}' != directory '{version_dir.name}'",
            )
        )

    dataset = card.get("dataset") or {}
    if not dataset:
        findings.append(
            Finding("error", label, "model card does not describe the training data")
        )
    else:
        for key in ("description", "fingerprint"):
            if not dataset.get(key):
                findings.append(Finding("error", label, f"dataset.{key} is missing"))
        if (
            "synthetic" in json.dumps(dataset).lower()
            and dataset.get("is_synthetic_sample") is not True
        ):
            findings.append(
                Finding(
                    "warning",
                    label,
                    "synthetic dataset is not marked is_synthetic_sample",
                )
            )

    calibration = card.get("calibration")
    if not isinstance(calibration, dict) or "calibrated" not in calibration:
        findings.append(
            Finding(
                "error",
                label,
                "calibration.calibrated must be recorded (the API's wording depends on it)",
            )
        )
    elif calibration["calibrated"] is True and not calibration.get("method"):
        findings.append(
            Finding("error", label, "calibrated=true without a calibration method")
        )

    metrics_path = version_dir / "metrics.json"
    if not metrics_path.exists():
        findings.append(Finding("error", label, "metrics.json is missing"))
    else:
        try:
            metrics = _load(metrics_path)
        except ValueError as exc:
            findings.append(Finding("error", label, str(exc)))
        else:
            if not metrics:
                findings.append(Finding("error", label, "metrics.json is empty"))
            findings.extend(
                Finding(f.level, f"{label}:{f.where}", f.message)
                for f in _metric_ranges(metrics)
            )
            splits = {
                key
                for key, value in metrics.items()
                if isinstance(value, dict)
                and any(hint in json.dumps(value).lower() for hint in SCORE_HINTS)
            }
            if not splits:
                findings.append(
                    Finding(
                        "warning",
                        label,
                        "no evaluation split found — how were these numbers produced?",
                    )
                )

    for optional in ("feature_names.json",):
        if not (version_dir / optional).exists():
            findings.append(
                Finding(
                    "warning", label, f"{optional} not present (fine for image models)"
                )
            )

    return findings


def discover(models_dir: Path, only: list[str]) -> list[tuple[Path, Path]]:
    found: list[tuple[Path, Path]] = []
    if not models_dir.exists():
        return found
    for model_dir in sorted(p for p in models_dir.iterdir() if p.is_dir()):
        if only and model_dir.name not in only:
            continue
        for version_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            found.append((model_dir, version_dir))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "models", nargs="*", help="limit validation to these model names"
    )
    parser.add_argument(
        "--models-dir",
        default=None,
        help="artefact root (default: $ML_MODELS_DIR or ./artifacts/models)",
    )
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as failures"
    )
    args = parser.parse_args(argv)

    models_dir = Path(
        args.models_dir or os.environ.get("ML_MODELS_DIR") or DEFAULT_MODELS_DIR
    )

    if not models_dir.exists():
        print(f"No artefact directory at {models_dir}.")
        print(
            "Every AI endpoint will report its model as unavailable — which is a valid state,"
        )
        print(
            "but it is not a valid *release* state. Train or install an artefact first."
        )
        return 1 if args.strict else 0

    targets = discover(models_dir, args.models)
    if not targets:
        print(f"No artefacts found under {models_dir}.")
        return 1 if args.strict else 0

    all_findings: list[Finding] = []
    for model_dir, version_dir in targets:
        findings = validate_version(model_dir, version_dir)
        errors = [f for f in findings if f.level == "error"]
        status = "FAIL" if errors else ("WARN" if findings else "OK")
        print(f"[{status}] {model_dir.name}/{version_dir.name}")
        for finding in findings:
            print(
                f"        {finding.level.upper():<7} {finding.where}: {finding.message}"
            )
        all_findings.extend(findings)

    errors = [f for f in all_findings if f.level == "error"]
    warnings = [f for f in all_findings if f.level == "warning"]
    print(
        f"\n{len(targets)} artefact version(s) checked: "
        f"{len(errors)} error(s), {len(warnings)} warning(s)."
    )
    if errors:
        print(
            "An artefact with errors must not be deployed: the API would not be able to state its provenance."
        )
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
