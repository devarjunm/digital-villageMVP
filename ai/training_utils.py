"""Shared training utilities: splits, metrics, MLflow logging, artefact export.

Used by every training pipeline in this repository so that:
  * splits are always seeded and reported (no accidental leakage between them);
  * metrics are computed with one implementation, so the numbers in a model card
    always mean the same thing;
  * artefacts land in the layout the serving layer expects
    (ML_MODELS_DIR/<name>/<version>/{model.*, model_card.json, metrics.json});
  * MLflow logging degrades to "recorded locally" when no tracking server is
    reachable, and the model card says which of the two happened.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class Split:
    X_train: np.ndarray
    y_train: np.ndarray
    X_val: np.ndarray
    y_val: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    report: dict[str, Any] = field(default_factory=dict)


def make_splits(
    X: np.ndarray,
    y: np.ndarray,
    *,
    test_size: float = 0.2,
    val_size: float = 0.1,
    seed: int = 42,
    stratify: bool = True,
) -> Split:
    from sklearn.model_selection import train_test_split

    strat = y if stratify else None
    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=strat
    )
    strat2 = y_train_val if stratify else None
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=val_size, random_state=seed, stratify=strat2
    )
    report = {
        "seed": seed,
        "test_size": test_size,
        "val_size": val_size,
        "stratified": stratify,
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
        "n_test": int(len(y_test)),
        "label_distribution": {
            "train": _distribution(y_train),
            "val": _distribution(y_val),
            "test": _distribution(y_test),
        },
    }
    return Split(X_train, y_train, X_val, y_val, X_test, y_test, report)


def _distribution(y: np.ndarray) -> dict[str, int]:
    values, counts = np.unique(y, return_counts=True)
    return {str(v): int(c) for v, c in zip(values, counts)}


# --------------------------------------------------------------------- metrics
def classification_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, *, labels: list[str] | None = None
) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        classification_report,
        cohen_kappa_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    labels = labels or sorted(set(y_true.tolist()) | set(y_pred.tolist()))
    report = classification_report(
        y_true, y_pred, output_dict=True, zero_division=0, labels=labels
    )
    metrics: dict[str, Any] = {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 6),
        "macro_precision": round(
            float(precision_score(y_true, y_pred, average="macro", zero_division=0)), 6
        ),
        "macro_recall": round(
            float(recall_score(y_true, y_pred, average="macro", zero_division=0)), 6
        ),
        "macro_f1": round(
            float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 6
        ),
        "weighted_f1": round(
            float(f1_score(y_true, y_pred, average="weighted", zero_division=0)), 6
        ),
        "cohen_kappa": round(float(cohen_kappa_score(y_true, y_pred)), 6),
    }
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    metrics["confusion_matrix"] = matrix.tolist()
    metrics["confusion_matrix_labels"] = list(labels)
    metrics["per_class"] = [
        {
            "label": label,
            "precision": round(float(report[label]["precision"]), 6),
            "recall": round(float(report[label]["recall"]), 6),
            "f1": round(float(report[label]["f1-score"]), 6),
            "support": int(report[label]["support"]),
        }
        for label in labels
        if label in report
    ]
    return metrics


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import (
        explained_variance_score,
        max_error,
        mean_absolute_error,
        mean_absolute_percentage_error,
        mean_squared_error,
        median_absolute_error,
        r2_score,
    )

    mse = float(mean_squared_error(y_true, y_pred))
    metrics = {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 6),
        "rmse": round(float(np.sqrt(mse)), 6),
        "r2": round(float(r2_score(y_true, y_pred)), 6),
        "explained_variance": round(float(explained_variance_score(y_true, y_pred)), 6),
        "median_absolute_error": round(float(median_absolute_error(y_true, y_pred)), 6),
        "max_error": round(float(max_error(y_true, y_pred)), 6),
    }
    try:
        metrics["mape"] = round(
            float(mean_absolute_percentage_error(y_true, y_pred)), 6
        )
    except ValueError:
        metrics["mape"] = None
    residuals = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    metrics["residual_std"] = round(float(residuals.std()), 6)
    return metrics


def learning_curve_summary(
    estimator: Any, X: np.ndarray, y: np.ndarray, *, cv: int = 5
) -> dict[str, Any]:
    """Cheap over/under-fitting signal: 5-fold CV score on the training pool."""
    from sklearn.model_selection import cross_val_score

    try:
        scores = cross_val_score(estimator, X, y, cv=cv, scoring="accuracy", n_jobs=1)
        return {
            "cv_folds": cv,
            "cv_mean": round(float(scores.mean()), 6),
            "cv_std": round(float(scores.std()), 6),
            "cv_scores": [round(float(s), 6) for s in scores],
        }
    except Exception as exc:  # noqa: BLE001
        return {"cv_error": str(exc)[:200]}


# ---------------------------------------------------------------------- mlflow
def mlflow_context(experiment: str, *, run_name: str) -> tuple[Any, dict[str, Any]]:
    """Return (run_context_manager, status_dict).

    Falls back to a no-op context when MLflow is not installed or the tracking
    server is unreachable, and reports which happened so the model card can state
    it truthfully.
    """
    status: dict[str, Any] = {
        "mlflow_available": False,
        "tracking_uri": None,
        "run_id": None,
        "logged": False,
    }
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        status["reason"] = (
            "mlflow not installed (pip install -r backend/requirements-ml.txt)"
        )
        return _NullRun(status), status

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    else:
        local_dir = REPO_ROOT / "mlruns"
        local_dir.mkdir(exist_ok=True)
        mlflow.set_tracking_uri(local_dir.as_uri())
        status["reason"] = (
            "MLFLOW_TRACKING_URI not set: logging to the local ./mlruns directory"
        )
    status["mlflow_available"] = True
    status["tracking_uri"] = mlflow.get_tracking_uri()
    try:
        mlflow.set_experiment(experiment)
        run = mlflow.start_run(run_name=run_name)
        status["run_id"] = run.info.run_id
        return MLflowRun(mlflow, run, status), status
    except Exception as exc:  # noqa: BLE001 - a tracking outage must not fail training
        status["reason"] = f"mlflow run could not be started: {exc}"[:300]
        return _NullRun(status), status


class MLflowRun:
    """Context manager around an active MLflow run (module-level proxies kept on
    purpose so callers never touch the mlflow global state)."""

    def __init__(self, module: Any, run: Any, status: dict[str, Any]) -> None:
        self._mlflow = module
        self._run = run
        self.status = status

    def log_params(self, params: dict[str, Any]) -> None:
        self._mlflow.log_params(params)

    def log_metrics(self, metrics: dict[str, Any]) -> None:
        self._mlflow.log_metrics(metrics)

    def log_artifact(self, path: str) -> None:
        self._mlflow.log_artifact(path)

    def set_tag(self, key: str, value: str) -> None:
        self._mlflow.set_tag(key, value)

    def __enter__(self) -> "MLflowRun":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            self._mlflow.end_run(status="FAILED" if exc_type else "FINISHED")
        except Exception:  # noqa: BLE001
            pass
        self.status["logged"] = exc_type is None
        return False


class _NullRun:
    def __init__(self, status: dict[str, Any]) -> None:
        self.status = status

    def log_params(self, *_a: Any, **_k: Any) -> None: ...
    def log_metrics(self, *_a: Any, **_k: Any) -> None: ...
    def log_artifact(self, *_a: Any, **_k: Any) -> None: ...
    def set_tag(self, *_a: Any, **_k: Any) -> None: ...
    def __enter__(self) -> "_NullRun":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False

    def end_run(self) -> None: ...


def log_to_mlflow(
    ctx: Any,
    *,
    params: dict[str, Any],
    metrics: dict[str, Any],
    artifacts: list[Path] | None = None,
    tags: dict[str, str] | None = None,
) -> None:
    try:
        ctx.log_params({k: str(v)[:250] for k, v in params.items()})
        flat_metrics = {
            k: float(v)
            for k, v in metrics.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if flat_metrics:
            ctx.log_metrics(flat_metrics)
        for key, value in (tags or {}).items():
            ctx.set_tag(key, value)
        for artifact in artifacts or []:
            if artifact.exists():
                ctx.log_artifact(str(artifact))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] MLflow logging partially failed: {exc}", file=sys.stderr)


# ------------------------------------------------------------------- artefacts
def environment_report() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for module_name in ("numpy", "pandas", "sklearn", "torch", "torchvision", "PIL"):
        try:
            module = __import__(module_name)
            versions[module_name] = getattr(module, "__version__", "unknown")
        except ImportError:
            continue
    return versions


def write_artifact_dir(
    *,
    model_name: str,
    version: str,
    model_files: dict[str, Any],
    card: dict[str, Any],
    metrics: dict[str, Any],
    extra_json: dict[str, dict[str, Any]] | None = None,
    base_dir: str | Path | None = None,
) -> Path:
    """Write the serving layout: ML_MODELS_DIR/<model_name>/<version>/…"""
    import joblib

    root = Path(
        base_dir
        or os.environ.get("ML_MODELS_DIR")
        or (REPO_ROOT / "artifacts" / "models")
    )
    target = root / model_name / version
    target.mkdir(parents=True, exist_ok=True)

    for filename, payload in model_files.items():
        path = target / filename
        if filename.endswith(".joblib"):
            # compress=3 (zlib) is the joblib default *setting* people forget to pass.
            # Uncompressed, an ensemble of forests lands at ~51 MB per version; with
            # compression the same artefact is ~8 MB. That matters where these files
            # live: a Docker volume, an S3 prefix and a developer's first clone. Loading
            # is unaffected (joblib decompresses transparently).
            joblib.dump(payload, path, compress=3)
        elif filename.endswith((".pt", ".pth")):
            import torch  # imported here so non-PyTorch pipelines do not need it

            torch.save(payload, path)
        elif filename.endswith(".json"):
            path.write_text(json.dumps(payload, indent=2, default=str))
        else:
            raise ValueError(f"Unsupported artefact type: {filename}")
    (target / "model_card.json").write_text(json.dumps(card, indent=2, default=str))
    (target / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    for filename, payload in (extra_json or {}).items():
        (target / filename).write_text(json.dumps(payload, indent=2, default=str))
    return target


def timer() -> Any:
    return time.perf_counter()
