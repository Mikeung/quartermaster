"""
Ingestion Limits — lightweight rate accounting and burst detection.

Purpose:
- Prevent one project from overwhelming the store with excessive event volume
- Detect noisy workflows that generate disproportionate event counts
- Surface ingestion pressure to operators before storage limits are hit

Design rules:
- Advisory and lightweight rejection only
- No blocking queues
- No distributed throttling
- No async pipelines
- All inputs are pre-counted (not streaming)
- Deterministic: same input → same output

This module is used as a gate on ingestion and as a diagnostic for operators.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Default limits (per project, per hour)
_DEFAULT_MAX_EVENTS_PER_HOUR = 1_000
_DEFAULT_BURST_WINDOW_MINUTES = 5
_DEFAULT_BURST_THRESHOLD = 200       # events in a burst window
_DEFAULT_NOISY_WORKFLOW_SHARE = 0.80 # single workflow >80% of project events is noisy
_DEFAULT_PRESSURE_WARNING_FRACTION = 0.70
_DEFAULT_PRESSURE_CRITICAL_FRACTION = 0.90


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IngestionLimits:
    """Per-project ingestion configuration."""
    max_events_per_hour: int = _DEFAULT_MAX_EVENTS_PER_HOUR
    burst_threshold: int = _DEFAULT_BURST_THRESHOLD
    burst_window_minutes: int = _DEFAULT_BURST_WINDOW_MINUTES
    noisy_workflow_share: float = _DEFAULT_NOISY_WORKFLOW_SHARE


@dataclass
class IngestionWarning:
    """A single ingestion concern for a project."""
    project_id: str
    warning_type: str   # "rate_exceeded" | "burst_detected" | "noisy_workflow" | "oversized_project"
    severity: str       # "warning" | "critical"
    message: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "warning_type": self.warning_type,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class ProjectIngestionStatus:
    """Ingestion health status for one project."""
    project_id: str
    events_last_hour: int
    max_events_per_hour: int
    rate_fraction: float            # events_last_hour / max
    pressure_level: str             # "ok" | "warning" | "critical"
    warnings: list[IngestionWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "events_last_hour": self.events_last_hour,
            "max_events_per_hour": self.max_events_per_hour,
            "rate_fraction": round(self.rate_fraction, 3),
            "pressure_level": self.pressure_level,
            "warnings": [w.to_dict() for w in self.warnings],
        }


@dataclass
class PressureSummary:
    """Cross-project ingestion pressure overview."""
    total_projects_checked: int
    ok_count: int
    warning_count: int
    critical_count: int
    all_warnings: list[IngestionWarning]
    highest_pressure_projects: list[str]
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_projects_checked": self.total_projects_checked,
            "ok_count": self.ok_count,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "all_warnings": [w.to_dict() for w in self.all_warnings],
            "highest_pressure_projects": self.highest_pressure_projects,
            "observations": self.observations,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class IngestionLimitsChecker:
    """
    Evaluates ingestion rate health for one or more projects.

    Accepts pre-counted event volumes (not raw event streams).
    Deterministic: same counts → same warnings.
    """

    def check_project(
        self,
        project_id: str,
        events_last_hour: int,
        workflow_counts: dict[str, int] | None = None,
        limits: IngestionLimits | None = None,
    ) -> ProjectIngestionStatus:
        """
        Check ingestion health for one project.

        events_last_hour: total events ingested in the past hour
        workflow_counts: event counts per workflow for noisy detection
        limits: per-project limits (uses defaults if None)
        """
        lim = limits or IngestionLimits()
        warnings: list[IngestionWarning] = []

        rate_fraction = events_last_hour / max(lim.max_events_per_hour, 1)

        # Rate check
        if rate_fraction >= 1.0:
            warnings.append(IngestionWarning(
                project_id=project_id,
                warning_type="rate_exceeded",
                severity="critical",
                message=(
                    f"Project '{project_id}' has exceeded ingestion rate limit: "
                    f"{events_last_hour:,} events/hour (limit: {lim.max_events_per_hour:,})."
                ),
                evidence=[
                    f"Events last hour: {events_last_hour:,}",
                    f"Limit: {lim.max_events_per_hour:,}",
                    f"Rate: {rate_fraction:.1%} of limit",
                    "Consider sampling events or adjusting ingestion frequency.",
                ],
            ))
        elif rate_fraction >= _DEFAULT_PRESSURE_WARNING_FRACTION:
            warnings.append(IngestionWarning(
                project_id=project_id,
                warning_type="rate_exceeded",
                severity="warning",
                message=(
                    f"Project '{project_id}' is approaching ingestion rate limit: "
                    f"{events_last_hour:,} events/hour ({rate_fraction:.0%} of limit)."
                ),
                evidence=[
                    f"Events last hour: {events_last_hour:,}",
                    f"Limit: {lim.max_events_per_hour:,}",
                ],
            ))

        # Noisy workflow check
        if workflow_counts:
            noisy = _detect_noisy_workflows(
                project_id, workflow_counts, lim.noisy_workflow_share
            )
            warnings.extend(noisy)

        # Pressure level
        if rate_fraction >= 1.0 or any(w.severity == "critical" for w in warnings):
            pressure = "critical"
        elif rate_fraction >= _DEFAULT_PRESSURE_WARNING_FRACTION or warnings:
            pressure = "warning"
        else:
            pressure = "ok"

        return ProjectIngestionStatus(
            project_id=project_id,
            events_last_hour=events_last_hour,
            max_events_per_hour=lim.max_events_per_hour,
            rate_fraction=rate_fraction,
            pressure_level=pressure,
            warnings=warnings,
        )

    def check_burst(
        self,
        project_id: str,
        events_in_window: int,
        limits: IngestionLimits | None = None,
    ) -> IngestionWarning | None:
        """
        Check for burst ingestion in a short window.

        events_in_window: events ingested in the last burst_window_minutes.
        """
        lim = limits or IngestionLimits()
        if events_in_window < lim.burst_threshold:
            return None
        return IngestionWarning(
            project_id=project_id,
            warning_type="burst_detected",
            severity="warning",
            message=(
                f"Project '{project_id}' burst: {events_in_window:,} events in "
                f"{lim.burst_window_minutes} minutes (threshold: {lim.burst_threshold:,})."
            ),
            evidence=[
                f"Events in burst window: {events_in_window:,}",
                f"Burst threshold: {lim.burst_threshold:,}",
                f"Window: {lim.burst_window_minutes} minutes",
                "Bursts may indicate batch ingestion or runaway instrumentation.",
            ],
        )

    def build_pressure_summary(
        self,
        project_statuses: list[ProjectIngestionStatus],
    ) -> PressureSummary:
        """Build a cross-project pressure summary from project statuses."""
        ok = sum(1 for s in project_statuses if s.pressure_level == "ok")
        warning = sum(1 for s in project_statuses if s.pressure_level == "warning")
        critical = sum(1 for s in project_statuses if s.pressure_level == "critical")

        all_warnings: list[IngestionWarning] = []
        for s in project_statuses:
            all_warnings.extend(s.warnings)

        highest = [
            s.project_id
            for s in sorted(project_statuses, key=lambda x: x.rate_fraction, reverse=True)
            if s.pressure_level in ("warning", "critical")
        ][:5]

        observations = _build_summary_observations(ok, warning, critical, all_warnings)

        return PressureSummary(
            total_projects_checked=len(project_statuses),
            ok_count=ok,
            warning_count=warning,
            critical_count=critical,
            all_warnings=all_warnings,
            highest_pressure_projects=highest,
            observations=observations,
        )


# ---------------------------------------------------------------------------
# Ingestion gate
# ---------------------------------------------------------------------------

def check_ingestion_allowed(
    project_id: str,
    events_last_hour: int,
    limits: IngestionLimits | None = None,
) -> tuple[bool, str | None]:
    """
    Quick check: is ingestion allowed for this project right now?

    Returns (allowed, rejection_reason).
    allowed=True means proceed. allowed=False means reject with reason.

    This is the lightweight gate used in the POST /llm/events path.
    """
    lim = limits or IngestionLimits()
    if events_last_hour >= lim.max_events_per_hour:
        return False, (
            f"Ingestion rate limit exceeded for project '{project_id}': "
            f"{events_last_hour:,}/{lim.max_events_per_hour:,} events/hour. "
            "Reduce ingestion frequency or enable event sampling."
        )
    return True, None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_noisy_workflows(
    project_id: str,
    workflow_counts: dict[str, int],
    threshold: float,
) -> list[IngestionWarning]:
    total = sum(workflow_counts.values())
    if total == 0:
        return []
    warnings = []
    for wf, count in workflow_counts.items():
        share = count / total
        if share >= threshold:
            warnings.append(IngestionWarning(
                project_id=project_id,
                warning_type="noisy_workflow",
                severity="warning",
                message=(
                    f"Workflow '{wf}' in project '{project_id}' accounts for "
                    f"{share:.0%} of ingested events — may be over-instrumented."
                ),
                evidence=[
                    f"Workflow: {wf}",
                    f"Events: {count:,} of {total:,} total",
                    f"Share: {share:.1%}",
                    "Consider reducing ingestion frequency for this workflow, or add sampling.",
                ],
            ))
    return warnings


def _build_summary_observations(
    ok: int,
    warning: int,
    critical: int,
    warnings: list[IngestionWarning],
) -> list[str]:
    obs = []
    if critical > 0:
        obs.append(
            f"{critical} project(s) have critical ingestion pressure — "
            "rate limits exceeded. Immediate attention recommended."
        )
    if warning > 0:
        obs.append(
            f"{warning} project(s) approaching ingestion rate limits. "
            "Monitor for growth."
        )
    noisy = [w for w in warnings if w.warning_type == "noisy_workflow"]
    if noisy:
        project_names = list({w.project_id for w in noisy})
        obs.append(
            f"Noisy workflow patterns detected in: {', '.join(project_names)}."
        )
    if not obs:
        obs.append(
            f"All {ok} project(s) within normal ingestion limits."
        )
    return obs
