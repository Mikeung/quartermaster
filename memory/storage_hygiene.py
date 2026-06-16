"""
Storage hygiene engine — observe disk and database storage pressure.

Purely observational and advisory. Does NOT delete anything.
Provides storage estimates, pressure classifications, and growth observations.

Pressure levels (based on VPS operational thresholds):
- ok:       below 70% of available disk or below soft limits
- warning:  70-85% disk usage or approaching snapshot limits
- critical: above 85% disk usage or significantly exceeding limits
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pressure thresholds (fraction of disk used)
_PRESSURE_WARNING = 0.70
_PRESSURE_CRITICAL = 0.85

# Snapshot count soft thresholds relative to max_snapshot_count
_COUNT_WARNING_FRACTION = 0.80   # 80% of max → warning
_COUNT_CRITICAL_FRACTION = 0.95  # 95% of max → critical


@dataclass
class StorageEstimate:
    """Point-in-time storage snapshot."""

    db_size_bytes: int
    db_path: str
    disk_total_bytes: int
    disk_used_bytes: int
    disk_free_bytes: int
    disk_usage_fraction: float
    snapshot_count: int
    max_snapshot_count: int
    snapshot_count_fraction: float
    pressure_level: str  # "ok" | "warning" | "critical"
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_size_bytes": self.db_size_bytes,
            "db_size_human": _human_bytes(self.db_size_bytes),
            "db_path": self.db_path,
            "disk_total_bytes": self.disk_total_bytes,
            "disk_used_bytes": self.disk_used_bytes,
            "disk_free_bytes": self.disk_free_bytes,
            "disk_free_human": _human_bytes(self.disk_free_bytes),
            "disk_usage_fraction": round(self.disk_usage_fraction, 3),
            "disk_usage_percent": round(self.disk_usage_fraction * 100, 1),
            "snapshot_count": self.snapshot_count,
            "max_snapshot_count": self.max_snapshot_count,
            "snapshot_count_fraction": round(self.snapshot_count_fraction, 3),
            "pressure_level": self.pressure_level,
            "observations": self.observations,
            "generated_at": self.generated_at,
        }


@dataclass
class StorageGrowthObservation:
    """Observed growth trend from comparing two StorageEstimates."""

    db_growth_bytes: int
    snapshot_growth: int
    window_description: str
    observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_growth_bytes": self.db_growth_bytes,
            "db_growth_human": _human_bytes(abs(self.db_growth_bytes)),
            "snapshot_growth": self.snapshot_growth,
            "window_description": self.window_description,
            "observations": self.observations,
        }


class StorageHygieneEngine:
    """
    Observes storage pressure from disk usage and snapshot counts.

    Reads from the filesystem and the store — never writes, never deletes.
    Operators use these observations to decide whether to run retention.
    """

    def estimate(
        self,
        db_path: str,
        snapshot_count: int,
        max_snapshot_count: int = 200,
    ) -> StorageEstimate:
        """Produce a storage estimate for the current state."""
        db_path_obj = Path(db_path)
        db_size = db_path_obj.stat().st_size if db_path_obj.exists() else 0

        disk = shutil.disk_usage(str(db_path_obj.parent) if db_path_obj.exists() else "/")
        disk_usage_fraction = disk.used / disk.total if disk.total > 0 else 0.0

        count_fraction = snapshot_count / max_snapshot_count if max_snapshot_count > 0 else 0.0

        pressure, observations = self._assess_pressure(
            disk_usage_fraction=disk_usage_fraction,
            count_fraction=count_fraction,
            snapshot_count=snapshot_count,
            max_snapshot_count=max_snapshot_count,
            db_size=db_size,
        )

        logger.info(
            "Storage estimate computed",
            extra={
                "pressure": pressure,
                "disk_pct": round(disk_usage_fraction * 100, 1),
                "snapshot_count": snapshot_count,
            },
        )
        return StorageEstimate(
            db_size_bytes=db_size,
            db_path=str(db_path),
            disk_total_bytes=disk.total,
            disk_used_bytes=disk.used,
            disk_free_bytes=disk.free,
            disk_usage_fraction=disk_usage_fraction,
            snapshot_count=snapshot_count,
            max_snapshot_count=max_snapshot_count,
            snapshot_count_fraction=count_fraction,
            pressure_level=pressure,
            observations=observations,
        )

    def compare(
        self,
        earlier: StorageEstimate,
        later: StorageEstimate,
    ) -> StorageGrowthObservation:
        """Compare two estimates to produce a growth observation."""
        db_growth = later.db_size_bytes - earlier.db_size_bytes
        snap_growth = later.snapshot_count - earlier.snapshot_count

        observations: list[str] = []
        if db_growth > 0:
            observations.append(
                f"Database grew by {_human_bytes(db_growth)} since earlier estimate."
            )
        elif db_growth < 0:
            observations.append(
                f"Database shrank by {_human_bytes(abs(db_growth))} — retention may have run."
            )

        if snap_growth > 0:
            observations.append(f"Snapshot count increased by {snap_growth}.")
        elif snap_growth < 0:
            observations.append(f"Snapshot count decreased by {abs(snap_growth)} — deletions occurred.")

        if not observations:
            observations.append("No significant storage change observed.")

        return StorageGrowthObservation(
            db_growth_bytes=db_growth,
            snapshot_growth=snap_growth,
            window_description=f"{earlier.generated_at} → {later.generated_at}",
            observations=observations,
        )

    def _assess_pressure(
        self,
        disk_usage_fraction: float,
        count_fraction: float,
        snapshot_count: int,
        max_snapshot_count: int,
        db_size: int,
    ) -> tuple[str, list[str]]:
        observations: list[str] = []
        pressure = "ok"

        # Disk pressure
        if disk_usage_fraction >= _PRESSURE_CRITICAL:
            pressure = "critical"
            observations.append(
                f"Disk usage at {disk_usage_fraction:.0%} — critically high. "
                "Consider running retention immediately."
            )
        elif disk_usage_fraction >= _PRESSURE_WARNING:
            pressure = "warning"
            observations.append(
                f"Disk usage at {disk_usage_fraction:.0%} — approaching capacity. "
                "Consider scheduling retention."
            )

        # Snapshot count pressure
        if count_fraction >= _COUNT_CRITICAL_FRACTION:
            if pressure != "critical":
                pressure = "critical"
            observations.append(
                f"Snapshot count {snapshot_count}/{max_snapshot_count} "
                f"({count_fraction:.0%}) — at capacity. Retention recommended."
            )
        elif count_fraction >= _COUNT_WARNING_FRACTION:
            if pressure == "ok":
                pressure = "warning"
            observations.append(
                f"Snapshot count {snapshot_count}/{max_snapshot_count} "
                f"({count_fraction:.0%}) — approaching limit."
            )

        # DB size observation
        if db_size > 500 * 1024 * 1024:  # 500 MB
            observations.append(
                f"Database size {_human_bytes(db_size)} — large for a single-node deployment."
            )
        elif db_size > 100 * 1024 * 1024:  # 100 MB
            observations.append(f"Database size {_human_bytes(db_size)}.")

        if pressure == "ok" and not observations:
            observations.append(
                f"Storage pressure normal. "
                f"Disk: {disk_usage_fraction:.0%} used. "
                f"Snapshots: {snapshot_count}/{max_snapshot_count}."
            )

        return pressure, observations


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n = int(n / 1024)
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# Per-project storage awareness (Phase 10 extension)
# ---------------------------------------------------------------------------

@dataclass
class ProjectStorageProfile:
    """Storage footprint for a single project."""

    project_id: str
    snapshot_count: int
    llm_event_count: int
    total_tokens: int
    estimated_cost: float
    latest_snapshot_at: str | None
    latest_event_at: str | None
    snapshot_share: float   # fraction of total snapshots in DB
    event_share: float      # fraction of total LLM events in DB
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "snapshot_count": self.snapshot_count,
            "llm_event_count": self.llm_event_count,
            "total_tokens": self.total_tokens,
            "estimated_cost": round(self.estimated_cost, 6),
            "latest_snapshot_at": self.latest_snapshot_at,
            "latest_event_at": self.latest_event_at,
            "snapshot_share": round(self.snapshot_share, 4),
            "event_share": round(self.event_share, 4),
            "observations": self.observations,
        }


@dataclass
class ProjectStorageSummary:
    """Cross-project storage distribution."""

    total_snapshots: int
    total_llm_events: int
    project_profiles: list[ProjectStorageProfile]
    runaway_projects: list[str]
    concentration_observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_snapshots": self.total_snapshots,
            "total_llm_events": self.total_llm_events,
            "project_count": len(self.project_profiles),
            "project_profiles": [p.to_dict() for p in self.project_profiles],
            "runaway_projects": self.runaway_projects,
            "concentration_observations": self.concentration_observations,
            "generated_at": self.generated_at,
        }


class ProjectStorageHygiene:
    """
    Observes per-project storage usage and flags imbalances.

    Purely observational — never deletes.
    Accepts pre-fetched stats from store queries to avoid cross-module coupling.
    """

    _RUNAWAY_SNAPSHOT_SHARE = 0.70   # single project owning 70%+ of snapshots
    _RUNAWAY_EVENT_SHARE = 0.70      # single project owning 70%+ of events

    def build_project_summary(
        self,
        snapshot_stats: list[dict[str, Any]],
        event_stats: list[dict[str, Any]],
    ) -> ProjectStorageSummary:
        """
        Build per-project storage profiles.

        snapshot_stats: rows from OperationalStore.get_project_snapshot_stats()
        event_stats: rows from LLMEventStore.count_events_by_project()
        """
        total_snapshots = sum(r.get("snapshot_count", 0) or 0 for r in snapshot_stats)
        total_events = sum(r.get("event_count", 0) or 0 for r in event_stats)

        # Index event stats by project
        event_by_project: dict[str, dict[str, Any]] = {
            r["project_id"]: r for r in event_stats if r.get("project_id")
        }

        profiles: list[ProjectStorageProfile] = []

        for snap_row in snapshot_stats:
            pid = str(snap_row.get("project_id") or "")
            if not pid:
                continue

            snap_count = int(snap_row.get("snapshot_count", 0) or 0)
            ev_row = event_by_project.get(pid, {})
            ev_count = int(ev_row.get("event_count", 0) or 0)
            tokens = int(ev_row.get("total_tokens", 0) or 0)
            cost = float(ev_row.get("total_estimated_cost", 0) or 0)

            snap_share = snap_count / max(total_snapshots, 1)
            ev_share = ev_count / max(total_events, 1)

            observations = _project_storage_observations(pid, snap_share, ev_share)

            profiles.append(ProjectStorageProfile(
                project_id=pid,
                snapshot_count=snap_count,
                llm_event_count=ev_count,
                total_tokens=tokens,
                estimated_cost=cost,
                latest_snapshot_at=snap_row.get("latest_at"),
                latest_event_at=ev_row.get("latest_at"),
                snapshot_share=snap_share,
                event_share=ev_share,
                observations=observations,
            ))

        # Also include projects with events but no snapshots
        for pid, ev_row in event_by_project.items():
            if not any(p.project_id == pid for p in profiles):
                ev_count = int(ev_row.get("event_count", 0) or 0)
                tokens = int(ev_row.get("total_tokens", 0) or 0)
                cost = float(ev_row.get("total_estimated_cost", 0) or 0)
                ev_share = ev_count / max(total_events, 1)
                profiles.append(ProjectStorageProfile(
                    project_id=pid,
                    snapshot_count=0,
                    llm_event_count=ev_count,
                    total_tokens=tokens,
                    estimated_cost=cost,
                    latest_snapshot_at=None,
                    latest_event_at=ev_row.get("latest_at"),
                    snapshot_share=0.0,
                    event_share=ev_share,
                    observations=_project_storage_observations(pid, 0.0, ev_share),
                ))

        runaway = [
            p.project_id for p in profiles
            if p.snapshot_share >= self._RUNAWAY_SNAPSHOT_SHARE
            or p.event_share >= self._RUNAWAY_EVENT_SHARE
        ]

        concentration_obs = _concentration_observations(profiles, total_snapshots, total_events)

        logger.info(
            "Project storage summary built",
            extra={
                "project_count": len(profiles),
                "runaway_count": len(runaway),
                "total_snapshots": total_snapshots,
                "total_events": total_events,
            },
        )
        return ProjectStorageSummary(
            total_snapshots=total_snapshots,
            total_llm_events=total_events,
            project_profiles=sorted(profiles, key=lambda p: p.snapshot_count + p.llm_event_count, reverse=True),
            runaway_projects=runaway,
            concentration_observations=concentration_obs,
        )


def _project_storage_observations(
    project_id: str, snap_share: float, ev_share: float
) -> list[str]:
    obs = []
    if snap_share >= 0.70:
        obs.append(
            f"Project '{project_id}' holds {snap_share:.0%} of all snapshots — "
            "disproportionate concentration may indicate missing retention."
        )
    if ev_share >= 0.70:
        obs.append(
            f"Project '{project_id}' holds {ev_share:.0%} of all LLM events — "
            "consider per-project retention to balance storage."
        )
    return obs


# ---------------------------------------------------------------------------
# Phase 13B: Extended hygiene analysis
# ---------------------------------------------------------------------------

_OVERSIZED_TOKEN_DEFAULT = 10_000   # tokens per snapshot above which evidence is flagged
_COLD_STORAGE_DAYS_DEFAULT = 90     # snapshots older than this are cold candidates
_ARCHIVE_WARN_FRACTION = 0.80       # 80% of max_count → warning
_ARCHIVE_CRITICAL_FRACTION = 0.95   # 95% of max_count → critical


@dataclass
class OversizedEvidenceReport:
    """Report on snapshots with disproportionately large evidence blobs."""

    oversized_count: int
    total_assessed: int
    token_threshold: int
    oversized_snapshot_ids: list[int]
    estimated_excess_tokens: int
    observations: list[str]

    @property
    def has_oversized(self) -> bool:
        return self.oversized_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "oversized_count": self.oversized_count,
            "total_assessed": self.total_assessed,
            "token_threshold": self.token_threshold,
            "oversized_snapshot_ids": self.oversized_snapshot_ids,
            "estimated_excess_tokens": self.estimated_excess_tokens,
            "has_oversized": self.has_oversized,
            "observations": self.observations,
            "advisory": "Evidence trimming requires operator review of affected snapshots.",
        }


@dataclass
class ColdStorageCandidate:
    """A snapshot identified as a cold-storage candidate."""

    snapshot_id: int
    project_id: str
    created_at: str
    age_days: float
    reason: str


@dataclass
class ColdStorageReport:
    """Report on snapshots suitable for cold-storage or archiving."""

    candidate_count: int
    total_assessed: int
    cold_after_days: int
    candidates: list[ColdStorageCandidate]
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def has_candidates(self) -> bool:
        return self.candidate_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "total_assessed": self.total_assessed,
            "cold_after_days": self.cold_after_days,
            "candidates": [
                {
                    "snapshot_id": c.snapshot_id,
                    "project_id": c.project_id,
                    "created_at": c.created_at,
                    "age_days": round(c.age_days, 1),
                    "reason": c.reason,
                }
                for c in self.candidates
            ],
            "has_candidates": self.has_candidates,
            "observations": self.observations,
            "generated_at": self.generated_at,
            "advisory": "Cold-storage archiving requires explicit operator action.",
        }


@dataclass
class SnapshotDensityReport:
    """Temporal distribution analysis of snapshot creation."""

    total_snapshots: int
    window_days: int
    avg_per_day: float
    peak_day: str | None
    peak_day_count: int
    sparse_periods: list[str]
    burst_periods: list[str]
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_snapshots": self.total_snapshots,
            "window_days": self.window_days,
            "avg_per_day": round(self.avg_per_day, 2),
            "peak_day": self.peak_day,
            "peak_day_count": self.peak_day_count,
            "sparse_periods": self.sparse_periods,
            "burst_periods": self.burst_periods,
            "observations": self.observations,
            "generated_at": self.generated_at,
        }


@dataclass
class ArchivePressureIndicator:
    """Forecast of when snapshot archive pressure will reach advisory thresholds."""

    current_count: int
    max_count: int
    snapshots_per_day: float
    days_to_warning: float | None    # None if already at or beyond warning
    days_to_critical: float | None   # None if already at or beyond critical
    current_fraction: float
    pressure_level: str    # "ok" | "warning" | "critical"
    observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_count": self.current_count,
            "max_count": self.max_count,
            "current_fraction": round(self.current_fraction, 3),
            "current_percent": round(self.current_fraction * 100, 1),
            "snapshots_per_day": round(self.snapshots_per_day, 2),
            "days_to_warning": (
                round(self.days_to_warning, 1) if self.days_to_warning is not None else None
            ),
            "days_to_critical": (
                round(self.days_to_critical, 1) if self.days_to_critical is not None else None
            ),
            "pressure_level": self.pressure_level,
            "observations": self.observations,
        }


# Methods are added directly to StorageHygieneEngine below as a mixin-style patch
# via subclassing is not needed — they are appended to the class body in the module.

def _find_oversized_snapshots(
    evidence_stats: list[dict[str, Any]],
    token_threshold: int = _OVERSIZED_TOKEN_DEFAULT,
) -> OversizedEvidenceReport:
    """
    Identify snapshots with disproportionately large evidence blobs.

    evidence_stats: list of dicts with {snapshot_id, total_tokens}
    """
    oversized_ids: list[int] = []
    excess_tokens = 0

    for row in evidence_stats:
        tokens = int(row.get("total_tokens", 0) or 0)
        if tokens > token_threshold:
            oversized_ids.append(int(row.get("snapshot_id", 0)))
            excess_tokens += tokens - token_threshold

    total = len(evidence_stats)
    count = len(oversized_ids)
    observations = []

    if count == 0:
        observations.append(
            f"No oversized evidence blobs detected "
            f"(threshold: {token_threshold:,} tokens/snapshot)."
        )
    else:
        observations.append(
            f"{count}/{total} snapshot(s) exceed the "
            f"{token_threshold:,}-token evidence threshold."
        )
        observations.append(
            f"Estimated excess tokens: {excess_tokens:,}. "
            "Evidence compression may reduce storage."
        )

    return OversizedEvidenceReport(
        oversized_count=count,
        total_assessed=total,
        token_threshold=token_threshold,
        oversized_snapshot_ids=oversized_ids,
        estimated_excess_tokens=excess_tokens,
        observations=observations,
    )


def _find_cold_storage_candidates(
    snapshots: list[dict[str, Any]],
    cold_after_days: int = _COLD_STORAGE_DAYS_DEFAULT,
) -> ColdStorageReport:
    """
    Identify snapshots old enough to be considered cold-storage candidates.

    snapshots: list of dicts with {id, project_id, created_at}
    """
    now = datetime.now(UTC)
    candidates: list[ColdStorageCandidate] = []

    for snap in snapshots:
        snap_id = snap.get("id")
        if snap_id is None:
            continue
        ts_str = snap.get("created_at", "")
        try:
            ts = datetime.fromisoformat(str(ts_str).replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            age_days = (now - ts).total_seconds() / 86400
            if age_days >= cold_after_days:
                candidates.append(ColdStorageCandidate(
                    snapshot_id=int(snap_id),
                    project_id=str(snap.get("project_id", "")),
                    created_at=ts_str,
                    age_days=age_days,
                    reason=(
                        f"age_days={age_days:.0f} >= "
                        f"cold_after_days={cold_after_days}"
                    ),
                ))
        except (ValueError, AttributeError, TypeError):
            pass

    total = len(snapshots)
    count = len(candidates)
    observations = []

    if count == 0:
        observations.append(
            f"No cold-storage candidates found "
            f"(threshold: {cold_after_days} days)."
        )
    else:
        observations.append(
            f"{count}/{total} snapshot(s) are older than {cold_after_days} days "
            "and may be suitable for archiving or cold storage."
        )
        oldest = max(candidates, key=lambda c: c.age_days)
        observations.append(
            f"Oldest candidate is ~{oldest.age_days:.0f} days old "
            f"(project: {oldest.project_id})."
        )

    return ColdStorageReport(
        candidate_count=count,
        total_assessed=total,
        cold_after_days=cold_after_days,
        candidates=candidates,
        observations=observations,
    )


def _analyze_snapshot_density(
    snapshots: list[dict[str, Any]],
    window_days: int = 30,
) -> SnapshotDensityReport:
    """
    Analyze temporal distribution of snapshot creation within a window.

    snapshots: list of dicts with {created_at}
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=window_days)
    day_counts: dict[str, int] = {}

    for snap in snapshots:
        ts_str = snap.get("created_at", "")
        try:
            ts = datetime.fromisoformat(str(ts_str).replace(" ", "T"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts >= cutoff:
                day_key = ts.date().isoformat()
                day_counts[day_key] = day_counts.get(day_key, 0) + 1
        except (ValueError, AttributeError, TypeError):
            pass

    total = sum(day_counts.values())
    avg_per_day = total / max(window_days, 1)

    peak_day = max(day_counts, key=lambda d: day_counts[d]) if day_counts else None
    peak_count = day_counts[peak_day] if peak_day else 0

    burst_threshold = max(avg_per_day * 3, 1)
    burst_periods = [
        f"{day} ({cnt} snapshots)"
        for day, cnt in sorted(day_counts.items())
        if cnt >= burst_threshold and avg_per_day > 0
    ]

    # Sparse: gaps of ≥3 consecutive days with zero snapshots within the window
    sparse_periods: list[str] = []
    if day_counts and window_days >= 7:
        current_date = cutoff.date()
        end_date = now.date()
        gap_start: date | None = None
        while current_date <= end_date:
            if day_counts.get(current_date.isoformat(), 0) == 0:
                if gap_start is None:
                    gap_start = current_date
            else:
                if gap_start and (current_date - gap_start).days >= 3:
                    sparse_periods.append(
                        f"{gap_start.isoformat()} to "
                        f"{(current_date - timedelta(days=1)).isoformat()}"
                    )
                gap_start = None
            current_date += timedelta(days=1)

    observations = []
    if total == 0:
        observations.append(
            f"No snapshots found within the last {window_days} days."
        )
    else:
        observations.append(
            f"{total} snapshot(s) in the last {window_days} days "
            f"(avg {avg_per_day:.1f}/day)."
        )
    if peak_day:
        observations.append(f"Peak day: {peak_day} with {peak_count} snapshots.")
    if burst_periods:
        observations.append(
            f"Burst activity detected on {len(burst_periods)} day(s)."
        )
    if sparse_periods:
        observations.append(
            f"Sparse coverage: {len(sparse_periods)} gap period(s) of "
            "3+ days with no snapshots."
        )

    return SnapshotDensityReport(
        total_snapshots=total,
        window_days=window_days,
        avg_per_day=avg_per_day,
        peak_day=peak_day,
        peak_day_count=peak_count,
        sparse_periods=sparse_periods,
        burst_periods=burst_periods,
        observations=observations,
    )


def _assess_archive_pressure(
    snapshot_count: int,
    max_count: int,
    snapshots_per_day: float = 0.0,
) -> ArchivePressureIndicator:
    """
    Forecast when snapshot archive pressure will reach advisory thresholds.

    snapshot_count: current total
    max_count: RetentionPolicy.max_snapshot_count
    snapshots_per_day: recent growth rate (0 = no forecast possible)
    """
    fraction = snapshot_count / max(max_count, 1)

    if fraction >= _ARCHIVE_CRITICAL_FRACTION:
        pressure = "critical"
    elif fraction >= _ARCHIVE_WARN_FRACTION:
        pressure = "warning"
    else:
        pressure = "ok"

    days_to_warning: float | None = None
    days_to_critical: float | None = None

    if snapshots_per_day > 0 and max_count > 0:
        warn_threshold = int(max_count * _ARCHIVE_WARN_FRACTION)
        critical_threshold = int(max_count * _ARCHIVE_CRITICAL_FRACTION)
        if snapshot_count < warn_threshold:
            days_to_warning = (warn_threshold - snapshot_count) / snapshots_per_day
        if snapshot_count < critical_threshold:
            days_to_critical = (critical_threshold - snapshot_count) / snapshots_per_day

    observations = [
        f"Snapshot count: {snapshot_count:,}/{max_count:,} ({fraction:.0%}). "
        f"Pressure: {pressure}."
    ]
    if days_to_warning is not None and pressure == "ok":
        observations.append(
            f"At current rate (~{snapshots_per_day:.1f}/day), "
            f"warning threshold in ~{days_to_warning:.0f} days."
        )
    if days_to_critical is not None and pressure in ("ok", "warning"):
        observations.append(
            f"Critical threshold projected in ~{days_to_critical:.0f} days."
        )
    if pressure == "critical":
        observations.append(
            "Archive pressure is CRITICAL. "
            "Retention policy or archiving should be reviewed immediately."
        )
    elif pressure == "warning":
        observations.append(
            "Archive pressure is at WARNING level. "
            "Consider scheduling retention soon."
        )

    return ArchivePressureIndicator(
        current_count=snapshot_count,
        max_count=max_count,
        snapshots_per_day=snapshots_per_day,
        days_to_warning=days_to_warning,
        days_to_critical=days_to_critical,
        current_fraction=fraction,
        pressure_level=pressure,
        observations=observations,
    )


# Public aliases for the new analysis functions
find_oversized_snapshots = _find_oversized_snapshots
find_cold_storage_candidates = _find_cold_storage_candidates
analyze_snapshot_density = _analyze_snapshot_density
assess_archive_pressure = _assess_archive_pressure


def _concentration_observations(
    profiles: list[ProjectStorageProfile],
    total_snapshots: int,
    total_events: int,
) -> list[str]:
    obs = []
    if not profiles:
        return ["No project-scoped data available yet."]

    top_snap = max(profiles, key=lambda p: p.snapshot_share)
    if top_snap.snapshot_share >= 0.70:
        obs.append(
            f"Snapshot concentration: '{top_snap.project_id}' holds {top_snap.snapshot_share:.0%} "
            f"of {total_snapshots:,} total snapshots."
        )

    top_ev = max(profiles, key=lambda p: p.event_share)
    if top_ev.event_share >= 0.70:
        obs.append(
            f"LLM event concentration: '{top_ev.project_id}' holds {top_ev.event_share:.0%} "
            f"of {total_events:,} total events."
        )

    if not obs:
        obs.append(
            f"Storage appears balanced across {len(profiles)} project(s). "
            "No runaway projects detected."
        )

    return obs
