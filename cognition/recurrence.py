"""
Recurring issue detection — chronic operational concern tracking.

Analyzes snapshot history to identify patterns that repeat:
- repeated recommendation categories
- recurring cost warnings
- unstable workflow patterns
- repeated drift of the same components
- recurring runtime failures

Repeated problems matter more than isolated ones.
Recurrence elevates severity and operator attention priority.

Deterministic. Evidence-backed. No speculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_MIN_OCCURRENCES = 2
_TITLE_KEY_LEN = 60
_OBS_KEY_LEN = 70


@dataclass
class RecurringIssue:
    """An operational concern that appeared in multiple snapshots."""
    kind: str            # "recommendation", "cost_warning", "drift", "runtime_failure"
    pattern: str         # normalized description of what recurs
    occurrences: int
    snapshot_ids: list[int]
    first_seen: str
    last_seen: str
    evidence: list[str]
    severity_hint: str   # "low", "moderate", "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "pattern": self.pattern,
            "occurrences": self.occurrences,
            "snapshot_ids": self.snapshot_ids,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "evidence": self.evidence,
            "severity_hint": self.severity_hint,
        }


class RecurrenceEngine:
    """Detects chronic operational concerns from snapshot history.

    Compares patterns across snapshots rather than just N vs N-1.
    Uses string-prefix matching for recommendations and cost observations
    to group semantically similar issues across scans.
    """

    def detect(self, snapshots: list[dict[str, Any]]) -> list[RecurringIssue]:
        """Detect recurring patterns across all provided snapshots.

        snapshots: list of snapshot dicts, any order (oldest or newest first).
        Each snapshot has: id, created_at, data.
        """
        if len(snapshots) < _MIN_OCCURRENCES:
            logger.info(
                "Recurrence detection skipped — insufficient snapshots",
                extra={"snapshot_count": len(snapshots)},
            )
            return []

        issues: list[RecurringIssue] = []
        issues.extend(self._detect_recommendation_recurrence(snapshots))
        issues.extend(self._detect_cost_warning_recurrence(snapshots))
        issues.extend(self._detect_drift_recurrence(snapshots))
        issues.extend(self._detect_runtime_failure_recurrence(snapshots))

        issues.sort(key=lambda x: -x.occurrences)

        logger.info(
            "Recurrence detection complete",
            extra={
                "snapshot_count": len(snapshots),
                "recurring_issues": len(issues),
            },
        )
        return issues

    def _detect_recommendation_recurrence(
        self, snapshots: list[dict[str, Any]]
    ) -> list[RecurringIssue]:
        pattern_map: dict[str, list[tuple[int, str]]] = {}

        for snap in snapshots:
            snap_id = snap.get("id", 0)
            created_at = snap.get("created_at", "")
            recs = snap.get("data", {}).get("recommendations", [])
            for rec in recs:
                key = _rec_key(rec)
                if key:
                    pattern_map.setdefault(key, []).append((snap_id, created_at))

        return [
            RecurringIssue(
                kind="recommendation",
                pattern=key,
                occurrences=len(appearances),
                snapshot_ids=[a[0] for a in appearances],
                first_seen=min(a[1] for a in appearances),
                last_seen=max(a[1] for a in appearances),
                evidence=[
                    f"Recommendation '{key}' appeared in {len(appearances)} of {len(snapshots)} scans",
                    f"Snapshot IDs: {[a[0] for a in appearances]}",
                ],
                severity_hint=_recurrence_severity(len(appearances), len(snapshots)),
            )
            for key, appearances in pattern_map.items()
            if len(appearances) >= _MIN_OCCURRENCES
        ]

    def _detect_cost_warning_recurrence(
        self, snapshots: list[dict[str, Any]]
    ) -> list[RecurringIssue]:
        pattern_map: dict[str, list[tuple[int, str]]] = {}

        for snap in snapshots:
            snap_id = snap.get("id", 0)
            created_at = snap.get("created_at", "")
            obs_list = snap.get("data", {}).get("cost_observations", [])
            for obs in obs_list:
                if obs.get("severity") in ("high", "warning"):
                    key = obs.get("observation", "")[:_OBS_KEY_LEN].strip()
                    if key:
                        pattern_map.setdefault(key, []).append((snap_id, created_at))

        return [
            RecurringIssue(
                kind="cost_warning",
                pattern=key,
                occurrences=len(appearances),
                snapshot_ids=[a[0] for a in appearances],
                first_seen=min(a[1] for a in appearances),
                last_seen=max(a[1] for a in appearances),
                evidence=[
                    f"Cost warning '{key[:60]}...' recurred in {len(appearances)} scans",
                    "Recurring cost risk — pattern is structurally embedded, not a transient anomaly",
                ],
                severity_hint=_recurrence_severity(len(appearances), len(snapshots)),
            )
            for key, appearances in pattern_map.items()
            if len(appearances) >= _MIN_OCCURRENCES
        ]

    def _detect_drift_recurrence(
        self, snapshots: list[dict[str, Any]]
    ) -> list[RecurringIssue]:
        """Detect components that drift repeatedly (added/removed multiple times)."""
        from cognition.temporal_analysis import _compare_snapshots

        sorted_snaps = sorted(snapshots, key=lambda s: s.get("created_at", ""))
        component_changes: dict[str, list[tuple[int, str, str]]] = {}

        for i in range(1, len(sorted_snaps)):
            events = _compare_snapshots(sorted_snaps[i - 1], sorted_snaps[i])
            snap_id = sorted_snaps[i].get("id", 0)
            detected_at = sorted_snaps[i].get("created_at", "")
            for ev in events:
                key = ev.value
                component_changes.setdefault(key, []).append((snap_id, detected_at, ev.change_type))

        issues = []
        for component, occurrences in component_changes.items():
            if len(occurrences) >= _MIN_OCCURRENCES:
                snap_ids = [o[0] for o in occurrences]
                issues.append(RecurringIssue(
                    kind="drift",
                    pattern=f"Component '{component}' changed repeatedly",
                    occurrences=len(occurrences),
                    snapshot_ids=snap_ids,
                    first_seen=min(o[1] for o in occurrences),
                    last_seen=max(o[1] for o in occurrences),
                    evidence=[
                        f"'{component}' changed {len(occurrences)} times: "
                        f"{', '.join(o[2] for o in occurrences)}",
                        "Repeated changes indicate instability or active migration",
                    ],
                    severity_hint=_recurrence_severity(len(occurrences), len(sorted_snaps)),
                ))
        return issues

    def _detect_runtime_failure_recurrence(
        self, snapshots: list[dict[str, Any]]
    ) -> list[RecurringIssue]:
        """Detect recurring failed services from runtime scanner data."""
        service_failures: dict[str, list[tuple[int, str]]] = {}

        for snap in snapshots:
            snap_id = snap.get("id", 0)
            created_at = snap.get("created_at", "")
            runtime = snap.get("data", {}).get("scanner_results", {}).get("results", {}).get(
                "runtime_scanner", {}
            )
            for svc in runtime.get("failed_services", []):
                service_failures.setdefault(svc, []).append((snap_id, created_at))

            # Also check runtime_health if stored
            runtime_health = snap.get("data", {}).get("runtime_health", {})
            for svc in runtime_health.get("failed_services", []):
                existing = service_failures.setdefault(svc, [])
                if not any(e[0] == snap_id for e in existing):
                    existing.append((snap_id, created_at))

        return [
            RecurringIssue(
                kind="runtime_failure",
                pattern=f"Service '{svc}' repeatedly failing",
                occurrences=len(appearances),
                snapshot_ids=[a[0] for a in appearances],
                first_seen=min(a[1] for a in appearances),
                last_seen=max(a[1] for a in appearances),
                evidence=[
                    f"Service '{svc}' in failed state across {len(appearances)} scans",
                    "Persistent service failure requires investigation",
                ],
                severity_hint="high" if len(appearances) >= 3 else "moderate",
            )
            for svc, appearances in service_failures.items()
            if len(appearances) >= _MIN_OCCURRENCES
        ]


def _rec_key(rec: dict[str, Any]) -> str:
    title = rec.get("title", "")
    category = rec.get("category", "")
    return f"[{category}] {title[:_TITLE_KEY_LEN]}".strip()


def _recurrence_severity(occurrences: int, total_snapshots: int) -> str:
    ratio = occurrences / max(total_snapshots, 1)
    if ratio >= 0.7 or occurrences >= 5:
        return "high"
    if ratio >= 0.4 or occurrences >= 3:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Recommendation continuity tracking
# ---------------------------------------------------------------------------

@dataclass
class RecommendationLifespan:
    """Tracks a recommendation across snapshot history to measure persistence.

    A recommendation that persists across many scans is a chronic operational
    concern — it has been observed but not resolved.
    """
    title: str
    category: str
    first_seen: str         # created_at of first snapshot containing it
    last_seen: str          # created_at of last snapshot containing it
    occurrence_count: int   # how many snapshots contain it
    snapshot_ids: list[int]
    duration_days: float    # calendar time between first and last seen
    status: str             # "persistent", "recurring", "resolved", "new"
    severity_hint: str
    summary_statement: str  # human-readable persistence summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "occurrence_count": self.occurrence_count,
            "snapshot_ids": self.snapshot_ids,
            "duration_days": round(self.duration_days, 1),
            "status": self.status,
            "severity_hint": self.severity_hint,
            "summary_statement": self.summary_statement,
        }


class ContinuityEngine:
    """Tracks recommendation lifespan across snapshot history.

    Identifies which recommendations have been observed but not resolved —
    the operational continuity memory of chronic concerns.
    """

    def track(self, snapshots: list[dict[str, Any]]) -> list[RecommendationLifespan]:
        """Compute recommendation lifespans across all provided snapshots.

        snapshots: list of snapshot dicts (any order — engine will sort by created_at).
        Returns list sorted by occurrence_count descending.
        """
        if len(snapshots) < 1:
            return []

        sorted_snaps = sorted(snapshots, key=lambda s: s.get("created_at", ""))
        latest_snap = sorted_snaps[-1]
        latest_snap_id = latest_snap.get("id", 0)
        total = len(sorted_snaps)

        # Group appearances by title
        rec_appearances: dict[str, list[tuple[int, str, str]]] = {}
        # key: title → list of (snap_id, created_at, category)

        for snap in sorted_snaps:
            snap_id = snap.get("id", 0)
            created_at = snap.get("created_at", "")
            recs = snap.get("data", {}).get("recommendations", [])
            for rec in recs:
                title = rec.get("title", "").strip()
                category = rec.get("category", "")
                if title:
                    rec_appearances.setdefault(title, []).append((snap_id, created_at, category))

        lifespans: list[RecommendationLifespan] = []

        for title, appearances in rec_appearances.items():
            count = len(appearances)
            snap_ids = [a[0] for a in appearances]
            first_seen = min(a[1] for a in appearances)
            last_seen = max(a[1] for a in appearances)
            category = appearances[0][2] if appearances else ""

            duration_days = _duration_days(first_seen, last_seen)
            status = _continuity_status(count, total, latest_snap_id, snap_ids)
            severity_hint = _continuity_severity(count, total, duration_days, status)
            summary = _continuity_summary(title, count, duration_days, status)

            lifespans.append(RecommendationLifespan(
                title=title,
                category=category,
                first_seen=first_seen,
                last_seen=last_seen,
                occurrence_count=count,
                snapshot_ids=snap_ids,
                duration_days=duration_days,
                status=status,
                severity_hint=severity_hint,
                summary_statement=summary,
            ))

        lifespans.sort(key=lambda l: (-l.occurrence_count, -l.duration_days))

        logger.info(
            "Continuity tracking complete",
            extra={
                "snapshot_count": total,
                "tracked_recommendations": len(lifespans),
                "persistent_count": sum(1 for l in lifespans if l.status == "persistent"),
            },
        )
        return lifespans


def _duration_days(first_seen: str, last_seen: str) -> float:
    try:
        from datetime import datetime
        fmt_a = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
        fmt_b = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        return abs((fmt_b - fmt_a).total_seconds()) / 86400
    except Exception:
        return 0.0


def _continuity_status(
    count: int, total: int, latest_snap_id: int, snap_ids: list[int]
) -> str:
    seen_in_latest = latest_snap_id in snap_ids
    ratio = count / max(total, 1)
    if not seen_in_latest:
        return "resolved"
    if count == 1:
        return "new"
    if ratio >= 0.80:
        return "persistent"
    return "recurring"


def _continuity_severity(
    count: int, total: int, duration_days: float, status: str
) -> str:
    if status == "resolved":
        return "low"
    if status == "new":
        return "low"
    ratio = count / max(total, 1)
    if ratio >= 0.80 or duration_days >= 7 or count >= 5:
        return "high"
    if ratio >= 0.50 or duration_days >= 3 or count >= 3:
        return "moderate"
    return "low"


def _continuity_summary(
    title: str, count: int, duration_days: float, status: str
) -> str:
    if status == "resolved":
        return f"'{title}' resolved — no longer present in latest scan."
    if status == "new":
        return f"'{title}' newly detected — first occurrence."
    if status == "persistent":
        if duration_days >= 1:
            return (
                f"'{title}' persistent across {count} scans "
                f"({duration_days:.1f} days unresolved)."
            )
        return f"'{title}' persistent across {count} scans."
    # recurring
    if duration_days >= 1:
        return (
            f"'{title}' recurring — appeared {count} times "
            f"over {duration_days:.1f} days."
        )
    return f"'{title}' recurring — appeared {count} times."
