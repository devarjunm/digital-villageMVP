"""Every shipped model artefact must be self-describing and internally consistent.

These tests live outside `backend/` on purpose: they check the *repository*, not
the application. A model artefact is a release artefact like an image or a
migration, and the failure this file exists to catch is an artefact that can be
served without saying what it is, what it was trained on, or how well it scored.

Nothing here trains or downloads anything; it validates what is on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "artifacts" / "models"

ARTEFACT_FILES = {"model.joblib", "model.pt", "model.pkl"}


def _versions() -> list[tuple[str, Path]]:
    if not MODELS_DIR.exists():
        return []
    out: list[tuple[str, Path]] = []
    for model_dir in sorted(p for p in MODELS_DIR.iterdir() if p.is_dir()):
        for version_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            out.append((f"{model_dir.name}/{version_dir.name}", version_dir))
    return out


ARTEFACTS = _versions()


def test_models_directory_exists_or_the_feature_is_reported_unavailable():
    """An empty artefacts directory is legal — it must simply be *absent*, not faked."""
    if not MODELS_DIR.exists():
        pytest.skip(
            "no artefacts directory: every AI endpoint must then report the model as unavailable"
        )
    assert MODELS_DIR.is_dir()


@pytest.mark.parametrize("label,directory", ARTEFACTS or [("none", MODELS_DIR)])
def test_reported_metrics_come_from_an_evaluation_run(
    label: str, directory: Path
) -> None:
    if label == "none":
        pytest.skip("no artefacts installed in this checkout")
    metrics = json.loads((directory / "metrics.json").read_text())
    assert metrics, f"{label}: metrics.json is empty"

    # metrics.json is written by the trainer as one block per evaluation split
    # (`validation`, `test`, plus the candidate comparison). Every bounded score in
    # there must be a valid score, and at least one real split must exist so a
    # number can never be quoted without knowing what it was measured on.
    bounded = {
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "weighted_f1",
        "macro_precision",
        "macro_recall",
        "cohen_kappa",
        "f1",
        "precision",
        "recall",
        "auc",
    }

    def walk(payload, prefix=""):
        if isinstance(payload, dict):
            for key, value in payload.items():
                yield from walk(value, f"{prefix}{key}.")
        elif isinstance(payload, list):
            for index, value in enumerate(payload):
                yield from walk(value, f"{prefix}{index}.")
        else:
            yield prefix.rstrip("."), payload

    scores = 0
    for path, value in walk(metrics):
        leaf = path.rsplit(".", 1)[-1].lower()
        if (
            leaf in bounded
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            assert (
                0.0 <= float(value) <= 1.0
            ), f"{label}: {path}={value} is not a valid score"
            scores += 1
    assert scores > 0, f"{label}: no recognised evaluation score found in metrics.json"
    assert (
        "validation" in metrics or "test" in metrics
    ), f"{label}: metrics must be grouped by evaluation split so they cannot be quoted out of context"


@pytest.mark.parametrize("label,directory", ARTEFACTS or [("none", MODELS_DIR)])
def test_calibration_status_is_explicit(label: str, directory: Path) -> None:
    """Uncalibrated scores may not be presented as probabilities."""
    if label == "none":
        pytest.skip("no artefacts installed in this checkout")
    card = json.loads((directory / "model_card.json").read_text())
    calibration = card.get("calibration")
    assert isinstance(
        calibration, dict
    ), f"{label}: the card must record calibration status"
    assert "calibrated" in calibration, f"{label}: calibration.calibrated is required"
    if calibration["calibrated"] is False:
        # The API reads this to choose between "probability" and "relative model
        # score" wording, so a false here must be explained.
        assert (
            calibration.get("note") or calibration.get("method") is None
        ), f"{label}: an uncalibrated artefact must explain the wording the API will use"


@pytest.mark.parametrize("label,directory", ARTEFACTS or [("none", MODELS_DIR)])
def test_artefact_files_are_compressed(label: str, directory: Path) -> None:
    """Artefacts travel to Docker volumes and S3; uncompressed joblib is pure waste.

    Regression guard: `joblib.dump(..., compress=3)` was missing, so a small
    soft-voting ensemble shipped as a 53 MB file per version (recompressed: ~9 MB).
    """
    if label == "none":
        pytest.skip("no artefacts installed in this checkout")

    def compressed(header: bytes) -> str | None:
        if header[:2] == b"\x1f\x8b":
            return "gzip"
        if header[:3] == b"BZh":
            return "bz2"
        if header[:6] == b"\xfd7zXZ\x00":
            return "xz"
        # RFC1950 zlib: deflate method in the low nibble, and the two header bytes
        # are a 16-bit value that must be divisible by 31.
        if (
            len(header) >= 2
            and header[0] & 0x0F == 8
            and ((header[0] << 8) | header[1]) % 31 == 0
        ):
            return "zlib"
        return None

    checked = 0
    for artefact in sorted(directory.glob("*.joblib")):
        assert compressed(artefact.read_bytes()[:8]) is not None, (
            f"{label}/{artefact.name} is stored uncompressed ({artefact.stat().st_size} bytes); "
            "write it with joblib.dump(..., compress=3)"
        )
        checked += 1
    if checked == 0:
        pytest.skip(f"{label}: no .joblib artefact in this directory")

    # A cap a healthy tabular model cannot plausibly reach, so runaway packaging
    # (bundling the training set, say) is caught early.
    biggest = max(
        (p.stat().st_size for p in directory.iterdir() if p.is_file()), default=0
    )
    assert (
        biggest < 25 * 1024 * 1024
    ), f"{label}: largest file is {biggest / 1e6:.1f} MB — check nothing is bundling the dataset"


def test_newest_crop_recommendation_artefact_loads_and_predicts():
    """Compression must not cost anything at load time: prove a real round trip."""
    pytest.importorskip("joblib")
    source = MODELS_DIR / "crop-recommendation"
    if not source.exists() or not any(source.iterdir()):
        pytest.skip("no crop-recommendation artefact in this checkout")

    import joblib

    newest = sorted(p for p in source.iterdir() if p.is_dir())[-1]
    payload = joblib.load(newest / "model.joblib")
    assert isinstance(payload, dict), "the artefact is a bundle of pipeline + metadata"
    for key in ("pipeline", "classes", "features"):
        assert key in payload, f"artefact bundle is missing '{key}'"

    pipeline = payload["pipeline"]
    assert hasattr(
        pipeline, "predict_proba"
    ), "the serving path requires predict_proba()"
    assert len(payload["features"]) == pipeline.n_features_in_

    import numpy as np

    sample = np.array([[90.0, 42.0, 43.0, 26.5, 82.0, 6.5, 180.0]])
    probabilities = pipeline.predict_proba(sample)[0]
    assert abs(float(sum(probabilities)) - 1.0) < 1e-6
    assert len(probabilities) == len(payload["classes"])
