"""The background worker: the process `docker-compose*.yml` starts must exist and drain jobs.

Regression test for a real defect: the compose files ran `python -m app.workers.main`
while the module did not exist, so the worker container would have crash-looped on
start — a failure no endpoint test would ever notice.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.enums import JobKind, JobStatus
from app.workers.handlers import HANDLERS, UNIMPLEMENTED_KINDS
from app.workers.models import BackgroundJob
from app.workers.queue import JobQueue

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_worker_module_exists_and_is_importable():
    module = importlib.import_module("app.workers.main")
    assert hasattr(module, "main"), "the worker entrypoint must expose main()"


def test_compose_files_start_the_module_that_exists():
    """Whatever the compose files run must be importable in this checkout."""
    compose = (BACKEND_ROOT.parent / "docker-compose.yml").read_text()
    dev_compose = (BACKEND_ROOT.parent / "docker-compose.dev.yml").read_text()
    assert "app.workers.main" in compose, "the worker service should run the documented module"
    assert "app.workers.main" in dev_compose
    importlib.import_module("app.workers.main")  # raises ImportError if it is missing


def test_every_registered_handler_is_callable_and_unimplemented_kinds_are_named():
    for kind, handler in HANDLERS.items():
        assert callable(handler), f"{kind} is registered but not callable"
    # Job kinds with no handler must be listed, so enqueue() can refuse them
    # instead of queueing work that would fail in the worker.
    from app.core.enums import JobKind as Kinds

    declared = {kind.value for kind in Kinds}
    assert set(HANDLERS).issubset(declared), "a handler is registered for an undeclared job kind"
    assert set(UNIMPLEMENTED_KINDS).issubset(
        declared - set(HANDLERS)
    ), "UNIMPLEMENTED_KINDS must list exactly the declared kinds without a handler"


def test_worker_drains_a_real_job_and_records_the_result(db):
    """Enqueue → claim → run, against the test database."""
    job = BackgroundJob(
        kind=JobKind.EMBEDDING_REINDEX,
        status=JobStatus.QUEUED,
        payload={"batch_size": 3, "reason": "worker test"},
    )
    db.add(job)
    db.flush()

    queue = JobQueue(db)
    claimed = queue.pop_next()
    assert claimed is not None, "a queued job must be claimable"

    result = queue.run_job(claimed)
    assert result.status == "succeeded", result.error
    stored = db.execute(select(BackgroundJob).where(BackgroundJob.id == claimed)).scalar_one()
    assert stored.status == JobStatus.SUCCEEDED
    assert stored.finished_at is not None
    assert stored.result, "a successful job must record what it did"


def test_queue_never_claims_the_same_job_twice(db):
    """Two workers must not both process one job."""
    job = BackgroundJob(
        kind=JobKind.EMBEDDING_REINDEX,
        status=JobStatus.QUEUED,
        payload={"batch_size": 1},
    )
    db.add(job)
    db.flush()

    first = JobQueue(db).pop_next()
    second = JobQueue(db).pop_next()
    assert first is not None
    assert second is None, "a claimed job must no longer be visible to other workers"


def test_status_command_is_a_diagnostic_even_without_a_database():
    """`--status` is the operator's first diagnostic: it must report, never traceback."""
    completed = subprocess.run(
        [sys.executable, "-m", "app.workers.main", "--status"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = completed.stdout + completed.stderr
    # In both cases the handler registry must be visible: a broken database should
    # not hide the fact that the worker knows what it can process.
    assert "registered kinds" in output
    assert "Traceback" not in completed.stderr, "a diagnostic must not crash"

    if "UNAVAILABLE" in completed.stdout:
        # No database (e.g. a container that has not been bootstrapped yet).
        assert completed.returncode != 0, "an unavailable queue must not report success"
        assert "next step" in completed.stdout
        assert "UNIMPLEMENTED" not in completed.stdout
    else:
        assert completed.returncode == 0, completed.stderr
        assert "queue mode" in completed.stdout


@pytest.mark.parametrize("kind", ["disease_detection", "ingest_document"])
def test_enqueueing_an_unimplemented_kind_is_refused(db, kind):
    """A job nothing can process must be rejected at the door, not queued."""
    from app.core.errors import ValidationError

    with pytest.raises(ValidationError):
        JobQueue(db).enqueue(kind=JobKind(kind), payload={})


def test_model_version_pin_is_honoured_and_never_falls_back(tmp_path, monkeypatch):
    """`ML_*_MODEL_VERSION` is the documented rollback lever, so it must be real.

    Regression test: the four settings existed but nothing read them, and asking
    for a version that was not installed silently served the newest one.
    """
    import shutil

    from app.ai import registry
    from app.core.config import settings
    from app.core.errors import ModelUnavailableError

    source = settings.models_path / "crop-recommendation"
    if not source.exists() or not any(source.iterdir()):
        pytest.skip("no crop-recommendation artefact in this checkout to pin")

    # Copy the installed artefacts into a temporary models directory so the test
    # never mutates the real one.
    fake_root = tmp_path / "models"
    (fake_root / "crop-recommendation").mkdir(parents=True)
    versions = sorted(p.name for p in source.iterdir() if p.is_dir())
    for version in versions:
        shutil.copytree(source / version, fake_root / "crop-recommendation" / version)

    monkeypatch.setattr(settings, "ml_models_dir", str(fake_root))
    monkeypatch.setattr(settings, "ml_crop_rec_model_version", versions[0])
    registry.clear_model_cache()

    handle = registry.load_model_handle("crop-recommendation")
    assert handle.artifact_dir.name == versions[0], "the pinned version must be the one served"

    # A pin that is not installed must fail loudly instead of serving another version.
    monkeypatch.setattr(settings, "ml_crop_rec_model_version", "v-not-installed")
    registry.clear_model_cache()
    with pytest.raises(ModelUnavailableError) as excinfo:
        registry.load_model_handle("crop-recommendation")
    assert "v-not-installed" in excinfo.value.message
    assert excinfo.value.details["installed_versions"], "the error must list what is installed"

    # Unpinned, the newest installed version is used.
    monkeypatch.setattr(settings, "ml_crop_rec_model_version", "")
    registry.clear_model_cache()
    assert registry.load_model_handle("crop-recommendation").artifact_dir.name == versions[-1]

    # Look-alike placeholder values must not be treated as version names.
    monkeypatch.setattr(settings, "ml_crop_rec_model_version", "demo-untrained")
    assert registry.pinned_version("crop-recommendation") is None
    registry.clear_model_cache()
    monkeypatch.undo()
    registry.clear_model_cache()
