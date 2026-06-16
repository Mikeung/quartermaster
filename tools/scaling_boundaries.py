"""
Scaling Boundary Validation — make operational limits explicit.

Purpose:
Assess whether the current operational footprint is approaching the known
scaling boundaries of a single-VPS SQLite deployment. This is not predictive
ML — it uses explicit threshold reasoning against measured metrics.

Checks:
1. Snapshot volume boundary — total snapshots vs. comfortable operating range
2. LLM event volume boundary — total events vs. storage/query pressure
3. Query latency boundary — estimated query time vs. user-acceptable threshold
4. Report generation boundary — report complexity vs. generation time envelope
5. SQLite contention indicators — write frequency vs. WAL checkpoint pressure
6. Cognition runtime boundary — number of active recommendations vs. pipeline cost

Design rules:
- Observational only. Never modifies state.
- All inputs are pre-fetched scalars/dicts. No direct DB access here.
- Deterministic: same inputs → same output.
- Bounded language throughout.
- Explicitly surface the "operating envelope" so operators know limits before they hit them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Operating envelope thresholds
# These are the recommended operating ranges for a single-VPS SQLite deployment.
# Not hard limits — advisory boundaries. Exceeding them degrades performance.
# -----------------------------------------------------------------------

# Snapshot volume
_SNAPSHOT_WARN = 5_000          # 5k snapshots → queries start slowing
_SNAPSHOT_CRITICAL = 20_000     # 20k → significant query latency expected

# LLM event volume
_EVENT_WARN = 50_000            # 50k events → aggregation queries slow
_EVENT_CRITICAL = 200_000       # 200k → noticeable UI/report delays

# Query latency (seconds, estimated from volume)
# Estimated linear scaling from SQLite benchmark: ~0.5ms per 1000 rows for simple queries
_QUERY_LATENCY_WARN_S = 2.0     # 2s = user starts noticing
_QUERY_LATENCY_CRITICAL_S = 8.0 # 8s = unacceptable for interactive use

# Report generation (seconds)
_REPORT_LATENCY_WARN_S = 10.0
_REPORT_LATENCY_CRITICAL_S = 30.0

# SQLite WAL / write pressure
# At >10 writes/second sustained, WAL checkpointing may lag
_WRITES_PER_HOUR_WARN = 5_000   # ~1.4/s average
_WRITES_PER_HOUR_CRITICAL = 36_000  # 10/s average

# Cognition pipeline: recommendations per run
_RECS_PER_SNAPSHOT_WARN = 150   # above this, consolidation + dedup take significant time
_RECS_PER_SNAPSHOT_CRITICAL = 400  # at this volume, consider batching or sampling

# DB file size
_DB_SIZE_WARN_BYTES = 200 * 1024 * 1024    # 200 MB
_DB_SIZE_CRITICAL_BYTES = 1024 * 1024 * 1024  # 1 GB


# -----------------------------------------------------------------------
# Output types
# -----------------------------------------------------------------------

@dataclass
class BoundaryCheck:
    """Result of a single scaling boundary check."""
    name: str
    passed: bool
    severity: str          # "ok" | "warning" | "critical"
    current_value: float
    warn_threshold: float
    critical_threshold: float
    unit: str
    message: str
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "current_value": self.current_value,
            "warn_threshold": self.warn_threshold,
            "critical_threshold": self.critical_threshold,
            "unit": self.unit,
            "message": self.message,
            "recommendations": self.recommendations,
        }


@dataclass
class OperatingEnvelope:
    """Describes the recommended operating range for this deployment."""
    snapshot_comfortable_max: int
    event_comfortable_max: int
    db_size_comfortable_max_mb: int
    writes_per_hour_comfortable_max: int
    recs_per_snapshot_comfortable_max: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_comfortable_max": self.snapshot_comfortable_max,
            "event_comfortable_max": self.event_comfortable_max,
            "db_size_comfortable_max_mb": self.db_size_comfortable_max_mb,
            "writes_per_hour_comfortable_max": self.writes_per_hour_comfortable_max,
            "recs_per_snapshot_comfortable_max": self.recs_per_snapshot_comfortable_max,
            "notes": self.notes,
        }


@dataclass
class ScalingBoundaryReport:
    """
    Scaling readiness assessment.

    Indicates which operational dimensions are approaching or exceeding
    the recommended operating envelope for this deployment type.
    """
    overall_status: str           # "ok" | "warning" | "critical"
    checks: list[BoundaryCheck]
    passed: int
    warned: int
    critical: int
    operating_envelope: OperatingEnvelope
    scaling_outlook: str          # "comfortable" | "approaching_limits" | "at_limits"
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "scaling_outlook": self.scaling_outlook,
            "checks": [c.to_dict() for c in self.checks],
            "passed": self.passed,
            "warned": self.warned,
            "critical": self.critical,
            "total_checks": len(self.checks),
            "operating_envelope": self.operating_envelope.to_dict(),
            "observations": self.observations,
            "generated_at": self.generated_at,
            "advisory": (
                "Scaling boundary checks are observational heuristics based on typical "
                "single-VPS SQLite performance characteristics. Actual limits depend on "
                "hardware, query patterns, and workload distribution. "
                "Human review is required before any architecture changes."
            ),
        }

    def markdown(self) -> str:
        lines = [
            "# Scaling Boundary Report",
            f"Generated: {self.generated_at}",
            "",
            f"**Overall status:** {self.overall_status.upper()}  "
            f"| **Scaling outlook:** {self.scaling_outlook.replace('_', ' ')}",
            f"**Checks:** {self.passed} within bounds / {self.warned} approaching / "
            f"{self.critical} at or beyond limits",
            "",
        ]

        if self.observations:
            lines += ["## Key Observations", ""]
            for o in self.observations:
                lines.append(f"- {o}")
            lines.append("")

        lines += ["## Boundary Checks", ""]
        for c in self.checks:
            icon = "✓" if c.passed else ("⚠" if c.severity == "warning" else "✗")
            lines.append(f"### {icon} {c.name}")
            lines.append(f"Current: **{c.current_value:,.0f} {c.unit}**  "
                         f"| Warn: {c.warn_threshold:,.0f} | Critical: {c.critical_threshold:,.0f}")
            lines.append("")
            lines.append(c.message)
            if c.recommendations:
                lines.append("")
                for r in c.recommendations:
                    lines.append(f"- {r}")
            lines.append("")

        env = self.operating_envelope
        lines += [
            "## Recommended Operating Envelope",
            "",
            f"- Snapshots: up to {env.snapshot_comfortable_max:,} (current warning threshold: {_SNAPSHOT_WARN:,})",
            f"- LLM events: up to {env.event_comfortable_max:,}",
            f"- DB size: up to {env.db_size_comfortable_max_mb:,} MB",
            f"- Write rate: up to {env.writes_per_hour_comfortable_max:,} writes/hour",
            f"- Recommendations per snapshot: up to {env.recs_per_snapshot_comfortable_max}",
            "",
        ]
        if env.notes:
            for n in env.notes:
                lines.append(f"> {n}")
            lines.append("")

        lines += [
            "---",
            "_Advisory only. Scaling boundaries are heuristic estimates for single-VPS SQLite deployments. "
            "All capacity planning decisions require operator judgement._",
        ]
        return "\n".join(lines)


# -----------------------------------------------------------------------
# Checker
# -----------------------------------------------------------------------

class ScalingBoundaryChecker:
    """
    Validates that current operational metrics remain within the known
    comfortable operating envelope for a single-VPS SQLite deployment.

    All inputs are pre-fetched to keep this module stateless and testable.
    No direct database access.
    """

    def check(
        self,
        *,
        snapshot_count: int,
        llm_event_count: int,
        db_size_bytes: int,
        avg_query_latency_ms: float | None,
        avg_report_latency_ms: float | None,
        writes_per_hour_estimate: int | None,
        avg_recs_per_snapshot: float | None,
    ) -> ScalingBoundaryReport:
        """
        Run all scaling boundary checks.

        Parameters:
        - snapshot_count: total snapshots stored
        - llm_event_count: total LLM events stored
        - db_size_bytes: current DB file size
        - avg_query_latency_ms: average query latency in milliseconds (None = unknown)
        - avg_report_latency_ms: average report generation time in ms (None = unknown)
        - writes_per_hour_estimate: estimated DB writes per hour (None = unknown)
        - avg_recs_per_snapshot: average recommendation count per snapshot (None = unknown)
        """
        checks = [
            self._check_snapshot_volume(snapshot_count),
            self._check_event_volume(llm_event_count),
            self._check_db_size(db_size_bytes),
            self._check_query_latency(avg_query_latency_ms, snapshot_count, llm_event_count),
            self._check_report_latency(avg_report_latency_ms, snapshot_count),
            self._check_write_pressure(writes_per_hour_estimate),
            self._check_cognition_volume(avg_recs_per_snapshot),
        ]

        passed = sum(1 for c in checks if c.passed)
        warned = sum(1 for c in checks if not c.passed and c.severity == "warning")
        critical = sum(1 for c in checks if c.severity == "critical")

        if critical > 0:
            overall = "critical"
            outlook = "at_limits"
        elif warned >= 2:
            overall = "warning"
            outlook = "approaching_limits"
        elif warned == 1:
            overall = "warning"
            outlook = "approaching_limits"
        else:
            overall = "ok"
            outlook = "comfortable"

        envelope = self._build_envelope()
        observations = self._build_observations(checks, snapshot_count, llm_event_count)

        logger.info(
            "Scaling boundary check complete",
            extra={"overall": overall, "passed": passed, "warned": warned, "critical": critical},
        )

        return ScalingBoundaryReport(
            overall_status=overall,
            checks=checks,
            passed=passed,
            warned=warned,
            critical=critical,
            operating_envelope=envelope,
            scaling_outlook=outlook,
            observations=observations,
        )

    # -----------------------------------------------------------------------
    # Individual checks
    # -----------------------------------------------------------------------

    def _check_snapshot_volume(self, count: int) -> BoundaryCheck:
        if count >= _SNAPSHOT_CRITICAL:
            return BoundaryCheck(
                name="Snapshot Volume",
                passed=False,
                severity="critical",
                current_value=count,
                warn_threshold=_SNAPSHOT_WARN,
                critical_threshold=_SNAPSHOT_CRITICAL,
                unit="snapshots",
                message=(
                    f"Snapshot count ({count:,}) has reached the critical boundary. "
                    "Query performance may be noticeably degraded."
                ),
                recommendations=[
                    "Run retention to reduce snapshot count below warning threshold.",
                    "Consider increasing retention frequency or reducing retention_days.",
                    "If snapshots must be preserved, evaluate migrating to PostgreSQL.",
                ],
            )
        elif count >= _SNAPSHOT_WARN:
            return BoundaryCheck(
                name="Snapshot Volume",
                passed=False,
                severity="warning",
                current_value=count,
                warn_threshold=_SNAPSHOT_WARN,
                critical_threshold=_SNAPSHOT_CRITICAL,
                unit="snapshots",
                message=(
                    f"Snapshot count ({count:,}) is approaching the operating boundary. "
                    "Monitor query performance."
                ),
                recommendations=[
                    "Consider scheduling retention to keep snapshots below 5,000.",
                    "Review snapshot scan frequency if growth is faster than expected.",
                ],
            )
        return BoundaryCheck(
            name="Snapshot Volume",
            passed=True,
            severity="ok",
            current_value=count,
            warn_threshold=_SNAPSHOT_WARN,
            critical_threshold=_SNAPSHOT_CRITICAL,
            unit="snapshots",
            message=f"Snapshot volume ({count:,}) is within the comfortable operating range.",
        )

    def _check_event_volume(self, count: int) -> BoundaryCheck:
        if count >= _EVENT_CRITICAL:
            return BoundaryCheck(
                name="LLM Event Volume",
                passed=False,
                severity="critical",
                current_value=count,
                warn_threshold=_EVENT_WARN,
                critical_threshold=_EVENT_CRITICAL,
                unit="events",
                message=(
                    f"LLM event count ({count:,}) has reached the critical boundary. "
                    "Aggregation queries and cost reports may be slow."
                ),
                recommendations=[
                    "Run LLM event retention to reduce volume.",
                    "Consider reducing max_event_count in ingestion limits.",
                    "Evaluate event sampling for high-frequency workflows.",
                ],
            )
        elif count >= _EVENT_WARN:
            return BoundaryCheck(
                name="LLM Event Volume",
                passed=False,
                severity="warning",
                current_value=count,
                warn_threshold=_EVENT_WARN,
                critical_threshold=_EVENT_CRITICAL,
                unit="events",
                message=(
                    f"LLM event count ({count:,}) is approaching the operating boundary. "
                    "Cost intelligence queries may begin to slow."
                ),
                recommendations=[
                    "Schedule periodic LLM event retention (e.g., keep last 30 days).",
                ],
            )
        return BoundaryCheck(
            name="LLM Event Volume",
            passed=True,
            severity="ok",
            current_value=count,
            warn_threshold=_EVENT_WARN,
            critical_threshold=_EVENT_CRITICAL,
            unit="events",
            message=f"LLM event volume ({count:,}) is within the comfortable operating range.",
        )

    def _check_db_size(self, size_bytes: int) -> BoundaryCheck:
        size_mb = size_bytes / (1024 * 1024)
        warn_mb = _DB_SIZE_WARN_BYTES / (1024 * 1024)
        crit_mb = _DB_SIZE_CRITICAL_BYTES / (1024 * 1024)

        if size_bytes >= _DB_SIZE_CRITICAL_BYTES:
            return BoundaryCheck(
                name="Database File Size",
                passed=False,
                severity="critical",
                current_value=size_mb,
                warn_threshold=warn_mb,
                critical_threshold=crit_mb,
                unit="MB",
                message=(
                    f"Database size ({size_mb:.0f} MB) has reached the critical boundary. "
                    "SQLite WAL overhead and backup duration become significant at this scale."
                ),
                recommendations=[
                    "Run retention immediately to reduce database size.",
                    "Vacuum the database after retention to reclaim space.",
                    "If growth cannot be controlled, evaluate PostgreSQL migration.",
                ],
            )
        elif size_bytes >= _DB_SIZE_WARN_BYTES:
            return BoundaryCheck(
                name="Database File Size",
                passed=False,
                severity="warning",
                current_value=size_mb,
                warn_threshold=warn_mb,
                critical_threshold=crit_mb,
                unit="MB",
                message=(
                    f"Database size ({size_mb:.0f} MB) is approaching the comfortable boundary. "
                    "Monitor growth rate."
                ),
                recommendations=[
                    "Review retention policy frequency.",
                    "Run storage hygiene check to identify largest data sources.",
                ],
            )
        return BoundaryCheck(
            name="Database File Size",
            passed=True,
            severity="ok",
            current_value=size_mb,
            warn_threshold=warn_mb,
            critical_threshold=crit_mb,
            unit="MB",
            message=f"Database size ({size_mb:.1f} MB) is within the comfortable range.",
        )

    def _check_query_latency(
        self,
        measured_ms: float | None,
        snapshot_count: int,
        event_count: int,
    ) -> BoundaryCheck:
        if measured_ms is not None:
            latency_s = measured_ms / 1000.0
        else:
            # Estimate: 0.5ms per 1000 rows for the larger table
            row_count = max(snapshot_count, event_count)
            latency_s = (row_count / 1000.0) * 0.0005

        warn_ms = _QUERY_LATENCY_WARN_S * 1000
        crit_ms = _QUERY_LATENCY_CRITICAL_S * 1000
        actual_ms = latency_s * 1000

        note = "(measured)" if measured_ms is not None else "(estimated from row count)"

        if latency_s >= _QUERY_LATENCY_CRITICAL_S:
            return BoundaryCheck(
                name="Query Latency",
                passed=False,
                severity="critical",
                current_value=actual_ms,
                warn_threshold=warn_ms,
                critical_threshold=crit_ms,
                unit=f"ms {note}",
                message=(
                    f"Query latency {note} ({actual_ms:,.0f} ms) exceeds acceptable threshold. "
                    "Interactive queries may time out."
                ),
                recommendations=[
                    "Run retention to reduce table sizes.",
                    "Add SQLite indexes if missing on timestamp columns.",
                    "Consider query result caching for expensive aggregations.",
                ],
            )
        elif latency_s >= _QUERY_LATENCY_WARN_S:
            return BoundaryCheck(
                name="Query Latency",
                passed=False,
                severity="warning",
                current_value=actual_ms,
                warn_threshold=warn_ms,
                critical_threshold=crit_ms,
                unit=f"ms {note}",
                message=(
                    f"Query latency {note} ({actual_ms:,.0f} ms) is approaching the acceptable threshold. "
                    "Users may notice delays."
                ),
                recommendations=[
                    "Monitor actual query times in logs.",
                    "Consider running retention if data volume is the cause.",
                ],
            )
        return BoundaryCheck(
            name="Query Latency",
            passed=True,
            severity="ok",
            current_value=actual_ms,
            warn_threshold=warn_ms,
            critical_threshold=crit_ms,
            unit=f"ms {note}",
            message=f"Query latency {note} ({actual_ms:,.0f} ms) is acceptable.",
        )

    def _check_report_latency(
        self,
        measured_ms: float | None,
        snapshot_count: int,
    ) -> BoundaryCheck:
        warn_ms = _REPORT_LATENCY_WARN_S * 1000
        crit_ms = _REPORT_LATENCY_CRITICAL_S * 1000

        if measured_ms is None:
            estimated_s = max(0.5, snapshot_count / 1000.0 * 0.8)
            actual_ms = estimated_s * 1000
            note = "(estimated)"
        else:
            actual_ms = measured_ms
            note = "(measured)"

        latency_s = actual_ms / 1000.0

        if latency_s >= _REPORT_LATENCY_CRITICAL_S:
            return BoundaryCheck(
                name="Report Generation Latency",
                passed=False,
                severity="critical",
                current_value=actual_ms,
                warn_threshold=warn_ms,
                critical_threshold=crit_ms,
                unit=f"ms {note}",
                message=(
                    f"Report generation time {note} ({actual_ms:,.0f} ms) exceeds the acceptable threshold. "
                    "On-demand reports may time out."
                ),
                recommendations=[
                    "Pre-generate reports on a schedule rather than on-demand.",
                    "Reduce snapshot count via retention to decrease report scope.",
                    "Consider caching report output for frequently-requested windows.",
                ],
            )
        elif latency_s >= _REPORT_LATENCY_WARN_S:
            return BoundaryCheck(
                name="Report Generation Latency",
                passed=False,
                severity="warning",
                current_value=actual_ms,
                warn_threshold=warn_ms,
                critical_threshold=crit_ms,
                unit=f"ms {note}",
                message=(
                    f"Report generation {note} ({actual_ms:,.0f} ms) is approaching the acceptable threshold. "
                    "Monitor for further increases."
                ),
                recommendations=[
                    "Consider scheduling reports during low-traffic periods.",
                ],
            )
        return BoundaryCheck(
            name="Report Generation Latency",
            passed=True,
            severity="ok",
            current_value=actual_ms,
            warn_threshold=warn_ms,
            critical_threshold=crit_ms,
            unit=f"ms {note}",
            message=f"Report generation latency {note} ({actual_ms:,.0f} ms) is acceptable.",
        )

    def _check_write_pressure(self, writes_per_hour: int | None) -> BoundaryCheck:
        if writes_per_hour is None:
            return BoundaryCheck(
                name="SQLite Write Pressure",
                passed=True,
                severity="ok",
                current_value=0,
                warn_threshold=_WRITES_PER_HOUR_WARN,
                critical_threshold=_WRITES_PER_HOUR_CRITICAL,
                unit="writes/hour",
                message="Write pressure not available — estimate not possible without ingestion rate data.",
                recommendations=[
                    "Pass writes_per_hour_estimate from ingestion counters for accurate assessment."
                ],
            )

        if writes_per_hour >= _WRITES_PER_HOUR_CRITICAL:
            return BoundaryCheck(
                name="SQLite Write Pressure",
                passed=False,
                severity="critical",
                current_value=writes_per_hour,
                warn_threshold=_WRITES_PER_HOUR_WARN,
                critical_threshold=_WRITES_PER_HOUR_CRITICAL,
                unit="writes/hour",
                message=(
                    f"Write rate ({writes_per_hour:,}/hour) has reached the critical boundary. "
                    "SQLite WAL checkpoint lag may cause read latency spikes."
                ),
                recommendations=[
                    "Reduce ingestion rate via event sampling or batch coalescing.",
                    "Consider increasing WAL checkpoint interval if SQLite pragma access is available.",
                    "If write rate cannot be reduced, PostgreSQL may be required.",
                ],
            )
        elif writes_per_hour >= _WRITES_PER_HOUR_WARN:
            return BoundaryCheck(
                name="SQLite Write Pressure",
                passed=False,
                severity="warning",
                current_value=writes_per_hour,
                warn_threshold=_WRITES_PER_HOUR_WARN,
                critical_threshold=_WRITES_PER_HOUR_CRITICAL,
                unit="writes/hour",
                message=(
                    f"Write rate ({writes_per_hour:,}/hour) is approaching the operating boundary. "
                    "Monitor for WAL checkpoint lag."
                ),
                recommendations=[
                    "Consider batching LLM event writes rather than writing per-event.",
                ],
            )
        return BoundaryCheck(
            name="SQLite Write Pressure",
            passed=True,
            severity="ok",
            current_value=writes_per_hour,
            warn_threshold=_WRITES_PER_HOUR_WARN,
            critical_threshold=_WRITES_PER_HOUR_CRITICAL,
            unit="writes/hour",
            message=f"Write rate ({writes_per_hour:,}/hour) is within the comfortable operating range.",
        )

    def _check_cognition_volume(self, avg_recs: float | None) -> BoundaryCheck:
        if avg_recs is None:
            return BoundaryCheck(
                name="Cognition Pipeline Volume",
                passed=True,
                severity="ok",
                current_value=0,
                warn_threshold=_RECS_PER_SNAPSHOT_WARN,
                critical_threshold=_RECS_PER_SNAPSHOT_CRITICAL,
                unit="recs/snapshot",
                message="Cognition volume not available — no recommendation rate data provided.",
            )

        if avg_recs >= _RECS_PER_SNAPSHOT_CRITICAL:
            return BoundaryCheck(
                name="Cognition Pipeline Volume",
                passed=False,
                severity="critical",
                current_value=avg_recs,
                warn_threshold=_RECS_PER_SNAPSHOT_WARN,
                critical_threshold=_RECS_PER_SNAPSHOT_CRITICAL,
                unit="recs/snapshot",
                message=(
                    f"Average recommendations per snapshot ({avg_recs:.0f}) exceeds the critical boundary. "
                    "Consolidation, deduplication, and report generation will be slow."
                ),
                recommendations=[
                    "Review recommendation generators for over-triggering patterns.",
                    "Enable deduplication to reduce redundant signals before pipeline.",
                    "Consider raising confidence thresholds to suppress low-quality signals.",
                ],
            )
        elif avg_recs >= _RECS_PER_SNAPSHOT_WARN:
            return BoundaryCheck(
                name="Cognition Pipeline Volume",
                passed=False,
                severity="warning",
                current_value=avg_recs,
                warn_threshold=_RECS_PER_SNAPSHOT_WARN,
                critical_threshold=_RECS_PER_SNAPSHOT_CRITICAL,
                unit="recs/snapshot",
                message=(
                    f"Average recommendations per snapshot ({avg_recs:.0f}) is approaching the operating boundary."
                ),
                recommendations=[
                    "Enable evidence compression for large recommendation chains.",
                    "Monitor deduplication ratio — high duplication means signal sources are noisy.",
                ],
            )
        return BoundaryCheck(
            name="Cognition Pipeline Volume",
            passed=True,
            severity="ok",
            current_value=avg_recs,
            warn_threshold=_RECS_PER_SNAPSHOT_WARN,
            critical_threshold=_RECS_PER_SNAPSHOT_CRITICAL,
            unit="recs/snapshot",
            message=f"Recommendation volume ({avg_recs:.0f}/snapshot) is within the comfortable range.",
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _build_envelope(self) -> OperatingEnvelope:
        return OperatingEnvelope(
            snapshot_comfortable_max=_SNAPSHOT_WARN,
            event_comfortable_max=_EVENT_WARN,
            db_size_comfortable_max_mb=int(_DB_SIZE_WARN_BYTES / (1024 * 1024)),
            writes_per_hour_comfortable_max=_WRITES_PER_HOUR_WARN,
            recs_per_snapshot_comfortable_max=_RECS_PER_SNAPSHOT_WARN,
            notes=[
                "These are comfortable operating targets, not hard limits.",
                "Exceeding them may increase latency but will not cause failures.",
                "Performance depends heavily on VPS hardware (RAM, disk I/O).",
                "SSD storage significantly extends all boundaries vs. HDD.",
            ],
        )

    def _build_observations(
        self,
        checks: list[BoundaryCheck],
        snapshot_count: int,
        event_count: int,
    ) -> list[str]:
        obs = []
        critical = [c for c in checks if c.severity == "critical"]
        warned = [c for c in checks if not c.passed and c.severity == "warning"]

        if critical:
            obs.append(
                f"{len(critical)} scaling boundary/boundaries breached: "
                f"{', '.join(c.name for c in critical)}. "
                "Operational performance may already be degraded."
            )
        if warned:
            obs.append(
                f"{len(warned)} boundary/boundaries approaching limits: "
                f"{', '.join(c.name for c in warned)}. "
                "Monitor closely over the next 7 days."
            )
        if not critical and not warned:
            obs.append(
                f"All boundaries within comfortable range. "
                f"Snapshots: {snapshot_count:,}, Events: {event_count:,}."
            )

        return obs
