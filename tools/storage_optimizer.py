"""
Storage optimization advisor — purely advisory, no actions taken.

Generates retention tuning recommendations, archive suggestions, storage
pressure forecasts, and SQLite maintenance guidance from pre-computed metrics.

All outputs are advisory. Operators decide whether to act.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Advisory thresholds
_DELETION_RATE_LOW = 0.05           # < 5% deleted → policy appears too lenient
_DELETION_RATE_HIGH = 0.50          # > 50% deleted → policy may be too aggressive
_FRAG_WARN_FRACTION = 0.20          # freelist/page_count > 20% → VACUUM suggested
_FRAG_CRITICAL_FRACTION = 0.40      # > 40% → VACUUM strongly recommended
_ARCHIVE_PRESSURE_FRACTION = 0.85   # snapshot count > 85% of max → archive pressure
_COLD_STORAGE_DAYS = 90             # snapshots older than this are cold-storage candidates
_FORECAST_HORIZON_DAYS = 30         # default forecast horizon
_OVERSIZED_TOKEN_THRESHOLD = 10_000  # avg tokens/snapshot above this → flag oversized


@dataclass
class RetentionTuningRecommendation:
    """Advisory recommendation for adjusting a retention policy."""

    recommendation_id: str
    priority: str    # "high" | "medium" | "low" | "info"
    title: str
    observation: str
    suggested_action: str
    current_value: str
    suggested_value: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "priority": self.priority,
            "title": self.title,
            "observation": self.observation,
            "suggested_action": self.suggested_action,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "advisory": "Advisory only. Operator must approve any policy change.",
        }


@dataclass
class ArchiveSuggestion:
    """Advisory suggestion for archiving cold or oversized data."""

    suggestion_id: str
    priority: str    # "high" | "medium" | "low" | "info"
    title: str
    rationale: str
    candidate_description: str
    estimated_space_savings: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "priority": self.priority,
            "title": self.title,
            "rationale": self.rationale,
            "candidate_description": self.candidate_description,
            "estimated_space_savings": self.estimated_space_savings,
            "advisory": "Advisory only. Archiving requires explicit operator action.",
        }


@dataclass
class StoragePressureForecast:
    """Projected storage pressure over a forecast horizon."""

    forecast_horizon_days: int
    current_db_size_bytes: int
    projected_db_size_bytes: int
    growth_rate_bytes_per_day: float
    projected_disk_usage_fraction: float
    projected_snapshot_count: int
    expected_pressure_level: str    # "ok" | "warning" | "critical"
    observations: list[str]
    confidence: str    # "low" | "medium" | "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_horizon_days": self.forecast_horizon_days,
            "current_db_size_bytes": self.current_db_size_bytes,
            "current_db_size_human": _human_bytes(self.current_db_size_bytes),
            "projected_db_size_bytes": self.projected_db_size_bytes,
            "projected_db_size_human": _human_bytes(self.projected_db_size_bytes),
            "growth_rate_bytes_per_day": round(self.growth_rate_bytes_per_day, 0),
            "projected_disk_usage_fraction": round(self.projected_disk_usage_fraction, 3),
            "projected_disk_usage_percent": round(self.projected_disk_usage_fraction * 100, 1),
            "projected_snapshot_count": self.projected_snapshot_count,
            "expected_pressure_level": self.expected_pressure_level,
            "observations": self.observations,
            "confidence": self.confidence,
        }


@dataclass
class SQLiteMaintenanceGuidance:
    """Practical SQLite VACUUM/ANALYZE/checkpoint recommendations."""

    fragmentation_fraction: float
    fragmentation_severity: str    # "none" | "low" | "moderate" | "high"
    vacuum_recommended: bool
    analyze_recommended: bool
    wal_checkpoint_recommended: bool
    guidance_items: list[str]
    estimated_space_recovery_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "fragmentation_fraction": round(self.fragmentation_fraction, 3),
            "fragmentation_percent": round(self.fragmentation_fraction * 100, 1),
            "fragmentation_severity": self.fragmentation_severity,
            "vacuum_recommended": self.vacuum_recommended,
            "analyze_recommended": self.analyze_recommended,
            "wal_checkpoint_recommended": self.wal_checkpoint_recommended,
            "guidance_items": self.guidance_items,
            "estimated_space_recovery_bytes": self.estimated_space_recovery_bytes,
            "estimated_space_recovery_human": _human_bytes(self.estimated_space_recovery_bytes),
            "advisory": "Run VACUUM and ANALYZE during low-traffic periods only.",
        }


@dataclass
class StorageOptimizationReport:
    """Container for all storage optimization advisories."""

    retention_recommendations: list[RetentionTuningRecommendation]
    archive_suggestions: list[ArchiveSuggestion]
    pressure_forecast: StoragePressureForecast | None
    sqlite_guidance: SQLiteMaintenanceGuidance | None
    summary_observations: list[str]
    overall_urgency: str    # "none" | "low" | "moderate" | "high"
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_urgency": self.overall_urgency,
            "retention_recommendations": [r.to_dict() for r in self.retention_recommendations],
            "archive_suggestions": [a.to_dict() for a in self.archive_suggestions],
            "pressure_forecast": self.pressure_forecast.to_dict() if self.pressure_forecast else None,
            "sqlite_guidance": self.sqlite_guidance.to_dict() if self.sqlite_guidance else None,
            "summary_observations": self.summary_observations,
            "generated_at": self.generated_at,
            "advisory": "All suggestions are advisory. No automatic actions will be taken.",
        }

    def markdown(self) -> str:
        lines = [
            "# Storage Optimization Report",
            f"Generated: {self.generated_at}",
            f"**Overall urgency: {self.overall_urgency.upper()}**",
            "",
        ]

        if self.summary_observations:
            lines.append("## Summary")
            for obs in self.summary_observations:
                lines.append(f"- {obs}")
            lines.append("")

        if self.retention_recommendations:
            lines.append("## Retention Tuning Recommendations")
            for rec in self.retention_recommendations:
                lines += [
                    f"### [{rec.priority.upper()}] {rec.title}",
                    f"- Observation: {rec.observation}",
                    f"- Current: {rec.current_value}",
                ]
                if rec.suggested_value:
                    lines.append(f"- Suggested: {rec.suggested_value}")
                lines += [f"- Action: {rec.suggested_action}", ""]

        if self.archive_suggestions:
            lines.append("## Archive Suggestions")
            for sug in self.archive_suggestions:
                lines += [
                    f"### [{sug.priority.upper()}] {sug.title}",
                    f"- Rationale: {sug.rationale}",
                    f"- Candidates: {sug.candidate_description}",
                    f"- Estimated savings: {sug.estimated_space_savings}",
                    "",
                ]

        if self.pressure_forecast:
            f = self.pressure_forecast
            lines += [
                "## Storage Pressure Forecast",
                f"Horizon: {f.forecast_horizon_days} days | "
                f"Projected: **{f.expected_pressure_level.upper()}** | "
                f"Confidence: {f.confidence}",
            ]
            for obs in f.observations:
                lines.append(f"- {obs}")
            lines.append("")

        if self.sqlite_guidance:
            g = self.sqlite_guidance
            lines += [
                "## SQLite Maintenance",
                f"Fragmentation: {g.fragmentation_fraction:.0%} ({g.fragmentation_severity})",
            ]
            for item in g.guidance_items:
                lines.append(f"- {item}")
            lines.append("")

        lines += ["---", "*Advisory only. All actions require explicit operator approval.*"]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class StorageOptimizerEngine:
    """
    Generates advisory storage optimization recommendations.

    Accepts pre-computed metrics — no DB access, no filesystem writes.
    All outputs are advisory: observe, report, suggest. Never act.
    """

    def generate(
        self,
        *,
        snapshot_count: int,
        max_snapshot_count: int,
        db_size_bytes: int,
        disk_total_bytes: int,
        disk_used_bytes: int,
        # Optional growth metrics
        db_growth_bytes_last_window: int | None = None,
        window_days: int | None = None,
        snapshot_growth_last_window: int | None = None,
        # Optional retention metrics
        retention_days: int = 30,
        deletion_count_last_run: int | None = None,
        total_count_last_run: int | None = None,
        # Optional fragmentation metrics
        db_page_count: int | None = None,
        db_freelist_count: int | None = None,
        # Optional cold-storage / evidence metrics
        cold_snapshot_count: int | None = None,
        oldest_snapshot_days: int | None = None,
        oversized_snapshot_count: int | None = None,
        oversized_estimated_bytes: int | None = None,
        avg_evidence_tokens_per_snapshot: float | None = None,
    ) -> StorageOptimizationReport:
        """
        Generate advisory storage optimization report.

        Required: core storage metrics (snapshot_count, max_snapshot_count,
        db_size_bytes, disk_total_bytes, disk_used_bytes).
        All other parameters are optional — the engine adapts.
        """
        seq = _IDSequencer()
        retention_recs: list[RetentionTuningRecommendation] = []
        archive_sugs: list[ArchiveSuggestion] = []

        retention_recs.extend(_check_retention_policy_fit(
            seq,
            snapshot_count=snapshot_count,
            max_snapshot_count=max_snapshot_count,
            deletion_count=deletion_count_last_run,
            total_at_run=total_count_last_run,
            retention_days=retention_days,
        ))

        archive_sugs.extend(_check_cold_storage_pressure(
            seq,
            cold_snapshot_count=cold_snapshot_count,
            oldest_snapshot_days=oldest_snapshot_days,
        ))
        archive_sugs.extend(_check_oversized_evidence_pressure(
            seq,
            oversized_snapshot_count=oversized_snapshot_count,
            oversized_estimated_bytes=oversized_estimated_bytes,
            avg_evidence_tokens=avg_evidence_tokens_per_snapshot,
        ))

        forecast = _build_pressure_forecast(
            snapshot_count=snapshot_count,
            max_snapshot_count=max_snapshot_count,
            db_size_bytes=db_size_bytes,
            disk_total_bytes=disk_total_bytes,
            disk_used_bytes=disk_used_bytes,
            db_growth_bytes_last_window=db_growth_bytes_last_window,
            window_days=window_days,
            snapshot_growth_last_window=snapshot_growth_last_window,
        )

        sqlite_guidance = _build_sqlite_guidance(
            db_size_bytes=db_size_bytes,
            db_page_count=db_page_count,
            db_freelist_count=db_freelist_count,
        )

        urgency = _compute_urgency(retention_recs, archive_sugs, forecast, sqlite_guidance)
        summary_obs = _build_summary_observations(
            snapshot_count=snapshot_count,
            max_snapshot_count=max_snapshot_count,
            db_size_bytes=db_size_bytes,
            disk_used_bytes=disk_used_bytes,
            disk_total_bytes=disk_total_bytes,
            retention_recs=retention_recs,
            archive_sugs=archive_sugs,
            forecast=forecast,
        )

        logger.info(
            "Storage optimization report generated",
            extra={
                "overall_urgency": urgency,
                "retention_rec_count": len(retention_recs),
                "archive_suggestion_count": len(archive_sugs),
            },
        )
        return StorageOptimizationReport(
            retention_recommendations=retention_recs,
            archive_suggestions=archive_sugs,
            pressure_forecast=forecast,
            sqlite_guidance=sqlite_guidance,
            summary_observations=summary_obs,
            overall_urgency=urgency,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _IDSequencer:
    """Generates sequential advisory IDs within a report."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]:02d}"


