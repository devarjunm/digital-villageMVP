"""Crop recommendation training pipeline (scikit-learn).

Usage
-----
    python -m ai.crop_recommendation.train                    # synthetic sample dataset
    CROP_REC_DATASET_PATH=/data/crop.csv python -m ai.crop_recommendation.train --register

What it does
------------
1. Builds or loads the dataset (see ai/crop_recommendation/dataset.py for the
   provenance rules — the bundled data is synthetic and labelled as such).
2. Makes a stratified train/validation/test split (seeded, reported).
3. Trains and compares several candidate models with 5-fold CV on the training
   pool, then fits the best on train+val and evaluates once on the held-out test
   set: accuracy, balanced accuracy, macro precision/recall/F1, Cohen's kappa,
   per-class metrics and a confusion matrix.
4. Writes the winning pipeline to ML_MODELS_DIR/crop-recommendation/<version>/
   with model.joblib, model_card.json and metrics.json.
5. Logs parameters, metrics and artefacts to MLflow when a tracking URI is
   configured (falls back to ./mlruns, and says so in the model card).
6. Optionally registers the version in the application database
   (`model_registry_entries`) so the admin console shows it — only when
   --register is passed and DATABASE_URL is reachable.

The metrics written into the model card are the measured ones from this run —
nothing in this repository hard-codes a performance number.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from ai.crop_recommendation.dataset import (  # noqa: E402
    build_sample_dataset,
    class_balance_report,
    dataset_fingerprint,
    load_real_dataset,
    write_sample_csv,
)
from ai.crop_recommendation.features import FEATURE_NAMES, SAMPLE_CROPS  # noqa: E402
from ai.training_utils import (  # noqa: E402
    classification_metrics,
    environment_report,
    log_to_mlflow,
    make_splits,
    mlflow_context,
    package_versions,
    write_artifact_dir,
)

MODEL_NAME = "crop-recommendation"
EXPERIMENT = os.environ.get(
    "MLFLOW_EXPERIMENT_CROP_RECOMMENDATION", "crop-recommendation"
)


def build_candidates(seed: int = 42):
    """Candidate models with small, documented search spaces."""
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        GradientBoostingClassifier,
        HistGradientBoostingClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    return {
        "random_forest": RandomForestClassifier(
            n_estimators=400,
            max_depth=None,
            min_samples_leaf=2,
            random_state=seed,
            n_jobs=-1,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=400, min_samples_leaf=2, random_state=seed, n_jobs=-1
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(random_state=seed),
        "gradient_boosting": GradientBoostingClassifier(random_state=seed),
        "svc_rbf_scaled": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("svc", SVC(C=4.0, gamma="scale", probability=True, random_state=seed)),
            ]
        ),
        "logistic_scaled": Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "logreg",
                    LogisticRegression(
                        max_iter=2000, multi_class="multinomial", random_state=seed
                    ),
                ),
            ]
        ),
        "soft_voting": VotingClassifier(
            estimators=[
                (
                    "rf",
                    RandomForestClassifier(
                        n_estimators=300,
                        min_samples_leaf=2,
                        random_state=seed,
                        n_jobs=-1,
                    ),
                ),
                (
                    "et",
                    ExtraTreesClassifier(
                        n_estimators=300,
                        min_samples_leaf=2,
                        random_state=seed,
                        n_jobs=-1,
                    ),
                ),
                (
                    "svc",
                    Pipeline(
                        [
                            ("scaler", StandardScaler()),
                            ("svc", SVC(C=4.0, probability=True, random_state=seed)),
                        ]
                    ),
                ),
            ],
            voting="soft",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the crop recommendation model")
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register the version in the application database",
    )
    parser.add_argument(
        "--version", default=None, help="Model version label (default: timestamped)"
    )
    parser.add_argument("--samples-per-crop", type=int, default=220)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cv", type=int, default=5)
    args = parser.parse_args()

    dataset_path = os.environ.get("CROP_REC_DATASET_PATH", "").strip()
    if dataset_path:
        print(f"[info] loading real dataset from {dataset_path}")
        dataset = load_real_dataset(dataset_path)
    else:
        print(
            "[info] building synthetic sample dataset (no CROP_REC_DATASET_PATH configured)"
        )
        dataset = build_sample_dataset(samples_per_crop=args.samples_per_crop)
        sample_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "datasets"
            / "crop_recommendation"
            / "sample_dataset.csv"
        )
        write_sample_csv(dataset, sample_path)
        print(f"[info] sample dataset written to {sample_path}")

    X = np.array(
        [[row[name] for name in FEATURE_NAMES] for row in dataset.rows], dtype=float
    )
    y = np.array(dataset.labels)

    splits = make_splits(X, y, seed=args.seed)
    print(
        f"[info] split: {splits.report['n_train']} train / {splits.report['n_val']} val / {splits.report['n_test']} test"
    )

    candidates = build_candidates(seed=args.seed)
    results: dict[str, dict] = {}
    from sklearn.model_selection import cross_val_score

    X_train_full = np.vstack([splits.X_train, splits.X_val])
    y_train_full = np.concatenate([splits.y_train, splits.y_val])

    for name, estimator in candidates.items():
        print(f"[info] cross-validating {name} …")
        try:
            scores = cross_val_score(
                estimator,
                splits.X_train,
                splits.y_train,
                cv=args.cv,
                scoring="accuracy",
                n_jobs=1,
            )
            cv_mean, cv_std = float(scores.mean()), float(scores.std())
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {name} CV failed: {exc}")
            results[name] = {"error": str(exc)[:200]}
            continue
        results[name] = {
            "cv_mean_accuracy": round(cv_mean, 6),
            "cv_std": round(cv_std, 6),
        }
        print(f"       CV accuracy {cv_mean:.4f} ± {cv_std:.4f}")

    best_name = max(
        (n for n, r in results.items() if "cv_mean_accuracy" in r),
        key=lambda n: results[n]["cv_mean_accuracy"],
        default=None,
    )
    if best_name is None:
        print("[error] every candidate failed cross-validation", file=sys.stderr)
        return 1
    print(f"[info] best candidate by CV: {best_name}")

    best = candidates[best_name]
    best.fit(X_train_full, y_train_full)

    val_pred = best.predict(splits.X_val)
    val_metrics = classification_metrics(
        splits.y_val, val_pred, labels=sorted(set(y.tolist()))
    )
    test_pred = best.predict(splits.X_test)
    test_metrics = classification_metrics(
        splits.y_test, test_pred, labels=sorted(set(y.tolist()))
    )
    print(
        f"[result] validation accuracy {val_metrics['accuracy']:.4f} | test accuracy {test_metrics['accuracy']:.4f}"
    )
    print(
        f"[result] test macro-F1 {test_metrics['macro_f1']:.4f} | Cohen's kappa {test_metrics['cohen_kappa']:.4f}"
    )

    # Optional probability calibration check (Brier score + reliability note).
    calibration = {"calibrated": False, "method": None}
    if hasattr(best, "predict_proba"):
        from sklearn.metrics import brier_score_loss
        from sklearn.preprocessing import LabelBinarizer

        try:
            probabilities = best.predict_proba(splits.X_test)
            classes = list(getattr(best, "classes_", sorted(set(y.tolist()))))
            lb = LabelBinarizer().fit(classes)
            y_bin = lb.transform(splits.y_test)
            if y_bin.shape[1] == 1:  # binary case safety
                y_bin = np.hstack([1 - y_bin, y_bin])
            brier = float(
                np.mean(
                    [
                        brier_score_loss(y_bin[:, i], probabilities[:, i])
                        for i in range(y_bin.shape[1])
                    ]
                )
            )
            calibration = {
                "calibrated": False,
                "method": None,
                "multiclass_brier": round(brier, 6),
                "note": (
                    "Raw model probabilities. Brier score reported for transparency; scores are NOT presented "
                    "as calibrated probabilities by the API because no calibration step was applied."
                ),
            }
        except Exception as exc:  # noqa: BLE001
            calibration = {"calibrated": False, "method": None, "error": str(exc)[:200]}

    version = args.version or f"v{datetime.now(UTC):%Y%m%d%H%M}"
    card = {
        "name": MODEL_NAME,
        "version": version,
        "task": "multiclass classification (crop recommendation)",
        "framework": f"scikit-learn ({package_versions().get('sklearn', 'unknown')})",
        "trained_at": datetime.now(UTC).isoformat(),
        "selected_model": best_name,
        "features": FEATURE_NAMES,
        "classes": sorted(set(y.tolist())),
        "calibration": calibration,
        "dataset": {
            "version": dataset.version,
            "fingerprint": dataset_fingerprint(dataset),
            "description": dataset.description,
            "is_synthetic_sample": dataset.is_synthetic,
            "path": dataset.path,
            "balance": class_balance_report(dataset),
        },
        "splits": splits.report,
        "candidate_comparison": results,
        "metrics": {
            "validation": {
                k: v for k, v in val_metrics.items() if k != "confusion_matrix"
            },
            "test": {k: v for k, v in test_metrics.items() if k != "confusion_matrix"},
        },
        "environment": environment_report(),
        "packages": package_versions(),
        "intended_use": (
            "Educational/demo ranking of candidate crops from soil and climate inputs for the crops listed in "
            "'classes'. Not a substitute for local agronomic advice, soil testing or crop planning."
        ),
        "known_limitations": [
            "Trained on a synthetic sample generated from textbook envelopes; real regional data is required "
            "before this output can inform real planting decisions.",
            "Scores are uncalibrated relative model scores (see 'calibration').",
            "No market, labour, water-availability or rotation information is used.",
            "Feature ranges are clamped to the documented plausible bounds; out-of-range inputs are rejected.",
        ],
        "mlflow": {},
    }

    artifacts_dir = write_artifact_dir(
        model_name=MODEL_NAME,
        version=version,
        model_files={
            "model.joblib": {
                "pipeline": best,
                "classes": sorted(set(y.tolist())),
                "features": FEATURE_NAMES,
                "calibrated": calibration.get("calibrated", False),
            }
        },
        card=card,
        metrics={
            "validation": val_metrics,
            "test": test_metrics,
            "candidates": results,
            "calibration": calibration,
        },
        extra_json={
            "feature_names.json": {"features": FEATURE_NAMES, "crops": SAMPLE_CROPS}
        },
    )
    print(f"[info] artefacts written to {artifacts_dir}")

    ctx, mlflow_status = mlflow_context(EXPERIMENT, run_name=f"{best_name}-{version}")
    with ctx:
        log_to_mlflow(
            ctx,
            params={
                "model": best_name,
                "seed": args.seed,
                "cv_folds": args.cv,
                "dataset_version": dataset.version,
                "dataset_fingerprint": dataset_fingerprint(dataset),
                "is_synthetic": dataset.is_synthetic,
                "n_train": splits.report["n_train"],
                "n_val": splits.report["n_val"],
                "n_test": splits.report["n_test"],
            },
            metrics={
                **{
                    f"test_{k}": v
                    for k, v in test_metrics.items()
                    if isinstance(v, (int, float))
                },
                **{
                    f"val_{k}": v
                    for k, v in val_metrics.items()
                    if isinstance(v, (int, float))
                },
            },
            artifacts=[
                artifacts_dir / "model_card.json",
                artifacts_dir / "metrics.json",
            ],
            tags={
                "model_name": MODEL_NAME,
                "version": version,
                "is_synthetic_sample": str(dataset.is_synthetic),
            },
        )
    card["mlflow"] = mlflow_status
    (artifacts_dir / "model_card.json").write_text(
        json.dumps(card, indent=2, default=str)
    )
    print(f"[info] mlflow: {mlflow_status}")

    if args.register:
        try:
            from app.ai.registry import ModelRegistryService
            from app.database.session import session_scope

            with session_scope() as db:
                entry = ModelRegistryService(db).register(
                    name=MODEL_NAME,
                    version=version,
                    display_name="Crop recommendation (soil & climate)",
                    task="classification",
                    framework="scikit-learn",
                    mlflow_run_id=mlflow_status.get("run_id"),
                    artifact_uri=str(artifacts_dir),
                    metrics={"test": test_metrics, "validation": val_metrics},
                    parameters={"selected_model": best_name, "seed": args.seed},
                    training_data={
                        "version": dataset.version,
                        "is_synthetic_sample": dataset.is_synthetic,
                        "rows": len(dataset.rows),
                        "classes": card["classes"],
                        "description": dataset.description,
                        "crops": [
                            {
                                "code": code,
                                "name_en": meta["name_en"],
                                "preferred": meta["preferred"],
                            }
                            for code, meta in SAMPLE_CROPS.items()
                            if code in card["classes"]
                        ],
                    },
                    evaluation_report={"validation": val_metrics, "test": test_metrics},
                    stage=__import__(
                        "app.core.enums", fromlist=["ModelStage"]
                    ).ModelStage.PRODUCTION,
                    notes="Registered by ai/crop_recommendation/train.py",
                )
            print(
                f"[info] registered in database: {entry.name} {entry.version} ({entry.stage})"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] database registration skipped: {exc}", file=sys.stderr)

    print("\n[summary]")
    print(
        json.dumps(
            {
                "model": best_name,
                "version": version,
                "test_accuracy": test_metrics["accuracy"],
                "test_macro_f1": test_metrics["macro_f1"],
                "artifacts": str(artifacts_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
