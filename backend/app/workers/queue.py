"""Background job queue.

Design:
  * every job is a row in `background_jobs` (durable, queryable, shows up in the
    admin console) plus either a Redis list entry (distributed workers) or an
    inline execution (single-node development);
  * `JOB_QUEUE_MODE=auto` (default) uses Redis when it is reachable and otherwise
    runs the handler in-process, so a laptop without Redis still has working
    embeddings, ingestion and notification fan-out;
  * handlers are registered by kind, executed with retries and exponential
    backoff, and every attempt updates the row so failures are visible rather
    than silent;
  * deduplication uses `dedupe_key` so a burst of identical requests (e.g. 50
    people triggering the same reindex) enqueues one job.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import settings
from app.core.enums import JobKind, JobStatus
from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.observability import JOB_COUNTER, JOB_QUEUE_DEPTH
from app.database.base import utcnow
from app.database.session import session_scope
from app.workers.models import BackgroundJob

logger = get_logger(__name__)

QUEUE_KEY = "dv:jobs:queue"
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 15


@dataclass(slots=True)
class JobResult:
    job_id: uuid.UUID
    status: str
    mode: str
    result: dict[str, Any] | None = None
    error: str | None = None


class JobQueue:
    def __init__(self, db: Session | None = None) -> None:
        self._db = db
        self.cache = get_cache()

    @property
    def mode(self) -> str:
        if settings.job_queue_mode == "inline":
            return "inline"
        if settings.job_queue_mode == "redis":
            return "redis"
        return "redis" if self.cache.available else "inline"

    # --------------------------------------------------------------- enqueue
    def enqueue(
        self,
        *,
        kind: JobKind | str,
        payload: dict[str, Any],
        requested_by_id: uuid.UUID | None = None,
        delay_seconds: int = 0,
        dedupe_key: str | None = None,
        run_inline: bool | None = None,
        max_attempts: int = MAX_RETRIES,
    ) -> JobResult:
        kind_value = kind.value if isinstance(kind, JobKind) else str(kind)
        # Refuse what we cannot process. Silently substituting a different kind
        # would run an unrelated handler against the caller's payload — the worst
        # possible outcome, because it looks like it worked.
        declared = {member.value for member in JobKind}
        if kind_value not in declared:
            raise ValidationError(
                "Unknown background job kind.",
                details={"kind": kind_value, "declared": sorted(declared)},
            )
        from app.workers.handlers import UNIMPLEMENTED_KINDS

        if kind_value in UNIMPLEMENTED_KINDS:
            raise ValidationError(
                f"No handler is implemented for the '{kind_value}' job kind yet, so it was not queued.",
                details={"kind": kind_value, "unimplemented": list(UNIMPLEMENTED_KINDS)},
            )
        scheduled_at = datetime.now(UTC) + timedelta(seconds=max(0, delay_seconds))

        with self._session() as db:
            if dedupe_key:
                existing = db.execute(
                    select(BackgroundJob).where(
                        BackgroundJob.dedupe_key == dedupe_key,
                        BackgroundJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return JobResult(
                        job_id=existing.id,
                        status=existing.status.value,
                        mode=self.mode,
                        result={"deduplicated": True},
                    )
            job = BackgroundJob(
                kind=JobKind(kind_value),
                status=JobStatus.QUEUED,
                payload=payload,
                scheduled_at=scheduled_at,
                max_attempts=max_attempts,
                dedupe_key=dedupe_key,
                requested_by_id=requested_by_id,
            )
            db.add(job)
            db.flush()
            job_id = job.id
            db.commit()

        inline = run_inline if run_inline is not None else self.mode == "inline"
        if inline and delay_seconds == 0:
            return self.run_job(job_id)
        if self.cache.available:
            self.cache.set(
                f"{QUEUE_KEY}:{job_id}",
                json.dumps({"kind": kind_value, "at": scheduled_at.isoformat()}),
                ttl=None,
            )
            self._push_to_redis(job_id)
        JOB_QUEUE_DEPTH.set(self.pending_count())
        return JobResult(job_id=job_id, status="queued", mode=self.mode)

    def _push_to_redis(self, job_id: uuid.UUID) -> None:
        try:
            client = getattr(self.cache, "_redis", None)
            if client is not None:
                client.rpush(QUEUE_KEY, str(job_id))
        except Exception as exc:
            logger.warning("job_push_failed", extra={"extra_fields": {"error": str(exc)[:150]}})

    def pop_next(self) -> uuid.UUID | None:
        """Claim the next due job (worker loop). Uses the DB as the source of
        truth so a lost Redis entry never loses a job."""
        with self._session() as db:
            job = db.execute(
                select(BackgroundJob)
                .where(
                    BackgroundJob.status == JobStatus.QUEUED,
                    BackgroundJob.scheduled_at <= datetime.now(UTC),
                )
                .order_by(BackgroundJob.scheduled_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            if job is None:
                return None
            job.status = JobStatus.RUNNING
            job.started_at = utcnow()
            job.attempts += 1
            db.commit()
            JOB_QUEUE_DEPTH.set(self.pending_count())
            return job.id

    def pending_count(self) -> int:
        with self._session() as db:
            return int(
                db.execute(select(BackgroundJob.id).where(BackgroundJob.status == JobStatus.QUEUED))
                .scalars()
                .all()
                .__len__()
            )

    # ------------------------------------------------------------------- run
    def run_job(self, job_id: uuid.UUID) -> JobResult:
        from app.workers.handlers import HANDLERS

        with self._session() as db:
            job = db.get(BackgroundJob, job_id)
            if job is None:
                return JobResult(
                    job_id=job_id, status="missing", mode=self.mode, error="job row not found"
                )
            if job.status == JobStatus.SUCCEEDED:
                return JobResult(
                    job_id=job_id, status="succeeded", mode=self.mode, result=job.result
                )
            job.status = JobStatus.RUNNING
            job.started_at = job.started_at or utcnow()
            job.attempts += 1
            kind_value = job.kind.value
            payload = dict(job.payload or {})
            attempts = job.attempts
            max_attempts = job.max_attempts
            db.commit()

        handler: Callable[..., dict[str, Any]] | None = HANDLERS.get(kind_value)
        if handler is None:
            return self._finish(
                job_id, status=JobStatus.FAILED, error=f"No handler registered for '{kind_value}'"
            )

        started = time.perf_counter()
        try:
            with session_scope() as handler_db:
                result = handler(handler_db, payload) or {}
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            JOB_COUNTER.labels(kind=kind_value, status="succeeded").inc()
            logger.info(
                "job_succeeded",
                extra={"extra_fields": {"kind": kind_value, "latency_ms": elapsed_ms}},
            )
            return self._finish(job_id, status=JobStatus.SUCCEEDED, result=result)
        except Exception as exc:
            JOB_COUNTER.labels(kind=kind_value, status="failed").inc()
            message = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "job_failed", extra={"extra_fields": {"kind": kind_value, "error": message}}
            )
            if attempts < max_attempts:
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
                self._retry(job_id, delay)
                return JobResult(
                    job_id=job_id, status="retry_scheduled", mode=self.mode, error=message
                )
            return self._finish(job_id, status=JobStatus.FAILED, error=message)

    def _retry(self, job_id: uuid.UUID, delay_seconds: int) -> None:
        with self._session() as db:
            job = db.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = JobStatus.QUEUED
            job.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
            db.commit()

    def _finish(
        self,
        job_id: uuid.UUID,
        *,
        status: JobStatus,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobResult:
        with self._session() as db:
            job = db.get(BackgroundJob, job_id)
            if job is None:
                return JobResult(job_id=job_id, status=status.value, mode=self.mode, error=error)
            job.status = status
            job.result = result
            job.last_error = error
            job.progress = 100 if status == JobStatus.SUCCEEDED else job.progress
            job.finished_at = utcnow()
            db.commit()
        JOB_QUEUE_DEPTH.set(self.pending_count())
        return JobResult(
            job_id=job_id, status=status.value, mode=self.mode, result=result, error=error
        )

    def _session(self):
        if self._db is not None:
            return _BorrowedSession(self._db)
        return session_scope()

    # ------------------------------------------------------------------ admin
    def status(self, job_id: uuid.UUID) -> dict[str, Any] | None:
        with self._session() as db:
            job = db.get(BackgroundJob, job_id)
            if job is None:
                return None
            return job.to_public()

    def stats(self) -> dict[str, Any]:
        with self._session() as db:
            rows = db.execute(select(BackgroundJob.status, BackgroundJob.kind)).all()
        counts: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for status, kind in rows:
            status_value = status.value if hasattr(status, "value") else str(status)
            kind_value = kind.value if hasattr(kind, "value") else str(kind)
            counts[status_value] = counts.get(status_value, 0) + 1
            kinds[kind_value] = kinds.get(kind_value, 0) + 1
        return {
            "mode": self.mode,
            "queue_backend": self.cache.backend,
            "by_status": counts,
            "by_kind": kinds,
        }


class _BorrowedSession:
    """Context manager that does not close a caller-owned session."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def __enter__(self) -> Session:
        return self.db

    def __exit__(self, *_exc: Any) -> bool:
        return False


def enqueue_job(**kwargs: Any) -> JobResult:
    return JobQueue().enqueue(**kwargs)
