"""
Maintenance Assistant — prioritized operational checklist generator.

Purpose:
Aggregates signals from across the system (survivability, scaling boundaries,
ingestion quality, storage hygiene, project health) and generates a prioritized
list of maintenance actions for the operator.

Design rules:
- Advisory only. Never modifies state.
- All inputs are pre-fetched reports/dicts. No direct DB access.
- Deterministic: same inputs → same output.
- Bounded language throughout.
- Priority levels: critical > high > medium > low > info
- Actions are grouped into: Retention, Ingestion, Projects, Configuration, Monitoring
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Priority ordering (lower number = higher priority)
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


# -----------------------------------------------------------------------
# Output types
# -----------------------------------------------------------------------

@dataclass
class MaintenanceAction:
    """A single recommended maintenance action."""
    action_id: str
    priority: str             # "critical" | "high" | "medium" | "low" | "info"
    category: str             # "retention" | "ingestion" | "projects" | "configuration" | "monitoring"
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    suggested_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "priority": self.priority,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "suggested_command": self.suggested_command,
        }


@dataclass
class MaintenanceChecklist:
    """
    Prioritized operator maintenance checklist.

    Generated from cross-system signals. Actions are sorted by priority,
    then alphabetically by title within each priority level.
    """
    actions: list[MaintenanceAction]
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.actions)

    @property
    def requires_immediate_attention(self) -> bool:
        return self.critical_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "info_count": self.info_count,
            "total": self.total,
            "requires_immediate_attention": self.requires_immediate_attention,
            "generated_at": self.generated_at,
            "notes": self.notes,
            "advisory": (
                "This checklist is advisory. All actions require operator review. "
                "Suggested commands are provided as guidance, not guarantees."
            ),
        }

    def markdown(self) -> str:
        lines = [
            "# Maintenance Checklist",
            f"Generated: {self.generated_at}",
            "",
        ]

        summary_parts = []
        if self.critical_count:
            summary_parts.append(f"**{self.critical_count} CRITICAL**")
        if self.high_count:
            summary_parts.append(f"{self.high_count} high")
        if self.medium_count:
            summary_parts.append(f"{self.medium_count} medium")
        if self.low_count:
            summary_parts.append(f"{self.low_count} low")
        if self.info_count:
            summary_parts.append(f"{self.info_count} info")

        if summary_parts:
            lines.append(f"**Actions:** {' | '.join(summary_parts)}")
        else:
            lines.append("**No maintenance actions required.**")
        lines.append("")

        if self.notes:
            for n in self.notes:
                lines.append(f"> {n}")
            lines.append("")

        if not self.actions:
            lines += [
                "No maintenance actions identified at this time.",
                "",
                "_Advisory only. Run this check periodically to catch emerging issues early._",
            ]
            return "\n".join(lines)

        current_priority = None
        for action in self.actions:
            if action.priority != current_priority:
                current_priority = action.priority
                lines += [f"## {action.priority.upper()} Priority", ""]

            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "ℹ"}.get(
                action.priority, "•"
            )
            lines.append(f"### {icon} [{action.category.upper()}] {action.title}")
            lines.append("")
            lines.append(action.description)
            if action.evidence:
                lines.append("")
                for e in action.evidence:
                    lines.append(f"- {e}")
            if action.suggested_command:
                lines.append("")
                lines.append(f"```bash\n{action.suggested_command}\n```")
            lines.append("")

        lines += [
            "---",
            "_Advisory only. All maintenance actions require operator review and approval._",
        ]
        return "\n".join(lines)


# -----------------------------------------------------------------------
# Assistant
# -----------------------------------------------------------------------

class MaintenanceAssistant:
    """
    Generates a prioritized maintenance checklist from cross-system signals.

    Accepts pre-computed reports from survivability, scaling, ingestion quality,
    and project store queries. Synthesizes them into an operator-facing checklist.

    Usage:
        assistant = MaintenanceAssistant()
        checklist = assistant.generate(
            survivability_report=survivability.to_dict(),
            scaling_report=scaling.to_dict(),
            ingestion_quality_report=quality.to_dict(),
            stale_workflows=["ocr_pipeline_v1", "test_workflow"],
            noisy_projects=["proj_alpha"],
            ...
        )
    """

    def generate(
        self,
        *,
        survivability_report: dict[str, Any] | None = None,
        scaling_report: dict[str, Any] | None = None,
        ingestion_quality_report: dict[str, Any] | None = None,
        stale_workflows: list[str] | None = None,
        noisy_projects: list[str] | None = None,
        archived_project_ids: list[str] | None = None,
        archived_project_last_activity_days: dict[str, int] | None = None,
        db_size_bytes: int | None = None,
        oldest_snapshot_days: int | None = None,
        oldest_event_days: int | None = None,
        retention_last_run_days: int | None = None,
        scheduler_degraded_jobs: list[str] | None = None,
    ) -> MaintenanceChecklist:
        """
        Generate a prioritized maintenance checklist.

        Most parameters are optional — the assistant adapts to available signals.
        Pass whatever reports and scalars are available; missing data produces
        informational notices rather than errors.
        """
        actions: list[MaintenanceAction] = []
        seq = _Sequencer()

        # --- Survivability-derived actions ---
        if survivability_report:
            actions.extend(self._actions_from_survivability(survivability_report, seq))

        # --- Scaling-derived actions ---
        if scaling_report:
            actions.extend(self._actions_from_scaling(scaling_report, seq))

        # --- Ingestion quality actions ---
        if ingestion_quality_report:
            actions.extend(self._actions_from_quality(ingestion_quality_report, seq))

        # --- Stale workflows ---
        if stale_workflows:
            actions.extend(self._actions_from_stale_workflows(stale_workflows, seq))

        # --- Noisy projects ---
        if noisy_projects:
            actions.extend(self._actions_from_noisy_projects(noisy_projects, seq))

        # --- Stale archived projects ---
        if archived_project_ids and archived_project_last_activity_days:
            actions.extend(self._actions_from_stale_archives(
                archived_project_ids, archived_project_last_activity_days, seq
            ))

        # --- Retention overdue ---
        if retention_last_run_days is not None and retention_last_run_days > 14:
            actions.append(self._action_retention_overdue(retention_last_run_days, seq))

        # --- Scheduler degraded jobs ---
        if scheduler_degraded_jobs:
            actions.append(self._action_degraded_scheduler(scheduler_degraded_jobs, seq))

        # --- DB size advisory ---
        if db_size_bytes and db_size_bytes > 100 * 1024 * 1024:
            actions.extend(self._actions_from_db_size(db_size_bytes, seq))

        # --- Oldest data advisory ---
        if oldest_snapshot_days and oldest_snapshot_days > 60:
            actions.append(self._action_old_snapshots(oldest_snapshot_days, seq))
        if oldest_event_days and oldest_event_days > 60:
            actions.append(self._action_old_events(oldest_event_days, seq))

        # Sort by priority then title
        actions.sort(key=lambda a: (_PRIORITY_ORDER.get(a.priority, 99), a.title))

        counts = dict.fromkeys(_PRIORITY_ORDER, 0)
        for a in actions:
            counts[a.priority] = counts.get(a.priority, 0) + 1

        notes = []
        if not actions:
            notes.append(
                "No maintenance actions identified. System appears to be in good operational health."
            )

        logger.info(
            "Maintenance checklist generated",
            extra={"total_actions": len(actions), "critical": counts.get("critical", 0)},
        )

        return MaintenanceChecklist(
            actions=actions,
            critical_count=counts.get("critical", 0),
            high_count=counts.get("high", 0),
            medium_count=counts.get("medium", 0),
            low_count=counts.get("low", 0),
            info_count=counts.get("info", 0),
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # Signal → action translators
    # -----------------------------------------------------------------------

    def _actions_from_survivability(
        self, report: dict[str, Any], seq: _Sequencer
    ) -> list[MaintenanceAction]:
        actions = []
        for check in report.get("checks", []):
            sev = check.get("severity", "ok")
            if sev == "ok":
                continue
            name = check.get("name", "Unknown Check")
            msg = check.get("message", "")
            evidence = check.get("evidence", [])
            priority = "critical" if sev == "critical" else "high"

            category = "monitoring"
            command = ""
            if "retention" in name.lower() or "backlog" in name.lower():
                category = "retention"
                command = "GET /operations/retention?dry_run=true"
            elif "growth" in name.lower() or "database" in name.lower():
                category = "retention"
                command = "GET /operations/storage"
            elif "scheduler" in name.lower():
                category = "monitoring"
                command = "GET /operations/scheduler-health"
            elif "archive" in name.lower():
                category = "projects"
                command = "GET /projects"
            elif "ingestion" in name.lower():
                category = "ingestion"
                command = "GET /projects/ingestion-pressure"

            actions.append(MaintenanceAction(
                action_id=seq.next("surv"),
                priority=priority,
                category=category,
                title=f"Survivability: {name}",
                description=msg,
                evidence=evidence[:3],
                suggested_command=command,
            ))
        return actions

    def _actions_from_scaling(
        self, report: dict[str, Any], seq: _Sequencer
    ) -> list[MaintenanceAction]:
        actions = []
        for check in report.get("checks", []):
            sev = check.get("severity", "ok")
            if sev == "ok":
                continue
            name = check.get("name", "Unknown")
            msg = check.get("message", "")
            recs = check.get("recommendations", [])
            priority = "critical" if sev == "critical" else "medium"

            category = "monitoring"
            command = ""
            if "event" in name.lower():
                category = "retention"
                command = "POST /operations/retention/llm-events {\"retention_days\": 30, \"dry_run\": true}"
            elif "snapshot" in name.lower() or "database" in name.lower():
                category = "retention"
                command = "POST /operations/retention/snapshots {\"retention_days\": 30, \"dry_run\": true}"
            elif "latency" in name.lower() or "report" in name.lower():
                category = "monitoring"
                command = "GET /stability/audit"
            elif "write" in name.lower() or "sqlite" in name.lower():
                category = "configuration"
                command = "GET /operations/storage"

            actions.append(MaintenanceAction(
                action_id=seq.next("scale"),
                priority=priority,
                category=category,
                title=f"Scaling: {name}",
                description=msg,
                evidence=recs[:2],
                suggested_command=command,
            ))
        return actions

    def _actions_from_quality(
        self, report: dict[str, Any], seq: _Sequencer
    ) -> list[MaintenanceAction]:
        actions = []
        band = report.get("quality_band", "good")
        score = report.get("quality_score", 1.0)
        warnings = report.get("integration_warnings", [])
        suggestions = report.get("improvement_suggestions", [])

        if band == "poor":
            priority = "high"
            desc = (
                f"Ingestion quality score is {score:.2f} (poor). "
                "Event data is missing key fields, reducing the value of cost intelligence."
            )
            actions.append(MaintenanceAction(
                action_id=seq.next("qual"),
                priority=priority,
                category="ingestion",
                title="Improve Ingestion Quality (Poor Score)",
                description=desc,
                evidence=warnings[:3] + suggestions[:2],
                suggested_command="GET /llm/quality",
            ))
        elif band == "fair":
            priority = "medium"
            desc = (
                f"Ingestion quality score is {score:.2f} (fair). "
                "Some dimensions have gaps — review integration configuration."
            )
            actions.append(MaintenanceAction(
                action_id=seq.next("qual"),
                priority=priority,
                category="ingestion",
                title="Improve Ingestion Quality (Fair Score)",
                description=desc,
                evidence=suggestions[:3],
                suggested_command="GET /llm/quality",
            ))

        for w in warnings[:3]:
            actions.append(MaintenanceAction(
                action_id=seq.next("qwarn"),
                priority="low",
                category="ingestion",
                title="Ingestion Quality Warning",
                description=w,
                suggested_command="GET /llm/quality",
            ))

        return actions

    def _actions_from_stale_workflows(
        self, stale: list[str], seq: _Sequencer
    ) -> list[MaintenanceAction]:
        return [MaintenanceAction(
            action_id=seq.next("wflow"),
            priority="low",
            category="ingestion",
            title=f"Stale Workflow: {wf}",
            description=(
                f"Workflow '{wf}' appears to have produced no events recently. "
                "It may be unused, renamed, or the integration may have broken."
            ),
            evidence=[
                f"Workflow name: {wf}",
                "Review whether this workflow is still active.",
            ],
            suggested_command=f"GET /llm/events?workflow={wf}",
        ) for wf in stale]

    def _actions_from_noisy_projects(
        self, noisy: list[str], seq: _Sequencer
    ) -> list[MaintenanceAction]:
        return [MaintenanceAction(
            action_id=seq.next("noise"),
            priority="medium",
            category="ingestion",
            title=f"Noisy Project: {pid}",
            description=(
                f"Project '{pid}' appears to be generating a disproportionate share of ingestion volume. "
                "This may indicate a runaway workflow or misconfigured event rate."
            ),
            evidence=[
                f"Project: {pid}",
                "Review ingestion limits and workflow event rates.",
            ],
            suggested_command=f"GET /projects/{pid}/pressure",
        ) for pid in noisy]

    def _actions_from_stale_archives(
        self,
        archived_ids: list[str],
        last_activity_days: dict[str, int],
        seq: _Sequencer,
    ) -> list[MaintenanceAction]:
        actions = []
        stale_threshold = 180
        for pid in archived_ids:
            days = last_activity_days.get(pid, 0)
            if days >= stale_threshold:
                actions.append(MaintenanceAction(
                    action_id=seq.next("arch"),
                    priority="low",
                    category="projects",
                    title=f"Stale Archive: {pid}",
                    description=(
                        f"Project '{pid}' has been archived and had no activity for {days} days. "
                        "Its data continues to consume storage. "
                        "Consider whether retention should be run on this project."
                    ),
                    evidence=[
                        f"Days since last activity: {days}",
                        "Archived projects are not automatically deleted.",
                    ],
                    suggested_command=f"POST /operations/retention/snapshots {{\"project_id\": \"{pid}\", \"dry_run\": true}}",
                ))
        return actions

    def _action_retention_overdue(self, days: int, seq: _Sequencer) -> MaintenanceAction:
        priority = "high" if days > 30 else "medium"
        return MaintenanceAction(
            action_id=seq.next("ret"),
            priority=priority,
            category="retention",
            title=f"Retention Not Run in {days} Days",
            description=(
                f"Retention has not been run in {days} days. "
                "Data may be accumulating beyond the configured retention window."
            ),
            evidence=[
                f"Days since last retention run: {days}",
                "Recommended: run retention at least weekly.",
            ],
            suggested_command="POST /operations/retention/snapshots {\"dry_run\": true}",
        )

    def _action_degraded_scheduler(
        self, degraded_jobs: list[str], seq: _Sequencer
    ) -> MaintenanceAction:
        return MaintenanceAction(
            action_id=seq.next("sched"),
            priority="high",
            category="monitoring",
            title=f"Scheduler Degradation ({len(degraded_jobs)} Jobs)",
            description=(
                f"{len(degraded_jobs)} scheduler job(s) have accumulated consecutive errors. "
                "Scans may not be running reliably."
            ),
            evidence=[f"Degraded: {', '.join(degraded_jobs)}"],
            suggested_command="GET /operations/scheduler-health",
        )

    def _actions_from_db_size(
        self, size_bytes: int, seq: _Sequencer
    ) -> list[MaintenanceAction]:
        size_mb = size_bytes / (1024 * 1024)
        priority = "high" if size_mb > 500 else "medium"
        return [MaintenanceAction(
            action_id=seq.next("dbsz"),
            priority=priority,
            category="retention",
            title=f"Database Size: {size_mb:.0f} MB",
            description=(
                f"Database file has grown to {size_mb:.0f} MB. "
                "Consider running retention and/or vacuuming to reclaim space."
            ),
            evidence=[
                f"Current size: {size_mb:.0f} MB",
                "Recommended ceiling for comfortable SQLite operation: 200 MB",
            ],
            suggested_command="GET /operations/storage",
        )]

    def _action_old_snapshots(self, days: int, seq: _Sequencer) -> MaintenanceAction:
        priority = "medium" if days > 90 else "low"
        return MaintenanceAction(
            action_id=seq.next("oldsnap"),
            priority=priority,
            category="retention",
            title=f"Old Snapshots ({days} Days)",
            description=(
                f"The oldest snapshot is {days} days old. "
                "Retention may not be configured to prune data beyond the active window."
            ),
            suggested_command="POST /operations/retention/snapshots {\"dry_run\": true}",
        )

    def _action_old_events(self, days: int, seq: _Sequencer) -> MaintenanceAction:
        priority = "medium" if days > 90 else "low"
        return MaintenanceAction(
            action_id=seq.next("oldev"),
            priority=priority,
            category="retention",
            title=f"Old LLM Events ({days} Days)",
            description=(
                f"The oldest LLM event is {days} days old. "
                "Cost intelligence aggregations may include stale data."
            ),
            suggested_command="POST /operations/retention/llm-events {\"dry_run\": true}",
        )


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------

class _Sequencer:
    """Simple counter for generating action IDs."""
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}-{self._counts[prefix]:03d}"