def _check_retention_policy_fit(
    seq: _IDSequencer,
    *,
    snapshot_count: int,
    max_snapshot_count: int,
    deletion_count: int | None,
    total_at_run: int | None,
    retention_days: int,
) -> list[RetentionTuningRecommendation]:
    recs = []

    if max_snapshot_count > 0:
        fraction = snapshot_count / max_snapshot_count
        if fraction >= _ARCHIVE_PRESSURE_FRACTION:
            recs.append(RetentionTuningRecommendation(
                recommendation_id=seq.next("RET"),
                priority="high",
                title="Snapshot count approaching retention limit",
                observation=(
                    f"Snapshot count {snapshot_count:,} is {fraction:.0%} of "
                    f"max_snapshot_count={max_snapshot_count:,}."
                ),
                suggested_action=(
                    "Consider reducing retention_days or running retention now."
                ),
                current_value=(
                    f"max_snapshot_count={max_snapshot_count}, "
                    f"retention_days={retention_days}"
                ),
                suggested_value=f"Reduce retention_days below {retention_days}",
            ))

    if deletion_count is not None and total_at_run is not None and total_at_run > 0:
        deletion_rate = deletion_count / total_at_run
        if deletion_rate < _DELETION_RATE_LOW:
            recs.append(RetentionTuningRecommendation(
                recommendation_id=seq.next("RET"),
                priority="low",
                title="Retention policy appears too lenient",
                observation=(
                    f"Last retention run deleted only {deletion_count:,} of "
                    f"{total_at_run:,} snapshots ({deletion_rate:.1%}). "
                    "Very few snapshots are aging out."
                ),
                suggested_action=(
                    "Consider reducing retention_days to prune data more aggressively."
                ),
                current_value=f"retention_days={retention_days}",
                suggested_value=f"Consider retention_days < {retention_days}",
            ))
        elif deletion_rate > _DELETION_RATE_HIGH:
            recs.append(RetentionTuningRecommendation(
                recommendation_id=seq.next("RET"),
                priority="medium",
                title="Retention policy appears aggressive",
                observation=(
                    f"Last retention run deleted {deletion_count:,} of "
                    f"{total_at_run:,} snapshots ({deletion_rate:.1%}). "
                    "A large fraction of history is being pruned."
                ),
                suggested_action=(
                    "Verify retention_days is not shorter than needed "
                    "for operational analysis."
                ),
                current_value=f"retention_days={retention_days}",
                suggested_value=f"Consider retention_days > {retention_days}",
            ))

    return recs


