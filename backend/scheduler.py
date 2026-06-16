"""
Operational scheduler — periodic scan orchestration.

Single-process. Observable. No distributed workers.
Hardened for VPS deployment:
- configurable misfire_grace_time
- last-successful-scan tracking
- stale scan detection
- bounded error counting per job
- scheduler health status
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_ERRORS = 5  # threshold before job flagged as degraded


class OperationalScheduler:
    """Runs periodic scan jobs in a background thread.

    Single-process. Observable. No distributed workers.
    """

    def __init__(self, grace_seconds: int = 60) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
        self._grace_seconds = grace_seconds
        self._lock = threading.Lock()
        self._last_success: dict[str, str] = {}   # job_id → ISO timestamp
        self._error_counts: dict[str, int] = {}   # job_id → consecutive error count
        self._total_runs: dict[str, int] = {}     # job_id → total run count
        self._intervals: dict[str, int] = {}      # job_id → interval_seconds

    def register_scan(
        self,
        scan_func: Callable[[str], Any],
        targets: list[str],
        interval_seconds: int,
    ) -> None:
        for target in targets:
            job_id = f"scan_{abs(hash(target))}"
            self._intervals[job_id] = interval_seconds

            def _wrapped(t: str = target, jid: str = job_id) -> None:
                self._run_with_tracking(scan_func, t, jid)

            self._scheduler.add_job(
                _wrapped,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id=job_id,
                replace_existing=True,
                misfire_grace_time=self._grace_seconds,
                coalesce=True,
            )
            logger.info(
                "Scan job registered",
                extra={
                    "target": target,
                    "interval_s": interval_seconds,
                    "job_id": job_id,
                    "grace_s": self._grace_seconds,
                },
            )

    def _run_with_tracking(
        self, scan_func: Callable[[str], Any], target: str, job_id: str
    ) -> None:
        with self._lock:
            self._total_runs[job_id] = self._total_runs.get(job_id, 0) + 1

        try:
            scan_func(target)
            with self._lock:
                self._last_success[job_id] = datetime.now(UTC).isoformat()
                self._error_counts[job_id] = 0
            logger.info("Scan job completed", extra={"job_id": job_id, "target": target})
        except Exception as exc:
            with self._lock:
                self._error_counts[job_id] = self._error_counts.get(job_id, 0) + 1
                count = self._error_counts[job_id]
            logger.error(
                "Scan job failed",
                extra={
                    "job_id": job_id,
                    "target": target,
                    "error": str(exc),
                    "consecutive_errors": count,
                },
            )
            if count >= _MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "Scan job degraded — consecutive error threshold reached",
                    extra={"job_id": job_id, "threshold": _MAX_CONSECUTIVE_ERRORS},
                )

    def register_cron_job(
        self,
        fn: Callable[[], Any],
        job_id: str,
        hour: int,
        minute: int = 0,
        day_of_week: str | None = None,
    ) -> None:
        """Register a daily (or weekly) cron-style delivery job."""
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=day_of_week,
            timezone="UTC",
        )

        def _wrapped(jid: str = job_id) -> None:
            self._run_with_tracking(fn, jid, jid)

        self._scheduler.add_job(
            _wrapped,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=self._grace_seconds,
            coalesce=True,
        )
        self._intervals[job_id] = 86400  # treat as ~daily for staleness detection
        logger.info(
            "Cron job registered",
            extra={
                "job_id": job_id,
                "hour": hour,
                "minute": minute,
                "day_of_week": day_of_week or "daily",
            },
        )

    def start(self) -> None:
        self._scheduler.start()
        logger.info(
            "Scheduler started",
            extra={"job_count": len(self._scheduler.get_jobs())},
        )

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def is_running(self) -> bool:
        return self._scheduler.running

    def get_jobs_info(self) -> list[dict[str, Any]]:
        with self._lock:
            last_success = dict(self._last_success)
            error_counts = dict(self._error_counts)
            total_runs = dict(self._total_runs)

        jobs = []
        for job in self._scheduler.get_jobs():
            jid = job.id
            consecutive_errors = error_counts.get(jid, 0)
            status = "degraded" if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS else "ok"
            jobs.append(
                {
                    "id": jid,
                    "next_run": str(job.next_run_time),
                    "trigger": str(job.trigger),
                    "last_success": last_success.get(jid),
                    "consecutive_errors": consecutive_errors,
                    "total_runs": total_runs.get(jid, 0),
                    "status": status,
                }
            )
        return jobs

    def get_health_status(self) -> dict[str, Any]:
        """Return a scheduler health summary for self-check and monitoring."""
        running = self.is_running()
        jobs_info = self.get_jobs_info() if running else []
        degraded_jobs = [j for j in jobs_info if j["status"] == "degraded"]
        stale_jobs = self._find_stale_jobs(jobs_info)

        overall = "ok"
        if not running:
            overall = "stopped"
        elif degraded_jobs or stale_jobs:
            overall = "degraded"

        return {
            "running": running,
            "overall_status": overall,
            "job_count": len(jobs_info),
            "degraded_jobs": [j["id"] for j in degraded_jobs],
            "stale_jobs": [j["id"] for j in stale_jobs],
            "jobs": jobs_info,
        }

    def _find_stale_jobs(self, jobs_info: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Jobs whose last_success is older than 3x their interval are considered stale."""
        stale = []
        now = datetime.now(UTC)
        with self._lock:
            intervals = dict(self._intervals)

        for job in jobs_info:
            jid = job["id"]
            last_ok = job.get("last_success")
            if last_ok is None:
                continue
            interval = intervals.get(jid, 300)
            try:
                ts = datetime.fromisoformat(last_ok)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age_seconds = (now - ts).total_seconds()
                if age_seconds > interval * 3:
                    stale.append(job)
            except (ValueError, TypeError):
                pass
        return stale
