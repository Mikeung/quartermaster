"""
Runtime self-checks — operational health verification for deployment readiness.

Checks:
1. Scheduler health (running, no degraded jobs, no stale jobs)
2. Stale snapshots (latest snapshot not too old)
3. Schema validity (latest snapshot passes schema v1.0)
4. Snapshot count (not approaching retention limits)
5. Storage pressure (disk usage and DB size)
6. Scan error rate (no runaway consecutive failures)

All checks are read-only. No mutations. Advisory output only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Stale snapshot threshold: if latest snapshot is older than this many seconds, flag it
_STALE_SNAPSHOT_SECONDS = 1800  # 30 minutes


@dataclass
class SelfCheckItem:
    name: str
    passed: bool
    message: str
    severity: str  # "ok" | "warning" | "critical"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
            "details": self.details,
        }


@dataclass
class SelfCheckReport:
    items: list[SelfCheckItem]
    overall_status: str  # "ok" | "warning" | "critical"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.items if i.passed)

    @property
    def failed_count(self) -> int:
        return len(self.items) - self.passed_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "total": len(self.items),
            "items": [i.to_dict() for i in self.items],
            "generated_at": self.generated_at,
            "advisory": "Self-check reflects observed state — all decisions require human review.",
        }

    def markdown(self) -> str:
        status_icon = {"ok": "OK", "warning": "WARNING", "critical": "CRITICAL"}.get(
            self.overall_status, self.overall_status.upper()
        )
        lines = [
            "# System Self-Check Report",
            f"**Generated:** {self.generated_at}",
            f"**Overall status:** {status_icon}",
            f"**Checks passed:** {self.passed_count}/{len(self.items)}",
            "",
        ]
        for item in self.items:
            icon = "PASS" if item.passed else "FAIL"
            lines.append(f"## [{icon}] {item.name}")
            lines.append(f"**Severity:** {item.severity}")
            lines.append(item.message)
            if item.details:
                for k, v in item.details.items():
                    lines.append(f"- **{k}:** {v}")
            lines.append("")

        lines += [
            "---",
            "*Advisory only — all operational decisions require human review.*",
        ]
        return "\n".join(lines)


class SystemSelfChecker:
    """
    Runs a battery of runtime self-checks and returns a SelfCheckReport.

    All inputs are passed in — no global state accessed directly.
    Designed to be called at startup or via the /operations/selfcheck endpoint.
    """

    def run(
        self,
        *,
        scheduler_health: dict[str, Any] | None = None,
        latest_snapshot: dict[str, Any] | None = None,
        snapshot_count: int = 0,
        max_snapshot_count: int = 200,
        storage_estimate: dict[str, Any] | None = None,
        schema_validation: dict[str, Any] | None = None,
        delivery_health: dict[str, Any] | None = None,
    ) -> SelfCheckReport:
        items: list[SelfCheckItem] = []

        items.append(self._check_scheduler(scheduler_health))
        items.append(self._check_stale_snapshot(latest_snapshot))
        items.append(self._check_schema(schema_validation))
        items.append(self._check_snapshot_count(snapshot_count, max_snapshot_count))
        items.append(self._check_storage(storage_estimate))
        if delivery_health is not None:
            items.append(self._check_delivery(delivery_health))

        overall = self._compute_overall(items)
        logger.info(
            "Self-check completed",
            extra={"overall": overall, "passed": sum(1 for i in items if i.passed)},
        )
        return SelfCheckReport(items=items, overall_status=overall)

    # ------------------------------------------------------------------

    def _check_scheduler(self, health: dict[str, Any] | None) -> SelfCheckItem:
        if health is None:
            return SelfCheckItem(
                name="Scheduler Health",
                passed=False,
                message="Scheduler health data not available.",
                severity="warning",
            )

        running = health.get("running", False)
        degraded = health.get("degraded_jobs", [])
        stale = health.get("stale_jobs", [])
        overall = health.get("overall_status", "unknown")

        if not running:
            return SelfCheckItem(
                name="Scheduler Health",
                passed=False,
                message="Scheduler is not running — periodic scans are not executing.",
                severity="critical",
                details={"status": overall},
            )

        if degraded:
            return SelfCheckItem(
                name="Scheduler Health",
                passed=False,
                message=f"{len(degraded)} scan job(s) are degraded (consecutive error threshold reached).",
                severity="warning",
                details={"degraded_jobs": degraded},
            )

        if stale:
            return SelfCheckItem(
                name="Scheduler Health",
                passed=False,
                message=f"{len(stale)} scan job(s) appear stale (last success > 3x interval ago).",
                severity="warning",
                details={"stale_jobs": stale},
            )

        return SelfCheckItem(
            name="Scheduler Health",
            passed=True,
            message="Scheduler is running. All scan jobs healthy.",
            severity="ok",
            details={"job_count": health.get("job_count", 0)},
        )

    def _check_stale_snapshot(self, snapshot: dict[str, Any] | None) -> SelfCheckItem:
        if snapshot is None:
            return SelfCheckItem(
                name="Latest Snapshot Freshness",
                passed=False,
                message="No snapshots found — system has not completed an initial scan.",
                severity="warning",
            )

        created_at = snapshot.get("created_at", "")
        try:
            ts = datetime.fromisoformat(created_at.replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            age_seconds = (datetime.now(UTC) - ts).total_seconds()
            if age_seconds > _STALE_SNAPSHOT_SECONDS:
                return SelfCheckItem(
                    name="Latest Snapshot Freshness",
                    passed=False,
                    message=(
                        f"Latest snapshot is {int(age_seconds / 60)} minutes old. "
                        "Scans may not be running."
                    ),
                    severity="warning",
                    details={"created_at": created_at, "age_minutes": int(age_seconds / 60)},
                )
        except (ValueError, AttributeError):
            return SelfCheckItem(
                name="Latest Snapshot Freshness",
                passed=False,
                message="Latest snapshot has an unparseable timestamp.",
                severity="warning",
                details={"created_at": created_at},
            )

        return SelfCheckItem(
            name="Latest Snapshot Freshness",
            passed=True,
            message="Latest snapshot is fresh.",
            severity="ok",
            details={"created_at": created_at},
        )

    def _check_schema(self, validation: dict[str, Any] | None) -> SelfCheckItem:
        if validation is None:
            return SelfCheckItem(
                name="Snapshot Schema Validity",
                passed=True,
                message="Schema validation not run — no snapshot data available.",
                severity="ok",
            )

        valid = validation.get("valid", True)
        violations = validation.get("violations", [])
        errors = [v for v in violations if v.get("severity") == "error"]

        if not valid and errors:
            return SelfCheckItem(
                name="Snapshot Schema Validity",
                passed=False,
                message=f"Latest snapshot has {len(errors)} schema error(s).",
                severity="warning",
                details={"error_count": len(errors), "violation_count": len(violations)},
            )

        return SelfCheckItem(
            name="Snapshot Schema Validity",
            passed=True,
            message="Latest snapshot passes schema validation.",
            severity="ok",
            details={"violation_count": len(violations)},
        )

    def _check_snapshot_count(self, count: int, max_count: int) -> SelfCheckItem:
        if max_count <= 0:
            return SelfCheckItem(
                name="Snapshot Count",
                passed=True,
                message="Snapshot count check skipped — max_snapshot_count not configured.",
                severity="ok",
            )

        fraction = count / max_count
        if fraction >= 0.95:
            return SelfCheckItem(
                name="Snapshot Count",
                passed=False,
                message=(
                    f"Snapshot count {count}/{max_count} ({fraction:.0%}) — "
                    "at capacity. Run retention."
                ),
                severity="critical",
                details={"count": count, "max": max_count, "fraction": round(fraction, 3)},
            )
        if fraction >= 0.80:
            return SelfCheckItem(
                name="Snapshot Count",
                passed=False,
                message=(
                    f"Snapshot count {count}/{max_count} ({fraction:.0%}) — "
                    "approaching limit. Consider scheduling retention."
                ),
                severity="warning",
                details={"count": count, "max": max_count, "fraction": round(fraction, 3)},
            )

        return SelfCheckItem(
            name="Snapshot Count",
            passed=True,
            message=f"Snapshot count {count}/{max_count} ({fraction:.0%}) — within limits.",
            severity="ok",
            details={"count": count, "max": max_count},
        )

    def _check_storage(self, storage: dict[str, Any] | None) -> SelfCheckItem:
        if storage is None:
            return SelfCheckItem(
                name="Storage Pressure",
                passed=True,
                message="Storage estimate not available — skipped.",
                severity="ok",
            )

        pressure = storage.get("pressure_level", "ok")
        disk_pct = storage.get("disk_usage_percent", 0.0)
        observations = storage.get("observations", [])

        if pressure == "critical":
            return SelfCheckItem(
                name="Storage Pressure",
                passed=False,
                message=f"Storage pressure critical — disk {disk_pct:.0f}% used.",
                severity="critical",
                details={"disk_usage_percent": disk_pct, "observations": observations},
            )
        if pressure == "warning":
            return SelfCheckItem(
                name="Storage Pressure",
                passed=False,
                message=f"Storage pressure elevated — disk {disk_pct:.0f}% used.",
                severity="warning",
                details={"disk_usage_percent": disk_pct, "observations": observations},
            )

        return SelfCheckItem(
            name="Storage Pressure",
            passed=True,
            message=f"Storage pressure normal — disk {disk_pct:.0f}% used.",
            severity="ok",
            details={"disk_usage_percent": disk_pct},
        )

    def _check_delivery(self, delivery: dict[str, Any]) -> SelfCheckItem:
        enabled = delivery.get("telegram_enabled", False)
        if not enabled:
            return SelfCheckItem(
                name="Telegram Delivery",
                passed=True,
                message="Telegram delivery is disabled — no delivery health to check.",
                severity="ok",
            )

        failure_count = delivery.get("failure_count", 0)
        success_count = delivery.get("success_count", 0)
        last_failure = delivery.get("last_failure_error")
        error_rate = delivery.get("error_rate", 0.0)

        if failure_count > 0 and success_count == 0:
            return SelfCheckItem(
                name="Telegram Delivery",
                passed=False,
                message=f"Telegram delivery has {failure_count} failure(s) and no successes.",
                severity="warning",
                details={
                    "failure_count": failure_count,
                    "last_error": last_failure or "unknown",
                },
            )

        if error_rate >= 0.5:
            return SelfCheckItem(
                name="Telegram Delivery",
                passed=False,
                message=f"Telegram delivery error rate is {error_rate:.0%} — over 50%.",
                severity="warning",
                details={"error_rate": error_rate, "failure_count": failure_count},
            )

        return SelfCheckItem(
            name="Telegram Delivery",
            passed=True,
            message=(
                f"Telegram delivery operational. "
                f"{success_count} success(es), {failure_count} failure(s)."
            ),
            severity="ok",
            details={
                "success_count": success_count,
                "failure_count": failure_count,
                "avg_latency_ms": delivery.get("avg_latency_ms"),
            },
        )

    @staticmethod
    def _compute_overall(items: list[SelfCheckItem]) -> str:
        severities = {i.severity for i in items if not i.passed}
        if "critical" in severities:
            return "critical"
        if "warning" in severities:
            return "warning"
        return "ok"