def _check_cold_storage_pressure(
    seq: _IDSequencer,
    *,
    cold_snapshot_count: int | None,
    oldest_snapshot_days: int | None,
) -> list[ArchiveSuggestion]:
    sugs = []

    if cold_snapshot_count and cold_snapshot_count > 0:
        sugs.append(ArchiveSuggestion(
            suggestion_id=seq.next("ARC"),
            priority="medium",
            title="Cold-storage snapshots identified",
            rationale=(
                f"{cold_snapshot_count:,} snapshot(s) appear cold (no recent activity, "
                f"older than {_COLD_STORAGE_DAYS} days). These may be archivable."
            ),
            candidate_description=(
                f"~{cold_snapshot_count:,} snapshots older than "
                f"{_COLD_STORAGE_DAYS} days with no recent reference."
            ),
            estimated_space_savings="Variable — depends on per-snapshot size.",
        ))

    if oldest_snapshot_days and oldest_snapshot_days > _COLD_STORAGE_DAYS * 2:
        sugs.append(ArchiveSuggestion(
            suggestion_id=seq.next("ARC"),
            priority="low",
            title="Very old snapshots present",
            rationale=(
                f"Oldest snapshot is ~{oldest_snapshot_days} days old. "
                "Snapshots outside the operational analysis window may be archivable."
            ),
            candidate_description=f"Snapshots older than {oldest_snapshot_days} days.",
            estimated_space_savings="Variable.",
        ))

    return sugs


