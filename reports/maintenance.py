"""
Maintenance reports — markdown output for Phase 8 operational deployment readiness.

Produces:
- maintenance report (full operational status)
- retention summary (what retention would do / has done)
- scheduler health report
- storage growth report
- deployment readiness report

All output is markdown with advisory footer.
No frontend. No streaming. No autonomous action.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def generate_maintenance_report(
    selfcheck: dict[str, Any],
    storage: dict[str, Any] | None = None,
    scheduler: dict[str, Any] | None = None,
    retention_plan: dict[str, Any] | None = None,
    delivery_health: dict[str, Any] | None = None,
) -> str:
    """Generate a full operational maintenance report in markdown."""
    now = _now()
    overall = selfcheck.get("overall_status", "unknown").upper()
    passed = selfcheck.get("passed", 0)
    total = selfcheck.get("total", 0)
    items = selfcheck.get("items", [])

    lines: list[str] = [
        "# Operational Maintenance Report",
        f"**Generated:** {now}",
        f"**System status:** {overall}",
        f"**Self-checks:** {passed}/{total} passed",
        "",
        "> This report summarizes the operational health of the deployment.",
        "> All observations are advisory — no automated actions have been taken.",
        "",
    ]

    # Self-check items
    if items:
        lines += ["## Self-Check Results", ""]
        for item in items:
            icon = "PASS" if item.get("passed") else "FAIL"
            sev = item.get("severity", "ok").upper()
            lines.append(f"### [{icon}/{sev}] {item.get('name', '?')}")
            lines.append(item.get("message", ""))
            details = item.get("details", {})
            if details:
                for k, v in details.items():
                    lines.append(f"- **{k}:** {v}")
            lines.append("")

    # Storage summary
    if storage:
        pressure = storage.get("pressure_level", "ok").upper()
        disk_pct = storage.get("disk_usage_percent", 0.0)
        snap_count = storage.get("snapshot_count", 0)
        max_count = storage.get("max_snapshot_count", 0)
        db_size = storage.get("db_size_human", "?")
        lines += [
            "## Storage Summary",
            f"**Pressure level:** {pressure}",
            f"**Disk usage:** {disk_pct:.1f}%",
            f"**Database size:** {db_size}",
            f"**Snapshot count:** {snap_count}/{max_count}",
            "",
        ]
        for obs in storage.get("observations", [])[:4]:
            lines.append(f"- {obs}")
        lines.append("")

    # Scheduler summary
    if scheduler:
        running = scheduler.get("running", False)
        sched_status = scheduler.get("overall_status", "unknown").upper()
        degraded = scheduler.get("degraded_jobs", [])
        lines += [
            "## Scheduler Summary",
            f"**Running:** {'yes' if running else 'no'}",
            f"**Status:** {sched_status}",
        ]
        if degraded:
            lines.append(f"**Degraded jobs:** {', '.join(degraded)}")
        lines.append("")

    # Retention plan preview
    if retention_plan:
        dry_run = retention_plan.get("dry_run", True)
        total_snaps = retention_plan.get("total_snapshots", 0)
        del_count = retention_plan.get("deletion_count", 0)
        kept = retention_plan.get("kept_count", 0)
        lines += [
            "## Retention Plan Preview",
            f"**Mode:** {'DRY RUN' if dry_run else 'LIVE'}",
            f"**Total snapshots:** {total_snaps}",
            f"**Would delete:** {del_count}",
            f"**Would keep:** {kept}",
            "",
        ]
        policy = retention_plan.get("policy", {})
        if policy:
            lines.append(
                f"- Policy: {policy.get('retention_days', '?')}d age limit, "
                f"{policy.get('max_snapshot_count', '?')} max count, "
                f"{policy.get('min_keep_count', '?')} min keep"
            )
        lines.append("")

    # Delivery health summary
    if delivery_health is not None:
        enabled = delivery_health.get("telegram_enabled", False)
        if enabled:
            success = delivery_health.get("success_count", 0)
            failures = delivery_health.get("failure_count", 0)
            suppressions = delivery_health.get("total_suppression_count", 0)
            avg_ms = delivery_health.get("avg_latency_ms")
            latency_str = f"{avg_ms:.0f} ms" if avg_ms is not None else "n/a"
            lines += [
                "## Telegram Delivery Health",
                f"**Successes:** {success} | **Failures:** {failures} | "
                f"**Suppressions:** {suppressions}",
                f"**Avg latency:** {latency_str}",
                "",
            ]
            last_failure = delivery_health.get("last_failure_error")
            if last_failure:
                lines.append(f"**Last failure:** {last_failure}")
                lines.append("")
            q_count = delivery_health.get("quiet_hour_suppression_count", 0)
            d_count = delivery_health.get("duplicate_suppression_count", 0)
            r_count = delivery_health.get("rate_limit_suppression_count", 0)
            if suppressions > 0:
                lines.append(
                    f"- Quiet-hour: {q_count} | Duplicate: {d_count} | Rate-limit: {r_count}"
                )
                lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_retention_summary(result: dict[str, Any]) -> str:
    """Generate a retention operation summary in markdown."""
    now = _now()
    executed = result.get("executed", False)
    message = result.get("message", "")
    deleted_ids = result.get("deleted_ids", [])
    plan = result.get("plan", {})

    lines: list[str] = [
        "# Retention Operation Summary",
        f"**Generated:** {now}",
        f"**Executed:** {'yes' if executed else 'no (dry run)'}",
        f"**Result:** {message}",
        "",
    ]

    if plan:
        total = plan.get("total_snapshots", 0)
        del_count = plan.get("deletion_count", 0)
        kept = plan.get("kept_count", 0)
        lines += [
            "## Plan Details",
            f"- Total snapshots before run: {total}",
            f"- Identified for deletion: {del_count}",
            f"- Retained: {kept}",
            "",
        ]
        policy = plan.get("policy", {})
        if policy:
            lines += [
                "## Policy Applied",
                f"- Retention days: {policy.get('retention_days', '?')}",
                f"- Max snapshot count: {policy.get('max_snapshot_count', '?')}",
                f"- Min keep count: {policy.get('min_keep_count', '?')}",
                "",
            ]

    if deleted_ids:
        lines.append(f"**Deleted snapshot IDs:** {', '.join(str(i) for i in deleted_ids[:20])}")
        if len(deleted_ids) > 20:
            lines.append(f"_(and {len(deleted_ids) - 20} more)_")
        lines.append("")

    if not executed:
        lines += [
            "> This was a dry run. No snapshots were deleted.",
            "> To execute, set dry_run=False on the RetentionPolicy.",
            "",
        ]

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_scheduler_health_report(health: dict[str, Any]) -> str:
    """Generate a scheduler health report in markdown."""
    now = _now()
    running = health.get("running", False)
    overall = health.get("overall_status", "unknown").upper()
    jobs = health.get("jobs", [])

    lines: list[str] = [
        "# Scheduler Health Report",
        f"**Generated:** {now}",
        f"**Scheduler running:** {'yes' if running else 'no'}",
        f"**Overall status:** {overall}",
        f"**Job count:** {len(jobs)}",
        "",
    ]

    if not running:
        lines += [
            "> WARNING: Scheduler is not running. Periodic scans are not executing.",
            "",
        ]

    if jobs:
        lines += ["## Job Status", ""]
        for job in jobs:
            jid = job.get("id", "?")
            status = job.get("status", "ok").upper()
            last_ok = job.get("last_success", "never")
            errors = job.get("consecutive_errors", 0)
            runs = job.get("total_runs", 0)
            next_run = job.get("next_run", "unknown")
            lines.append(f"### {jid} [{status}]")
            lines.append(f"- **Last success:** {last_ok}")
            lines.append(f"- **Consecutive errors:** {errors}")
            lines.append(f"- **Total runs:** {runs}")
            lines.append(f"- **Next run:** {next_run}")
            lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_storage_growth_report(
    current: dict[str, Any],
    growth: dict[str, Any] | None = None,
) -> str:
    """Generate a storage growth report in markdown."""
    now = _now()
    pressure = current.get("pressure_level", "ok").upper()
    disk_pct = current.get("disk_usage_percent", 0.0)
    db_size = current.get("db_size_human", "?")
    snap_count = current.get("snapshot_count", 0)
    max_count = current.get("max_snapshot_count", 0)

    lines: list[str] = [
        "# Storage Growth Report",
        f"**Generated:** {now}",
        f"**Storage pressure:** {pressure}",
        f"**Disk usage:** {disk_pct:.1f}%",
        f"**Database size:** {db_size}",
        f"**Snapshots:** {snap_count}/{max_count}",
        "",
        "> Storage observations are point-in-time.",
        "> Growth trends require multiple observations over time.",
        "",
    ]

    for obs in current.get("observations", []):
        lines.append(f"- {obs}")
    lines.append("")

    if growth:
        lines += ["## Growth Trend", ""]
        lines.append(f"**Window:** {growth.get('window_description', '?')}")
        lines.append(f"**DB growth:** {growth.get('db_growth_human', '?')}")
        lines.append(f"**Snapshot growth:** {growth.get('snapshot_growth', 0)}")
        lines.append("")
        for obs in growth.get("observations", []):
            lines.append(f"- {obs}")
        lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_deployment_readiness_report(
    selfcheck: dict[str, Any],
    profile_name: str = "standard",
    profile_info: dict[str, Any] | None = None,
) -> str:
    """Generate a deployment readiness report in markdown."""
    now = _now()
    overall = selfcheck.get("overall_status", "unknown")
    passed = selfcheck.get("passed", 0)
    total = selfcheck.get("total", 0)
    ready = overall == "ok"

    lines: list[str] = [
        "# Deployment Readiness Report",
        f"**Generated:** {now}",
        f"**Profile:** {profile_name}",
        f"**Self-checks:** {passed}/{total} passed",
        f"**Readiness verdict:** {'READY' if ready else 'NOT READY — see issues below'}",
        "",
    ]

    failed = [i for i in selfcheck.get("items", []) if not i.get("passed")]
    if failed:
        lines += ["## Issues Requiring Attention", ""]
        for item in failed:
            sev = item.get("severity", "warning").upper()
            lines.append(f"- **[{sev}]** {item.get('name', '?')}: {item.get('message', '')}")
        lines.append("")

    if profile_info:
        lines += [
            "## Active Deployment Profile",
            f"**Name:** {profile_info.get('name', profile_name)}",
            f"**Scan interval:** {profile_info.get('scan_interval_seconds', '?')}s",
            f"**Retention days:** {profile_info.get('retention_days', '?')}",
            f"**Max snapshots:** {profile_info.get('max_snapshot_count', '?')}",
            f"**Runtime scanning:** {profile_info.get('runtime_scanning_enabled', '?')}",
            "",
        ]

    if ready:
        lines += ["> System is operational and all self-checks pass.", ""]
    else:
        lines += [
            "> System has issues that should be reviewed before relying on it in production.",
            "",
        ]

    lines += _advisory_footer()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _advisory_footer() -> list[str]:
    return [
        "---",
        "*Advisory only — all operational decisions require human review.*",
        "*Generated by Quartermaster — Observe automatically. Decide manually.*",
    ]
