"""Worker process entrypoint.

Run with::

    python -m app.workers.main                # loop until SIGTERM/SIGINT
    python -m app.workers.main --once         # drain the queue and exit (used by tests/CI)
    python -m app.workers.main --status       # print queue depth and registered kinds

Design notes:

* The **database is the queue's source of truth** (`background_jobs`): a job is
  claimed by flipping its status to `running` in a transaction, so a worker
  restart, a Redis flush or a lost pub/sub message cannot lose work. Redis is
  only a wake-up signal, which is why this loop still works with
  `JOB_QUEUE_MODE=inline`.
* Retries and backoff live in `JobQueue.run_job`/`_retry`, not here: a handler
  that raises is retried up to `MAX_RETRIES` with exponential backoff and then
  recorded as failed with its error, so a poison job cannot spin the loop.
* Shutdown is graceful: on SIGTERM the loop stops claiming new jobs, finishes the
  job in flight, and exits — the container's stop timeout is therefore not spent
  killing a half-finished embedding run.
* The loop never invents work. Job kinds declared in the enum but with no handler
  (`UNIMPLEMENTED_KINDS`) are refused at enqueue time, so nothing here needs a
  "not implemented" branch.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from types import FrameType

import sqlalchemy as sa

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.observability import JOB_QUEUE_DEPTH
from app.database.session import session_scope
from app.workers.handlers import HANDLERS, UNIMPLEMENTED_KINDS
from app.workers.queue import JobQueue

logger = get_logger(__name__)

IDLE_SLEEP_SECONDS = 2.0
MAX_IDLE_SLEEP_SECONDS = 15.0


class Worker:
    """Claims and runs jobs until asked to stop."""

    def __init__(self, *, once: bool = False, max_jobs: int | None = None) -> None:
        self.once = once
        self.max_jobs = max_jobs
        self._stop = False
        self.processed = 0

    # ------------------------------------------------------------------ signals
    def install_signal_handlers(self) -> None:
        def _handler(signum: int, _frame: FrameType | None) -> None:
            # Only sets a flag: the job in flight still completes.
            logger.info("worker_shutdown_requested", extra={"signal": signal.Signals(signum).name})
            self._stop = True

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    # --------------------------------------------------------------- main loop
    def run(self) -> int:
        queue = JobQueue()
        logger.info(
            "worker_started",
            extra={
                "queue_mode": queue.mode,
                "handlers": sorted(HANDLERS),
                "unimplemented_kinds": list(UNIMPLEMENTED_KINDS),
                "environment": settings.app_env,
            },
        )
        idle_sleep = IDLE_SLEEP_SECONDS
        while not self._stop:
            job_id = queue.pop_next()
            if job_id is None:
                if self.once:
                    break
                # Back off while idle so an idle worker is cheap on the database,
                # but snap back to a short sleep as soon as work arrives.
                time.sleep(idle_sleep)
                idle_sleep = min(idle_sleep * 1.5, MAX_IDLE_SLEEP_SECONDS)
                self._publish_depth(queue)
                continue
            idle_sleep = IDLE_SLEEP_SECONDS
            # `run_job` already increments dv_jobs_total{kind,status} and records the
            # failure reason, so the loop only tracks its own progress counter.
            result = queue.run_job(job_id)
            self.processed += 1
            logger.info(
                "worker_job_finished",
                extra={
                    "job_id": str(result.job_id),
                    "status": result.status,
                    "error": result.error,
                    "processed_total": self.processed,
                },
            )
            self._publish_depth(queue)
            if self.max_jobs is not None and self.processed >= self.max_jobs:
                break
        logger.info("worker_stopped", extra={"processed_total": self.processed})
        return 0

    @staticmethod
    def _publish_depth(queue: JobQueue) -> None:
        try:
            JOB_QUEUE_DEPTH.set(queue.pending_count())
        except Exception as exc:
            logger.debug("queue_depth_publish_failed", extra={"error": str(exc)[:200]})


def print_status() -> int:
    """Operator helper: what would this worker process, and is anything waiting?

    Deliberately never raises: the first thing an operator runs when the worker
    misbehaves should print a diagnosable message, not a traceback. An unreachable
    database is reported as such, with a non-zero exit code so a healthcheck or a
    monitoring probe still fails loudly.
    """
    try:
        queue = JobQueue()
        stats = queue.stats()
    except Exception as exc:
        database = getattr(settings, "database_url", "") or "unset"
        host = database.split("@")[-1].split("/")[0] if "@" in database else database
        print("worker status: UNAVAILABLE")
        print(f"reason        : {type(exc).__name__}: {str(exc)[:200]}")
        print(f"database host : {host}  (credentials are never printed)")
        print("next step     : start PostgreSQL/Redis with scripts/dev_bootstrap.sh")
        print(f"registered kinds: {', '.join(sorted(HANDLERS))}")
        return 2
    by_status = stats.get("by_status", {})
    print(f"queue mode        : {stats.get('mode', queue.mode)}")
    print(f"queue backend     : {stats.get('queue_backend', 'unknown')}")
    for status in ("queued", "running", "succeeded", "failed"):
        print(f"{status:<18}: {by_status.get(status, 0)}")
    print(f"registered kinds  : {', '.join(sorted(HANDLERS))}")
    print(f"declared, no handler yet: {', '.join(UNIMPLEMENTED_KINDS) or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Digital Village background worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    parser.add_argument("--max-jobs", type=int, default=None, help="stop after N jobs (testing)")
    parser.add_argument("--status", action="store_true", help="print queue status and exit")
    args = parser.parse_args(argv)

    configure_logging()
    if args.status:
        return print_status()

    worker = Worker(once=args.once, max_jobs=args.max_jobs)
    worker.install_signal_handlers()
    # A single cheap query at startup: failing loudly here is far better than a
    # container that runs for hours and discovers the database is gone on the
    # first job.
    with session_scope() as db:
        db.execute(sa.text("SELECT 1"))
    return worker.run()


if __name__ == "__main__":
    sys.exit(main())