def _check_oversized_evidence_pressure(
    seq: _IDSequencer,
    *,
    oversized_snapshot_count: int | None,
    oversized_estimated_bytes: int | None,
    avg_evidence_tokens: float | None,
) -> list[ArchiveSuggestion]:
    sugs = []

    if oversized_snapshot_count and oversized_snapshot_count > 0:
        savings_str = (
            _human_bytes(oversized_estimated_bytes)
            if oversized_estimated_bytes else "variable"
        )
        sugs.append(ArchiveSuggestion(
            suggestion_id=seq.next("ARC"),
            priority="medium",
            title="Oversized evidence blobs detected",
            rationale=(
                f"{oversized_snapshot_count:,} snapshot(s) contain evidence blobs "
                "significantly larger than typical. These may be compressible or truncatable."
            ),
            candidate_description=(
                f"~{oversized_snapshot_count:,} snapshots with outsized evidence "
                f"(threshold: >{_OVERSIZED_TOKEN_THRESHOLD:,} avg tokens per snapshot)."
            ),
            estimated_space_savings=f"~{savings_str}",
        ))

    if avg_evidence_tokens and avg_evidence_tokens > _OVERSIZED_TOKEN_THRESHOLD:
        sugs.append(ArchiveSuggestion(
            suggestion_id=seq.next("ARC"),
            priority="low",
            title="High average evidence token density",
            rationale=(
                f"Average evidence token density is {avg_evidence_tokens:,.0f} "
                f"tokens/snapshot, above the advisory threshold of "
                f"{_OVERSIZED_TOKEN_THRESHOLD:,}. Evidence compression may reduce storage."
            ),
            candidate_description=(
                "All snapshots with evidence above average token density."
            ),
            estimated_space_savings="Variable — depends on compressibility.",
        ))

    return sugs


