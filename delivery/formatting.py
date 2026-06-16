"""
Telegram message formatting — compact, mobile-readable, operationally actionable.

Each format function answers: "What matters right now?"

Uses Telegram HTML parse mode.
All output is bounded to < 4096 chars (Telegram limit).
No raw JSON. No markdown walls. No evidence dumps.
"""

from __future__ import annotations

from datetime import UTC, datetime

_MAX_LEN = 4000   # leave headroom below 4096 for safety
_TRUNCATION_NOTICE = "\n\n<i>(truncated — see full report)</i>"


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------

def format_daily_digest(
    *,
    system_status: str,
    scan_count: int,
    snapshot_count: int,
    max_snapshot_count: int,
    top_recommendations: list[str] | None = None,
    active_recommendation_count: int = 0,
    storage_status: str = "ok",
    disk_pct: float = 0.0,
    scheduler_status: str = "ok",
    scheduler_job_count: int = 0,
    generated_at: str | None = None,
) -> str:
    ts = generated_at or _now()
    status_icon = _status_icon(system_status)
    snap_pct = (snapshot_count / max_snapshot_count * 100) if max_snapshot_count > 0 else 0.0

    lines = [
        "<b>Daily Operational Digest</b>",
        f"{ts}",
        "",
        f"{status_icon} <b>System:</b> {system_status.upper()}",
        f"<b>Scans today:</b> {scan_count}",
        f"<b>Snapshots:</b> {snapshot_count}/{max_snapshot_count} ({snap_pct:.0f}%)",
    ]

    if top_recommendations:
        lines.append("")
        lines.append(f"<b>Recommendations ({active_recommendation_count} active):</b>")
        for rec in top_recommendations[:3]:
            lines.append(f"• {_escape(rec)}")

    lines += [
        "",
        f"<b>Storage:</b> {disk_pct:.0f}% disk used ({storage_status})",
        f"<b>Scheduler:</b> {scheduler_job_count} job(s), {scheduler_status}",
    ]

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Critical alert
# ---------------------------------------------------------------------------

def format_critical_alert(
    *,
    kind: str,
    summary: str,
    confidence: float = 0.0,
    evidence: list[str] | None = None,
    generated_at: str | None = None,
) -> str:
    ts = generated_at or _now()
    lines = [
        f"🚨 <b>CRITICAL: {_escape(kind)}</b>",
        f"{ts}",
        "",
        _escape(summary),
    ]

    if confidence > 0.0:
        lines.append(f"\n<b>Confidence:</b> {confidence:.0%}")

    if evidence:
        lines.append("")
        lines.append("<b>Evidence:</b>")
        for ev in evidence[:3]:
            lines.append(f"• {_escape(ev)}")

    lines += [
        "",
        "<i>Action required — review and decide manually.</i>",
    ]

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------

def format_weekly_digest(
    *,
    scan_count_7d: int,
    active_concern_count: int,
    resolved_count: int,
    new_count: int,
    top_concerns: list[str] | None = None,
    system_status: str = "ok",
    generated_at: str | None = None,
) -> str:
    ts = generated_at or _now()
    status_icon = _status_icon(system_status)

    lines = [
        "<b>Weekly Operational Digest</b>",
        f"{ts}",
        "",
        f"{status_icon} <b>System:</b> {system_status.upper()}",
        f"<b>Scans this week:</b> {scan_count_7d}",
        f"<b>Active concerns:</b> {active_concern_count} "
        f"(+{new_count} new, {resolved_count} resolved)",
    ]

    if top_concerns:
        lines.append("")
        lines.append("<b>Top concerns:</b>")
        for concern in top_concerns[:4]:
            lines.append(f"• {_escape(concern)}")

    lines += [
        "",
        "<i>Advisory only — all decisions require human review.</i>",
    ]

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Survivability warning
# ---------------------------------------------------------------------------

def format_survivability_warning(
    *,
    outlook: str,
    warning_checks: list[str],
    critical_checks: list[str] | None = None,
    generated_at: str | None = None,
) -> str:
    ts = generated_at or _now()
    icon = "🚨" if critical_checks else "⚠️"

    lines = [
        f"{icon} <b>Survivability Warning</b>",
        f"{ts}",
        f"<b>Long-term outlook:</b> {_escape(outlook.replace('_', ' '))}",
        "",
    ]

    if critical_checks:
        lines.append("<b>Critical issues:</b>")
        for check in critical_checks[:3]:
            lines.append(f"• {_escape(check)}")
        lines.append("")

    if warning_checks:
        lines.append("<b>Warnings:</b>")
        for check in warning_checks[:4]:
            lines.append(f"• {_escape(check)}")
        lines.append("")

    lines.append("<i>Review before next maintenance window.</i>")

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Storage pressure warning
# ---------------------------------------------------------------------------

