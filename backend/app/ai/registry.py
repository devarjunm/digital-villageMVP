"""Model registry access layer.

MLflow is the training-side source of truth (experiments, runs, artefacts). This
module is the *serving-side* view:

  * `model_registry_entries` mirrors what has been trained and promoted, with the
    evaluation metrics copied verbatim from the training run (never retyped);
  * artefacts are loaded from ML_MODELS_DIR/<name>/<version>/… (a mounted volume
    or a downloaded S3 prefix) with an in-process cache;
  * when an artefact is missing, callers get `ModelUnavailableError` carrying a
    precise reason — the API then returns 503 `model_unavailable` instead of a
    fabricated prediction.

Nothing here downloads models at import time; loading is lazy and happens on the
first request for that model, so API start-up stays fast and a missing artefact
does not take the whole service down.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.models import ModelEvaluation, ModelRegistryEntry
from app.core.config import settings
from app.core.enums import ModelStage
from app.core.errors import ModelUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

MODEL_NAMES = {
    "crop_recommendation": "crop-recommendation",
    "disease_detection": "disease-detection",
    "yield_prediction": "yield-prediction",
    "price_prediction": "price-prediction",
    "risk_assessment": "risk-assessment",
}


@dataclass(slots=True)
class ModelHandle:
    name: str
    version: str
    task: str
    framework: str
    artifact_dir: Path
    metrics: dict[str, Any] = field(default_factory=dict)
    training_data: dict[str, Any] = field(default_factory=dict)
    mlflow_run_id: str | None = None
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    objects: dict[str, Any] = field(default_factory=dict)

    @property
    def model_card(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "task": self.task,
            "framework": self.framework,
            "metrics": self.metrics,
            "training_data": self.training_data,
            "mlflow_run_id": self.mlflow_run_id,
            "artifact_dir": str(self.artifact_dir),
        }


_lock = threading.Lock()
_cache: dict[str, ModelHandle] = {}

# Environment pin per model name. An operator rolls a model release back by
# setting the matching variable and restarting (docs/deployment.md §9) — so these
# settings must actually be consulted, not merely documented.
PINNED_VERSION_SETTINGS: dict[str, str] = {
    "crop-recommendation": "ml_crop_rec_model_version",
    "disease-detection": "ml_disease_model_version",
    "yield-prediction": "ml_yield_model_version",
    "price-prediction": "ml_price_model_version",
}


def pinned_version(name: str) -> str | None:
    """The version this deployment pinned for a model, if any."""
    setting = PINNED_VERSION_SETTINGS.get(name)
    if setting is None:
        return None
    value = (getattr(settings, setting, "") or "").strip()
    # Treat obvious placeholders as "not pinned" rather than as a version name that
    # silently makes the model unavailable.
    if not value or value.lower() in {"demo-untrained", "none", "latest", "unset"}:
        return None
    return value


def artifact_path(name: str, version: str | None = None) -> Path:
    """Resolve the directory holding a model version.

    Layout: ML_MODELS_DIR/<name>/<version>/ (falling back to ML_MODELS_DIR/<name>/
    when a single active version is deployed without a version directory).

    Resolution order for `version`:
      1. the version asked for explicitly by the caller;
      2. the version pinned for this deployment in the environment
         (`ML_*_MODEL_VERSION`, see `pinned_version`);
      3. the newest installed version directory.
    """
    requested = version or pinned_version(name)
    base = settings.models_path / name
    if requested:
        versioned = base / requested
        if versioned.exists():
            return versioned
        # An explicit request or a deployment pin that is not on disk must NOT fall
        # back to "newest installed": that would silently serve a different model
        # than the operator asked for. Return the (missing) path so the caller
        # reports the model as unavailable and lists what is installed.
        logger.warning(
            "requested_model_version_missing",
            extra={
                "extra_fields": {
                    "model": name,
                    "requested": requested,
                    "installed": available_versions(name),
                }
            },
        )
        return versioned
    if base.exists():
        versions = sorted([p for p in base.iterdir() if p.is_dir()])
        if versions:
            return versions[-1]
        return base
    return base / "unknown"


def available_versions(name: str) -> list[str]:
    """Version directories present on disk for a model (newest last)."""
    base = settings.models_path / name
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


class ModelRegistryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --------------------------------------------------------------- registry
    def register(
        self,
        *,
        name: str,
        version: str,
        display_name: str,
        task: str,
        framework: str,
        mlflow_run_id: str | None,
        artifact_uri: str | None,
        metrics: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        training_data: dict[str, Any] | None = None,
        evaluation_report: dict[str, Any] | None = None,
        stage: ModelStage = ModelStage.STAGING,
        notes: str | None = None,
    ) -> ModelRegistryEntry:
        existing = self.db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.name == name, ModelRegistryEntry.version == version
            )
        ).scalar_one_or_none()
        if existing:
            existing.metrics = metrics
            existing.evaluation_report = evaluation_report or existing.evaluation_report
            existing.stage = stage
            self.db.commit()
            self.db.refresh(existing)
            return existing
        entry = ModelRegistryEntry(
            name=name,
            version=version,
            display_name=display_name,
            task=task,
            framework=framework,
            stage=stage,
            mlflow_run_id=mlflow_run_id,
            artifact_uri=artifact_uri,
            metrics=metrics,
            parameters=parameters or {},
            training_data=training_data or {},
            evaluation_report=evaluation_report or {},
            trained_at=datetime.now(UTC),
            is_active=(stage == ModelStage.PRODUCTION),
            notes=notes,
        )
        self.db.add(entry)
        if stage == ModelStage.PRODUCTION:
            self._deactivate_others(name, keep=entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def _deactivate_others(self, name: str, *, keep: ModelRegistryEntry | None = None) -> None:
        rows = (
            self.db.execute(select(ModelRegistryEntry).where(ModelRegistryEntry.name == name))
            .scalars()
            .all()
        )
        for row in rows:
            if keep is not None and row.id == keep.id:
                continue
            row.is_active = False
            if row.stage == ModelStage.PRODUCTION:
                row.stage = ModelStage.ARCHIVED

    def get_entry(self, entry_id: uuid.UUID) -> ModelRegistryEntry | None:
        return self.db.get(ModelRegistryEntry, entry_id)

    def activate(
        self, *, entry_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> ModelRegistryEntry:
        entry = self.db.get(ModelRegistryEntry, entry_id)
        if entry is None:
            raise ModelUnavailableError(
                "That model version is not in the registry.", details={"entry_id": str(entry_id)}
            )
        self._deactivate_others(entry.name, keep=entry)
        entry.stage = ModelStage.PRODUCTION
        entry.is_active = True
        self.db.commit()
        self.db.refresh(entry)
        _cache.pop(entry.name, None)  # force reload on next request
        logger.info(
            "model_activated",
            extra={
                "extra_fields": {
                    "model": entry.name,
                    "version": entry.version,
                    "actor": str(actor_id),
                }
            },
        )
        return entry

    def list_entries(
        self, *, name: str | None = None, include_archived: bool = False
    ) -> list[ModelRegistryEntry]:
        stmt = select(ModelRegistryEntry)
        if name:
            stmt = stmt.where(ModelRegistryEntry.name == name)
        if not include_archived:
            stmt = stmt.where(ModelRegistryEntry.stage != ModelStage.ARCHIVED)
        return list(
            self.db.execute(
                stmt.order_by(ModelRegistryEntry.name, ModelRegistryEntry.trained_at.desc())
            ).scalars()
        )

    def active_entry(self, name: str) -> ModelRegistryEntry | None:
        return (
            self.db.execute(
                select(ModelRegistryEntry)
                .where(ModelRegistryEntry.name == name, ModelRegistryEntry.is_active.is_(True))
                .order_by(ModelRegistryEntry.trained_at.desc())
            )
            .scalars()
            .first()
        )

    def record_evaluation(
        self,
        *,
        model_name: str,
        model_version: str,
        evaluation_type: str,
        metrics: dict[str, Any],
        dataset_version: str | None = None,
        sample_count: int = 0,
        confusion_matrix: list | None = None,
        per_class_metrics: list | None = None,
        notes: str | None = None,
    ) -> ModelEvaluation:
        row = ModelEvaluation(
            model_name=model_name,
            model_version=model_version,
            evaluation_type=evaluation_type,
            dataset_version=dataset_version,
            sample_count=sample_count,
            metrics=metrics,
            confusion_matrix=confusion_matrix or [],
            per_class_metrics=per_class_metrics or [],
            notes=notes,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # -------------------------------------------------------------- artefacts
    def available_versions(self, name: str) -> list[str]:
        return available_versions(name)


def load_model_handle(
    name: str, *, version: str | None = None, db: Session | None = None
) -> ModelHandle:
    """Load (and cache) the artefact directory for a model.

    Raises ModelUnavailableError with an actionable reason when the artefact is
    not present, so the API can degrade explicitly.
    """
    pinned = pinned_version(name)
    cache_key = f"{name}:{version or pinned or 'active'}"
    with _lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    # Resolution order: explicit argument > registry's active entry > deployment pin
    # > newest installed version. A pin therefore wins over "newest on disk", which
    # is what makes ML_*_MODEL_VERSION a usable rollback lever.
    if db is not None:
        entry = ModelRegistryService(db).active_entry(name)
        if entry is not None:
            version = version or entry.version
    if version is None:
        version = pinned
    if version is None:
        available = available_versions(name)
        if available:
            version = available[-1]

    if pinned and version != pinned:
        # Serving something other than what was pinned is a configuration surprise
        # worth a log line, even when it is the documented fallback.
        logger.info(
            "model_version_differs_from_pin",
            extra={"extra_fields": {"model": name, "pinned": pinned, "serving": version}},
        )

    directory = artifact_path(name, version)
    if not directory.exists() or not any(directory.iterdir()):
        installed = available_versions(name)
        if version and installed:
            message = (
                f"Model '{name}' version '{version}' is not installed "
                f"(installed versions: {', '.join(installed)})."
            )
        else:
            message = f"No trained model artefact is installed for '{name}'."
        raise ModelUnavailableError(
            message,
            details={
                "model": name,
                "requested_version": version,
                "pinned_version": pinned,
                "installed_versions": available_versions(name),
                "searched_path": str(directory),
                "how_to_fix": (
                    f"Train and export the model (python -m ai.{name.replace('-', '_')}.train) so artefacts are "
                    f"written to {settings.models_path / name}/<version>/, or set ML_MODELS_DIR to a volume "
                    "containing the exported model."
                ),
            },
        )

    card = _read_json(directory / "model_card.json")
    handle = ModelHandle(
        name=name,
        version=str(card.get("version") or version or directory.name),
        task=str(card.get("task") or name),
        framework=str(card.get("framework") or "unknown"),
        artifact_dir=directory,
        metrics=card.get("metrics") or {},
        training_data=card.get("training_data") or {},
        mlflow_run_id=card.get("mlflow_run_id"),
    )
    with _lock:
        _cache[cache_key] = handle
    return handle


def clear_model_cache() -> None:
    with _lock:
        _cache.clear()