def _build_pressure_forecast(
    *,
    snapshot_count: int,
    max_snapshot_count: int,
    db_size_bytes: int,
    disk_total_bytes: int,
    disk_used_bytes: int,
    db_growth_bytes_last_window: int | None,
    window_days: int | None,
    snapshot_growth_last_window: int | None,
) -> StoragePressureForecast | None:
    if disk_total_bytes <= 0:
        return None

    confidence = "low"
    growth_rate_bpd = 0.0
    snap_rate_per_day = 0.0

    if db_growth_bytes_last_window is not None and window_days and window_days > 0:
        growth_rate_bpd = max(0.0, db_growth_bytes_last_window / window_days)
        confidence = "medium"
        if snapshot_growth_last_window is not None:
            snap_rate_per_day = max(0.0, snapshot_growth_last_window / window_days)
            confidence = "high"

    projected_db_bytes = int(db_size_bytes + growth_rate_bpd * _FORECAST_HORIZON_DAYS)
    projected_disk_used = disk_used_bytes + int(growth_rate_bpd * _FORECAST_HORIZON_DAYS)
    projected_disk_frac = projected_disk_used / disk_total_bytes
    projected_snap_count = snapshot_count + int(snap_rate_per_day * _FORECAST_HORIZON_DAYS)

    if projected_disk_frac >= 0.85:
        pressure = "critical"
    elif projected_disk_frac >= 0.70:
        pressure = "warning"
    else:
        pressure = "ok"

    if max_snapshot_count > 0 and projected_snap_count >= max_snapshot_count:
        if pressure == "ok":
            pressure = "warning"

    observations = []
    if growth_rate_bpd > 0:
        observations.append(
            f"Estimated growth rate: {_human_bytes(int(growth_rate_bpd))}/day "
            f"({_human_bytes(int(growth_rate_bpd * 30))}/month)."
        )
    observations.append(
        f"In {_FORECAST_HORIZON_DAYS} days: projected DB size "
        f"{_human_bytes(projected_db_bytes)}, "
        f"disk usage {projected_disk_frac:.0%}."
    )
    if projected_snap_count >= max_snapshot_count > 0:
        observations.append(
            f"Snapshot count may reach or exceed limit "
            f"({projected_snap_count:,}/{max_snapshot_count:,}) "
            f"within {_FORECAST_HORIZON_DAYS} days."
        )
    if confidence == "low":
        observations.append(
            "Low confidence: no growth window data provided. "
            "Forecast based on current state only."
        )

    return StoragePressureForecast(
        forecast_horizon_days=_FORECAST_HORIZON_DAYS,
        current_db_size_bytes=db_size_bytes,
        projected_db_size_bytes=projected_db_bytes,
        growth_rate_bytes_per_day=growth_rate_bpd,
        projected_disk_usage_fraction=projected_disk_frac,
        projected_snapshot_count=projected_snap_count,
        expected_pressure_level=pressure,
        observations=observations,
        confidence=confidence,
    )