def format_storage_pressure_warning(
    *,
    pressure_level: str,
    disk_pct: float,
    db_size_human: str = "?",
    snapshot_count: int = 0,
    max_snapshot_count: int = 0,
    observations: list[str] | None = None,
    generated_at: str | None = None,
) -> str:
    ts = generated_at or _now()
    icon = "🚨" if pressure_level == "critical" else "⚠️"
    snap_info = (
        f"{snapshot_count}/{max_snapshot_count}"
        if max_snapshot_count > 0
        else str(snapshot_count)
    )

    lines = [
        f"{icon} <b>Storage Pressure: {pressure_level.upper()}</b>",
        f"{ts}",
        "",
        f"<b>Disk:</b> {disk_pct:.0f}% used",
        f"<b>DB size:</b> {_escape(db_size_human)}",
        f"<b>Snapshots:</b> {snap_info}",
    ]

    if observations:
        lines.append("")
        lines.append("<b>Notes:</b>")
        for obs in observations[:3]:
            lines.append(f"• {_escape(obs)}")

    lines += [
        "",
        "<i>Consider running retention to free space.</i>",
    ]

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Operational report summary (delta-first, mobile-optimized)
# ---------------------------------------------------------------------------

def format_operational_summary(
    *,
    report_type: str,
    timestamp: str | None = None,
    # Change section
    drift_events: list[str] | None = None,
    drift_count: int = 0,
    # Risk section
    security_high: list[str] | None = None,
    security_medium_count: int = 0,
    new_risks: list[str] | None = None,
    # Health section
    health_failures: list[str] | None = None,
    pipeline_ok: bool = True,
    # Coverage section
    unscanned_services: list[str] | None = None,
    # Recommendations
    new_recs: list[str] | None = None,
    # Pipeline confirmation
    scan_count: int = 0,
    target_count: int = 0,
    snapshot_count: int = 0,
    delivery_state: dict | None = None,
    # Delivery status (for this report)
    git_ok: bool | None = None,
    telegram_ok: bool | None = None,
) -> str:
    """
    Produce a compact, mobile-readable operator summary for Telegram.

    Layout:
      HEADER (type + timestamp)
      [DELTA] — what changed (only if non-empty)
      [RISKS] — high-severity findings (only if present)
      [GAPS]  — unscanned services (count only unless few)
      [RECS]  — new recommendations (first 3 only)
      [STATUS] — pipeline confirmation (last line)
    """
    ts = timestamp or _now()
    _type_labels = {
        "daily": "Daily Report",
        "drift": "Drift Detected",
        "security": "Security Findings",
        "selfmonitor": "Self-Monitor",
        "vps": "VPS Snapshot",
    }
    label = _type_labels.get(report_type, report_type.title())

    # Determine top-level icon. The daily report is the CALM decision channel — it
    # never sirens (🚨). Real-time urgency is the push channel's job; the daily digest
    # summarises calmly even when it contains high-severity items. Other report types
    # (drift/security/selfmonitor) are alert channels and keep the siren.
    has_critical = bool(security_high or health_failures or (not pipeline_ok))
    has_changes = bool(drift_events or drift_count > 0)
    if report_type == "daily":
        icon = "📋"
    else:
        icon = "🚨" if has_critical else ("📊" if has_changes else "✅")

    lines = [
        f"{icon} <b>{_escape(label)}</b>",
        f"<code>{_escape(ts)}</code>",
        "",
    ]

    # DELTA — what changed
    if drift_events:
        lines.append("<b>Changes:</b>")
        for ev in drift_events[:5]:
            lines.append(f"  + {_escape(ev)}")
        if len(drift_events) > 5:
            lines.append(f"  <i>…and {len(drift_events) - 5} more</i>")
        lines.append("")
    elif drift_count > 0:
        lines += [f"<b>Changes:</b> {drift_count} event(s)", ""]
    else:
        lines += ["<b>Changes:</b> none", ""]

    # RISKS — high severity first
    if security_high:
        lines.append("<b>Security (high):</b>")
        for item in security_high[:3]:
            lines.append(f"  ⚠ {_escape(item)}")
        if len(security_high) > 3:
            lines.append(f"  <i>…and {len(security_high) - 3} more</i>")
        if security_medium_count:
            lines.append(f"  <i>+ {security_medium_count} medium finding(s)</i>")
        lines.append("")
    elif new_risks:
        lines.append("<b>New risks:</b>")
        for r in new_risks[:3]:
            lines.append(f"  ⚠ {_escape(r)}")
        lines.append("")

    # HEALTH — pipeline failures
    if health_failures:
        lines.append("<b>Health failures:</b>")
        for f in health_failures[:3]:
            lines.append(f"  ✗ {_escape(f)}")
        lines.append("")

    # COVERAGE GAPS
    if unscanned_services:
        if len(unscanned_services) <= 4:
            lines.append("<b>No scan coverage:</b>")
            for svc in unscanned_services:
                lines.append(f"  · {_escape(svc)}")
        else:
            lines.append(f"<b>Coverage gaps:</b> {len(unscanned_services)} services unscanned")
        lines.append("")

    # NEW RECOMMENDATIONS
    if new_recs:
        lines.append("<b>New recommendations:</b>")
        for rec in new_recs[:3]:
            lines.append(f"  → {_escape(rec)}")
        lines.append("")

    # STATUS LINE — last, minimal
    status_parts = [f"scans:{scan_count}"]
    if target_count:
        status_parts.append(f"targets:{target_count}")
    if snapshot_count:
        status_parts.append(f"snapshots:{snapshot_count}")

    delivery_flags = []
    if git_ok is False:
        delivery_flags.append("git:FAIL")
    if telegram_ok is False:
        delivery_flags.append("tg:FAIL")
    if delivery_state:
        tg_fails = delivery_state.get("telegram_failures_since_success", 0)
        git_fails = delivery_state.get("git_failures_since_success", 0)
        if tg_fails > 0:
            delivery_flags.append(f"tg_fails:{tg_fails}")
        if git_fails > 0:
            delivery_flags.append(f"git_fails:{git_fails}")

    status_line = "  ".join(status_parts)
    if delivery_flags:
        status_line += "  " + "  ".join(delivery_flags)

    lines.append(f"<code>{_escape(status_line)}</code>")

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Self-monitor alert (lightweight, immediate)
# ---------------------------------------------------------------------------