def _build_sqlite_guidance(
    *,
    db_size_bytes: int,
    db_page_count: int | None,
    db_freelist_count: int | None,
) -> SQLiteMaintenanceGuidance | None:
    if not db_page_count or db_page_count <= 0:
        return None

    freelist = db_freelist_count or 0
    frag_fraction = freelist / db_page_count

    if frag_fraction >= _FRAG_CRITICAL_FRACTION:
        severity = "high"
    elif frag_fraction >= _FRAG_WARN_FRACTION:
        severity = "moderate"
    elif frag_fraction > 0.05:
        severity = "low"
    else:
        severity = "none"

    vacuum_recommended = frag_fraction >= _FRAG_WARN_FRACTION
    analyze_recommended = db_size_bytes > 50 * 1024 * 1024
    wal_checkpoint = db_size_bytes > 100 * 1024 * 1024

    bytes_per_page = db_size_bytes / max(db_page_count, 1)
    estimated_recovery = int(freelist * bytes_per_page)

    guidance_items = []
    if vacuum_recommended:
        guidance_items.append(
            f"VACUUM recommended: {frag_fraction:.0%} of pages are free "
            f"(~{_human_bytes(estimated_recovery)} recoverable). "
            "Run: PRAGMA wal_checkpoint(FULL); VACUUM;"
        )
    if analyze_recommended:
        guidance_items.append(
            "ANALYZE recommended: database is large enough that query planner "
            "statistics may drift. Run: ANALYZE;"
        )
    if wal_checkpoint:
        guidance_items.append(
            "WAL checkpoint suggested: database exceeds 100 MB. "
            "Run: PRAGMA wal_checkpoint(TRUNCATE);"
        )
    if not guidance_items:
        guidance_items.append(
            f"SQLite fragmentation is low ({frag_fraction:.0%}). "
            "No immediate maintenance required."
        )

    return SQLiteMaintenanceGuidance(
        fragmentation_fraction=frag_fraction,
        fragmentation_severity=severity,
        vacuum_recommended=vacuum_recommended,
        analyze_recommended=analyze_recommended,
        wal_checkpoint_recommended=wal_checkpoint,
        guidance_items=guidance_items,
        estimated_space_recovery_bytes=estimated_recovery,
    )


def _compute_urgency(
    retention_recs: list[RetentionTuningRecommendation],
    archive_sugs: list[ArchiveSuggestion],
    forecast: StoragePressureForecast | None,
    sqlite_guidance: SQLiteMaintenanceGuidance | None,
) -> str:
    priorities = (
        [r.priority for r in retention_recs]
        + [s.priority for s in archive_sugs]
    )
    if forecast:
        if forecast.expected_pressure_level == "critical":
            priorities.append("high")
        elif forecast.expected_pressure_level == "warning":
            priorities.append("medium")
    if sqlite_guidance and sqlite_guidance.fragmentation_severity in ("moderate", "high"):
        priorities.append("medium")

    if "high" in priorities:
        return "high"
    if "medium" in priorities:
        return "moderate"
    if "low" in priorities:
        return "low"
    return "none"


def _build_summary_observations(
    *,
    snapshot_count: int,
    max_snapshot_count: int,
    db_size_bytes: int,
    disk_used_bytes: int,
    disk_total_bytes: int,
    retention_recs: list[RetentionTuningRecommendation],
    archive_sugs: list[ArchiveSuggestion],
    forecast: StoragePressureForecast | None,
) -> list[str]:
    obs = []
    disk_pct = disk_used_bytes / max(disk_total_bytes, 1)
    snap_pct = snapshot_count / max(max_snapshot_count, 1)

    obs.append(
        f"Database size: {_human_bytes(db_size_bytes)}. "
        f"Disk usage: {disk_pct:.0%}. "
        f"Snapshots: {snapshot_count:,}/{max_snapshot_count:,} ({snap_pct:.0%})."
    )
    if retention_recs:
        obs.append(f"{len(retention_recs)} retention tuning recommendation(s) generated.")
    if archive_sugs:
        obs.append(f"{len(archive_sugs)} archive suggestion(s) identified.")
    if forecast and forecast.expected_pressure_level != "ok":
        obs.append(
            f"Pressure forecast: {forecast.expected_pressure_level.upper()} expected "
            f"within {forecast.forecast_horizon_days} days."
        )
    return obs


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n = int(n / 1024)
    return f"{n:.1f} TB"