def format_selfmonitor_alert(
    *,
    failures: list[str],
    timestamp: str | None = None,
    delivery_state: dict | None = None,
) -> str:
    ts = timestamp or _now()
    lines = [
        "🚨 <b>Self-Monitor Alert</b>",
        f"<code>{_escape(ts)}</code>",
        "",
        "<b>Pipeline failures:</b>",
    ]
    for f in failures:
        lines.append(f"  ✗ {_escape(f)}")

    if delivery_state:
        last_git = delivery_state.get("last_git_push_success", "never")
        last_tg = delivery_state.get("last_telegram_success", "never")
        lines += [
            "",
            f"Last git push: <code>{_escape(str(last_git))}</code>",
            f"Last Telegram: <code>{_escape(str(last_tg))}</code>",
        ]

    lines += ["", "<i>Check cron logs and service status.</i>"]
    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Drift report summary
# ---------------------------------------------------------------------------

def format_drift_summary(
    *,
    changes: list[str],
    target: str = "VPS",
    timestamp: str | None = None,
) -> str:
    ts = timestamp or _now()
    icon = "📡" if changes else "✅"
    lines = [
        f"{icon} <b>Drift: {_escape(target)}</b>",
        f"<code>{_escape(ts)}</code>",
        "",
    ]
    if changes:
        for ch in changes[:8]:
            lines.append(f"  + {_escape(ch)}")
        if len(changes) > 8:
            lines.append(f"  <i>…and {len(changes) - 8} more</i>")
    else:
        lines.append("<i>No infrastructure changes detected.</i>")

    return _finalize("\n".join(lines))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _status_icon(status: str) -> str:
    return {"ok": "✅", "warning": "⚠️", "critical": "🚨"}.get(status.lower(), "ℹ️")


def _escape(text: str) -> str:
    """Escape HTML special chars for Telegram HTML mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _finalize(text: str) -> str:
    """Ensure the message fits within Telegram's limit."""
    if len(text) <= _MAX_LEN:
        return text
    cut = _MAX_LEN - len(_TRUNCATION_NOTICE)
    return text[:cut] + _TRUNCATION_NOTICE

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _status_icon(status: str) -> str:
    return {"ok": "✅", "warning": "⚠️", "critical": "🚨"}.get(status.lower(), "ℹ️")


def _escape(text: str) -> str:
    """Escape HTML special chars for Telegram HTML mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _finalize(text: str) -> str:
    """Ensure the message fits within Telegram's limit."""
    if len(text) <= _MAX_LEN:
        return text
    cut = _MAX_LEN - len(_TRUNCATION_NOTICE)
    return text[:cut] + _TRUNCATION_NOTICE
