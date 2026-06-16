#!/usr/bin/env python3
"""Daily report — runs at 02:00 UTC via cron.

Every execution:
  1. Generates the markdown report
  2. Writes to reports/history/YYYY-MM-DD/daily_report.md
  3. Git commits + pushes (mandatory)
  4. Sends Telegram operator summary (mandatory)
  5. Persists delivery state

Report sections (operator-first order):
  1. What changed (VPS drift)
  2. New risks (security findings, new unscanned services)
  3. System health (pipeline failures)
  4. Coverage gaps (unscanned services)
  5. New recommendations
  6. Pipeline status + delivery integrity

Cron: 0 2 * * *
"""

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

LOG_FILE = "/var/log/ai-quartermaster-daily.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("daily_report")


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _days_since(iso_ts: str) -> int:
    """Return days elapsed since an ISO timestamp string, or 0 on parse error."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        return max(0, (datetime.now(UTC) - dt).days)
    except Exception:
        return 0


def _scan_incident_reports(max_days: int = 2) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Cross-reference the committed incident reports (system of record).

    Returns (listed, index):
      - listed: [(date, repo_relative_path)] for the most recent `max_days` of
        incident reports, newest first — for the report's Incident Reports index.
      - index: {incident_slug: repo_relative_path} over ALL dated dirs (newest
        wins) — for inline linking of any rendered finding to its report.

    Deterministic, read-only: just lists files under reports/incidents/.
    """
    base = PROJECT_ROOT / "reports" / "incidents"
    listed: list[tuple[str, str]] = []
    index: dict[str, str] = {}
    if not base.exists():
        return listed, index
    day_dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    recent = {d.name for d in day_dirs[:max_days]}
    skip = {"index.md", "open_incidents.md"}
    for day_dir in day_dirs:
        for md in sorted(day_dir.glob("*.md")):
            if md.name in skip:
                continue
            rel = f"reports/incidents/{day_dir.name}/{md.name}"
            index.setdefault(md.stem, rel)
            if day_dir.name in recent:
                listed.append((day_dir.name, rel))
    return listed, index


def _incidents_created_today(day: str) -> list[tuple[str, str, str]]:
    """Return [(severity, title, relpath)] for incident reports filed on `day`.

    Reads each report's metadata header (system of record) so the daily report
    reflects exactly what was committed. Deterministic, read-only.
    """
    from reports.incident_report import parse_incident_metadata

    out: list[tuple[str, str, str]] = []
    day_dir = PROJECT_ROOT / "reports" / "incidents" / day
    if not day_dir.exists():
        return out
    for md in sorted(day_dir.glob("*.md")):
        if md.name in ("index.md", "open_incidents.md"):
            continue
        rel = f"reports/incidents/{day}/{md.name}"
        try:
            meta = parse_incident_metadata(md.read_text(encoding="utf-8"))
        except OSError:
            meta = {}
        out.append((meta.get("severity", ""), meta.get("title", md.stem), rel))
    _rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "": 4}
    out.sort(key=lambda r: _rank.get((r[0] or "").upper(), 4))
    return out


def _day_so_what(created_today: list[tuple[str, str, str]]) -> str:
    """One-line day-level SO WHAT derived from today's incidents (deterministic)."""
    if not created_today:
        return "No incidents required a report today — no P0/P1 operational events filed."
    sev_counts: dict[str, int] = {}
    for sev, _t, _r in created_today:
        sev_counts[(sev or "").upper()] = sev_counts.get((sev or "").upper(), 0) + 1
    top_sev, top_title, _ = created_today[0]
    urgent = sev_counts.get("CRITICAL", 0) + sev_counts.get("HIGH", 0)
    if urgent:
        return (f"{len(created_today)} incident(s) filed today, {urgent} at HIGH/CRITICAL — "
                f"highest: [{top_sev}] {top_title}. Review the incident reports below.")
    return (f"{len(created_today)} incident(s) filed today (none HIGH/CRITICAL) — "
            f"awareness items; see the reports below.")


def _persistence_label(occurrence_count: int, first_seen: str = "", density: float = 0.0) -> str:
    """Return human label for occurrence recurrence state.

    When density >= 1.0/day, appends frequency annotation to signal acceleration.
    """
    if occurrence_count <= 1:
        return "New"
    days = _days_since(first_seen) if first_seen else 0
    if days > 0:
        label = f"Persisting ({occurrence_count}×, {days}d)"
    else:
        label = f"Persisting ({occurrence_count}×)"
    if density >= 1.0:
        label += f" | {density:.1f}/day"
    return label


def _get_selfmonitor_failures() -> list[str]:
    """Inline pipeline health checks — same logic as selfmonitor.py."""
    failures = []
    try:
        import sqlite3
        from datetime import timedelta

        scan_log = Path("/var/log/ai-quartermaster-scan.log")
        if not scan_log.exists():
            failures.append("Scan log missing — pipeline may never have run")
        else:
            age = (datetime.now(UTC) - datetime.fromtimestamp(
                scan_log.stat().st_mtime, tz=UTC
            )).total_seconds() / 3600
            if age > 8:
                failures.append(f"Scan log is {age:.1f}h old — scheduled scan may be failing")

        db_path = PROJECT_ROOT / "data" / "operational_memory.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cutoff = (datetime.now(UTC) - timedelta(hours=26)).strftime("%Y-%m-%d %H:%M:%S")
            row = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE created_at > ?", (cutoff,)
            ).fetchone()
            conn.close()
            if row and row[0] == 0:
                failures.append("No new snapshots in the last 26h — scan pipeline stuck")
    except Exception as exc:
        failures.append(f"Self-monitor check error: {exc}")
    return failures


# Short, deterministic impact statements for intrinsically critical finding types,
# used to frame the calm "Needs Attention" lead in consequence terms (the impact OF
# the finding, not telemetry). Owner-facing findings carry their own graph-derived
# consequence; this map only covers the intrinsic (security / OOM / money) classes.
_INTRINSIC_IMPACT: dict[str, str] = {
    "kernel_oom_kill": "memory pressure killed a process — in-flight work lost, service may be degraded",
    "port_exposed_publicly": "a service is reachable from the public internet",
    "credential_in_unit_file": "a credential is exposed in a unit/config file",
    "world_readable_env_file": "a secrets file is world-readable",
    "dependency_unreachable": "a core dependency is unreachable — dependents may be failing",
    "spend_spike": "cost is materially above baseline and compounds daily",
    "economic_anomaly": "a new/unexpected spender means cost is no longer fully attributable",
    "runaway_agent_cost": "unattended spend keeps accruing until the workflow is capped",
    "abnormal_burn_rate": "spend is accruing faster than expected",
    "unknown_cost_owner": "paid consumption with no accountable owner — cost cannot be governed",
    "agent_cost": "an agent's cost is no longer negligible",
}

_ATTN_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "": 4}


def _normalize_security_finding(s: dict) -> dict:
    """Map a VPS-scan security dict (severity 'high', key 'type'/'unit'/'path') into the
    finding shape the push policy + consequence mapper expect. Read-only, no mutation."""
    return {
        "finding_type": s.get("finding_type") or s.get("type", "security"),
        "target_id": "vps",
        "resource": s.get("unit") or s.get("path") or s.get("resource", ""),
        "collector_type": "security_scanner",
        "severity": (s.get("severity") or "").upper(),
        "title": s.get("recommendation") or s.get("title") or s.get("type", "security finding"),
    }


def _attention_rows(all_findings: list, security_high: list | None = None,
                    graph_store=None) -> list[tuple]:
    """The calm decision lead: findings that genuinely need attention, in consequence terms.

    A finding qualifies when it would earn a real-time push under the push policy AND
    it is genuinely urgent — either:
      * intrinsically critical (security / OOM / money / dependency), or
      * it takes an owner-facing capability with it (consequence walk), or
      * its effective severity is HIGH or CRITICAL.
    Impact-free activity and the tool's own dev/git churn are excluded by the policy
    (verdict.push is False). HIGH security findings from the VPS scan are folded in so
    the lead is honest — it never says "nothing" while a HIGH risk sits below.

    Returns [(rank, effective_severity, headline, impact_line, check_step)] sorted
    most-urgent first; check_step is the first diagnostic step from the check
    playbook ("" when the finding_type has no rule).
    Deterministic; never raises (consequence-framing failures degrade to intrinsic text).
    """
    from cognition.push_policy import evaluate as _eval_push

    get_framing = None
    get_checks = None
    if graph_store is not None:
        try:
            from cognition.consequence_mapper import get_consequence_framing as get_framing
        except Exception:
            get_framing = None
        try:
            from cognition.check_mapper import get_check_steps as get_checks
        except Exception:
            get_checks = None

    candidates = list(all_findings) + [_normalize_security_finding(s) for s in (security_high or [])]

    rows: list[tuple] = []
    seen: set[tuple] = set()
    for f in candidates:
        framing = None
        if get_framing is not None:
            try:
                framing = get_framing(f, graph_store)
            except Exception:
                framing = None
        verdict = _eval_push(f, framing)
        if not verdict.push:
            continue  # silenced by policy (impact-free activity / self dev churn)
        sev = (f.get("severity") or "").upper()
        if framing and framing.get("escalated"):
            sev = (framing.get("consequence_severity") or sev).upper()
        urgent = verdict.reason in ("intrinsic", "owner_facing_consequence") \
            or sev in ("HIGH", "CRITICAL")
        if not urgent:
            continue
        headline = f.get("title") or f.get("finding_type", "?")
        if verdict.reason == "owner_facing_consequence" and framing:
            impacts = framing.get("owner_impact_lines") or []
            impact = impacts[0] if impacts else f"{framing.get('mapped_node_label', '')} loses an owner-facing capability"
        else:
            impact = _INTRINSIC_IMPACT.get(f.get("finding_type", ""),
                                           "high-severity operational finding")
        key = (sev, headline, impact)
        if key in seen:
            continue
        seen.add(key)
        # 🔍 first diagnostic step (advisory), if the playbook has a rule for this type.
        check = ""
        if get_checks is not None:
            try:
                cs = get_checks(f, graph_store)
                if cs and cs.get("steps"):
                    check = cs["steps"][0]["check"]
            except Exception:
                check = ""
        rows.append((_ATTN_RANK.get(sev, 4), sev or "—", headline, impact, check))
    rows.sort(key=lambda r: (r[0], r[2]))
    return rows


def _build_report(
    generated_at: str,
    snapshot_count: int,
    scan_snapshots: list,
    vps_snap: dict,
    delivery_state: dict,
    surv_findings: list | None = None,
    project_findings: list | None = None,
    economic_findings: list | None = None,
    agent_findings: list | None = None,
    spend_summary: dict | None = None,
    graph_store=None,
) -> tuple[str, dict]:
    """Build markdown report. Returns (markdown_content, structured_data_for_telegram)."""
    vps_data = vps_snap.get("data", {}) if vps_snap else {}
    vps_drift = vps_data.get("drift", {})
    security = vps_data.get("security", {})
    unscanned = vps_data.get("unscanned_services", [])

    selfmonitor_failures = _get_selfmonitor_failures()

    # Aggregate scan-level stats
    targets: set[str] = set()
    total_recs = 0
    providers: set[str] = set()
    surfaced_recs: list[tuple[str, int, str]] = []  # (title, recurrence_count, relevance)

    for snap in scan_snapshots:
        data = snap.get("data", {}) if isinstance(snap, dict) else {}
        t = data.get("target", "")
        if t:
            targets.add(t)
        recs = data.get("recommendations", [])
        total_recs += len(recs)
        for r in recs[:2]:
            text = r.get("title") or r.get("message") or str(r)
            count = r.get("recurrence_count", 0)
            relevance = r.get("relevance", "informational")
            if text and not any(sr[0] == text for sr in surfaced_recs):
                surfaced_recs.append((text, count, relevance))
        for det in data.get("llm_detections", []):
            p = det.get("provider")
            if p:
                providers.add(p)

    drift_events = vps_drift.get("human_readable", [])  # operational only after classification
    drift_changes = vps_drift.get("changes", [])
    drift_telemetry_count = vps_drift.get("telemetry_count", 0)
    high_sec = [f for f in security.get("findings", []) if f.get("severity") == "high"]
    med_sec = [f for f in security.get("findings", []) if f.get("severity") == "medium"]
    new_unscanned_events = [e for e in drift_changes if e.get("type") == "NEW_UNSCANNED_SERVICE"]

    # Survivability findings from FindingStore (active, scoped to vps/survivability_scanner)
    _surv = surv_findings or []
    crit_surv = [f for f in _surv if f.get("severity") == "CRITICAL"]
    high_surv = [f for f in _surv if f.get("severity") == "HIGH"]
    med_surv = [f for f in _surv if f.get("severity") == "MEDIUM"]

    # Delivery state display
    last_git = delivery_state.get("last_git_push_success", "never")
    last_tg = delivery_state.get("last_telegram_success", "never")
    git_fails = delivery_state.get("git_failures_since_success", 0)
    tg_fails = delivery_state.get("telegram_failures_since_success", 0)

    lines = [
        "# Daily Operational Report",
        f"Generated: {generated_at}",
        "",
    ]

    _all_activity = (surv_findings or []) + (project_findings or []) \
        + (economic_findings or []) + (agent_findings or [])

    # 0. Needs Attention — the calm decision lead. What (if anything) actually needs
    #    the operator, framed in consequence terms (owner-facing impact or intrinsic
    #    criticality). Impact-free activity and the tool's own dev churn never appear
    #    here — they live in the quiet sections below. Silence is the default.
    attention = _attention_rows(_all_activity, security_high=high_sec, graph_store=graph_store)
    lines.append("## Needs Attention")
    lines.append("")
    if attention:
        for _rank, sev, headline, impact, *rest in attention:
            lines.append(f"- **[{sev}]** {headline}")
            lines.append(f"  ↳ {impact}")
            check = rest[0] if rest else ""
            if check:
                lines.append(f"  🔍 {check}")
    else:
        lines.append("_Nothing needs your attention. No owner-facing consequence or "
                     "critical finding in the last 24h._")
    lines.append("")

    # Operational context (4W) — secondary; answers WHAT/WHERE/WHEN/WHICH. Demoted
    # below the decision lead (context, not headline) and with the tool's own dev/git
    # churn filtered out, so the context describes the fleet, not quartermaster watching itself.
    from cognition.four_w import summarize_4w
    from cognition.push_policy import is_self_dev_activity as _is_self_dev_ctx
    s4w = summarize_4w([f for f in _all_activity if not _is_self_dev_ctx(f)])
    lines.append("## Operational Context (4W)")
    lines.append("")
    if _all_activity:
        lines.append(f"- **WHAT:** {', '.join(s4w['what']) or '—'}")
        where_bits = []
        if s4w["where_repos"]:
            where_bits.append("repos: " + ", ".join(s4w["where_repos"]))
        if s4w["where_subsystems"]:
            where_bits.append("subsystems: " + ", ".join(s4w["where_subsystems"]))
        if s4w["where_services"]:
            where_bits.append("services: " + ", ".join(s4w["where_services"][:6]))
        lines.append(f"- **WHERE:** {' · '.join(where_bits) or '—'}")
        when_v = "—"
        if s4w["when_earliest"] and s4w["when_latest"]:
            when_v = f"{s4w['when_earliest']} → {s4w['when_latest']} UTC"
        lines.append(f"- **WHEN:** {when_v}")
        which_bits = []
        if s4w["which_agents"]:
            which_bits.append("agents: " + ", ".join(s4w["which_agents"]))
        if s4w["which_providers"]:
            which_bits.append("providers: " + ", ".join(s4w["which_providers"]))
        if s4w["which_models"]:
            which_bits.append("models: " + ", ".join(s4w["which_models"]))
        lines.append(f"- **WHICH:** {' · '.join(which_bits) or '—'}")
    else:
        lines.append("_No 4W activity recorded in the window._")
    lines.append("")

    # 1. What changed
    lines.append("## 1. What Changed")
    lines.append("")
    if drift_events:
        for item in drift_events:
            lines.append(f"- {item}")
        if drift_telemetry_count:
            lines.append(
                f"  _({drift_telemetry_count} ephemeral localhost port event(s) "
                f"classified as telemetry-only and not shown)_"
            )
    elif drift_telemetry_count:
        lines.append(
            f"_No operational drift. "
            f"{drift_telemetry_count} ephemeral port event(s) logged as telemetry-only._"
        )
    else:
        summary = vps_drift.get("summary", "")
        if summary:
            lines.append(f"_{summary}_")
        else:
            lines.append("_No VPS snapshot available yet — will appear after next scan cycle._")
    lines.append("")

    # 2. Risks (actionable tier: critical/high survivability, high security, new unscanned)
    lines.append("## 2. Risks")
    lines.append("")
    has_actionable = bool(crit_surv or high_surv or high_sec or new_unscanned_events)
    has_informational = bool(med_surv or med_sec)
    has_risks = has_actionable or has_informational

    from memory.finding_store import (
        ACTIONABILITY_MAP as _ACTIONABILITY_MAP,
    )
    from memory.finding_store import (
        operator_posture as _operator_posture,
    )
    from memory.finding_store import (
        persistence_density as _persistence_density,
    )
    from memory.finding_store import (
        trend_label as _trend_label,
    )

    def _surv_label(f: dict) -> str:
        count = f.get("occurrence_count", 1)
        first = f.get("first_seen", "")
        last = f.get("last_seen", "")
        d = _persistence_density(count, first, last) if count > 1 else 0.0
        return _persistence_label(count, first, d)

    def _surv_trend_suffix(f: dict) -> str:
        count = f.get("occurrence_count", 1)
        if count <= 1:
            return ""
        first = f.get("first_seen", "")
        last = f.get("last_seen", "")
        d = _persistence_density(count, first, last)
        tl = _trend_label(count, d)
        return f" [{tl}]"

    def _fmt_evidence(evidence: list) -> str:
        skip_words = ("none", "unknown", "n/a")
        useful = [e for e in evidence if not any(w in e.lower() for w in skip_words)]
        shown = useful[:2] if useful else evidence[:1]
        return " · ".join(shown) if shown else ""

    if crit_surv:
        lines.append("**Survivability — Critical**")
        for f in crit_surv:
            label = _surv_label(f)
            trend_sfx = _surv_trend_suffix(f)
            posture = _operator_posture(f)
            lines.append(f"- [{label} | {posture}]{trend_sfx} `{f.get('resource', '?')}`: {f.get('recommendation', f.get('title', ''))}")
            ev = _fmt_evidence(f.get("evidence", []))
            if ev:
                lines.append(f"  ↳ Evidence: {ev}")
        lines.append("")
    if high_surv:
        lines.append("**Survivability — High**")
        for f in high_surv:
            label = _surv_label(f)
            trend_sfx = _surv_trend_suffix(f)
            posture = _operator_posture(f)
            lines.append(f"- [{label} | {posture}]{trend_sfx} `{f.get('resource', '?')}`: {f.get('recommendation', f.get('title', ''))}")
            ev = _fmt_evidence(f.get("evidence", []))
            if ev:
                lines.append(f"  ↳ Evidence: {ev}")
        lines.append("")
    if high_sec:
        lines.append("**Security — High**")
        for f in high_sec:
            label = _persistence_label(f.get("occurrence_count", 1), f.get("first_seen", ""))
            posture = _operator_posture(f)
            lines.append(f"- [{label} | {posture}] `{f.get('unit', f.get('path', '?'))}`: {f.get('recommendation', '')}")
            ftype = f.get("finding_type", f.get("type", ""))
            if ftype == "credential_in_unit_file":
                patterns = f.get("patterns_found", [])
                pattern_str = patterns[0] if patterns else "credential pattern matched"
                user = f.get("service_user", "root")
                lines.append(f"  ↳ Evidence: Pattern: `{pattern_str}` · Service user: {user}")
            elif ftype == "port_exposed_publicly":
                lines.append(f"  ↳ Evidence: Port {f.get('port', '?')} bound to 0.0.0.0 · Process: {f.get('process', '?')}")
        lines.append("")
    if new_unscanned_events:
        lines.append("**New services without scan coverage**")
        for e in new_unscanned_events:
            lines.append(f"- `{e['value']}` — appeared since last snapshot, not in scan targets")
        lines.append("")

    # Informational tier: medium severity findings (lower urgency, useful context)
    # Actionability is shown here because severity MEDIUM doesn't tell full story
    # (e.g., monitor_stale is MEDIUM severity but HIGH actionability).
    if med_surv:
        lines.append("**Informational — Survivability**")
        for f in med_surv:
            label = _surv_label(f)
            ftype = f.get("finding_type", "")
            actionability = _ACTIONABILITY_MAP.get(ftype, "medium")
            trend_sfx = _surv_trend_suffix(f)
            lines.append(
                f"- [{label} | {actionability}-actionability]{trend_sfx} "
                f"`{f.get('resource', '?')}`: {f.get('recommendation', f.get('title', ''))}"
            )
        lines.append("")
    if med_sec:
        lines.append("**Informational — Security**")
        for f in med_sec:
            label = _persistence_label(f.get("occurrence_count", 1), f.get("first_seen", ""))
            ftype = f.get("type", "")
            if ftype == "port_exposed_publicly":
                lines.append(f"- [{label}] Port {f.get('port')} ({f.get('process', '?')}): {f.get('recommendation', '')}")
            elif ftype == "world_readable_env_file":
                lines.append(f"- [{label}] `{f.get('path', '?')}`: {f.get('recommendation', '')}")
            else:
                lines.append(f"- [{label}] {f.get('recommendation', f.get('type', ''))}")
        lines.append("")

    if not has_risks:
        lines.append("_No risks detected._")
        lines.append("")

    # ---- Activity domains (economic / project / agent) ----
    # Break the self-feedback loop: the tool's OWN dev/git activity (quartermaster committing
    # reports, code about itself) is not an operational event — drop it from the
    # activity sections. Operational health of the tool is still tracked (System Health).
    from cognition.push_policy import is_self_dev_activity as _is_self_dev
    _proj = [f for f in (project_findings or []) if not _is_self_dev(f)]
    _econ = economic_findings or []
    _agent = [f for f in (agent_findings or []) if not _is_self_dev(f)]
    _spend = spend_summary or {}

    def _sev_rank(f: dict) -> int:
        return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(f.get("severity", "LOW"), 3)

    # Incident reports cross-reference (system of record). Built once; used to
    # link rendered findings to their committed incident report, and to populate
    # the dedicated Incident Reports section.
    from reports.incident_report import incident_slug
    incidents_listed, incidents_index = _scan_incident_reports()

    def _incident_link(f: dict) -> str | None:
        try:
            return incidents_index.get(incident_slug(f))
        except Exception:
            return None

    def _render_finding(f: dict, show_posture: bool = True) -> str:
        label = _persistence_label(f.get("occurrence_count", 1), f.get("first_seen", ""))
        posture = _operator_posture(f) if show_posture else ""
        head = f"[{label} | {posture}]" if show_posture else f"[{label}]"
        line = f"- {head} {f.get('title', f.get('finding_type', '?'))}"
        rp = _incident_link(f)
        if rp:
            line += f"\n  ↳ 📄 Incident report: `{rp}`"
        return line

    # 3. Economic activity
    lines.append("## 3. Economic Activity")
    lines.append("")
    if _spend.get("event_count", 0) > 0:
        total = _spend.get("total_cost", 0.0)
        burn = _spend.get("burn_rate_usd_per_hr", 0.0)
        span = _spend.get("active_span_hours", 0.0)
        lines.append(
            f"- Spend (last {_spend.get('window_hours', 24)}h): **${total:,.2f}** "
            f"across {_spend.get('event_count', 0)} call event(s); "
            f"burn ${burn:,.2f}/hr over {span:.1f}h active"
        )
        for p in _spend.get("by_provider", [])[:4]:
            pc = float(p.get("total_estimated_cost") or 0.0)
            lines.append(f"  - {p.get('provider', '?')}: ${pc:,.2f} ({p.get('event_count', 0)} events)")

        # Cost / day, model / day, agent / day (4W: WHICH × WHEN × how much)
        cbd = _spend.get("cost_by_day", [])
        if cbd:
            day_str = " · ".join(
                f"{r.get('day')}: ${float(r.get('total_estimated_cost') or 0):,.2f}" for r in cbd
            )
            lines.append(f"- **Cost / day:** {day_str}")
        bym = _spend.get("by_model", [])
        if bym:
            model_str = " · ".join(
                f"{m.get('model')} (${m.get('total_cost', 0):,.2f})" for m in bym[:5]
            )
            lines.append(f"- **By model:** {model_str}")
        abd = _spend.get("agent_by_day", [])
        if abd:
            agent_str = " · ".join(
                f"{r.get('day')} {r.get('agent') or '?'}: ${float(r.get('total_cost') or 0):,.2f}"
                for r in abd if r.get("agent")
            )
            if agent_str:
                lines.append(f"- **Agent / day:** {agent_str}")

        for f in sorted(_econ, key=_sev_rank):
            lines.append(_render_finding(f))
            ev = _fmt_evidence(f.get("evidence", []))
            if ev and f.get("severity") in ("HIGH", "CRITICAL"):
                lines.append(f"  ↳ Evidence: {ev}")
    elif _econ:
        for f in sorted(_econ, key=_sev_rank):
            lines.append(_render_finding(f))
    else:
        lines.append("_No LLM/API spend observed in the last 24h._")
    lines.append("")

    # 4. Project activity
    lines.append("## 4. Project Activity")
    lines.append("")
    if _proj:
        # group by target_id (repo); lead with burst/rebuild/deploy, then summary
        repos: dict[str, list] = {}
        for f in _proj:
            repos.setdefault(f.get("target_id", "?"), []).append(f)
        for repo in sorted(repos):
            # summary (project_activity) leads, then notable sub-findings by severity
            repo_findings = sorted(
                repos[repo],
                key=lambda f: (0 if f.get("finding_type") == "project_activity" else 1, _sev_rank(f)),
            )
            for f in repo_findings:
                if f.get("finding_type") == "project_activity":
                    lines.append(f"- **{repo}**: {f.get('title', '')}")
                else:
                    lines.append(f"  - [{f.get('severity')}] {f.get('title', '')}")
    else:
        lines.append("_No engineering activity in the last 24h._")
    lines.append("")

    # 5. Agent activity
    lines.append("## 5. Agent Activity")
    lines.append("")
    if _agent:
        agents: dict[str, list] = {}
        for f in _agent:
            agents.setdefault(f.get("target_id", "?"), []).append(f)
        for agent in sorted(agents):
            af = sorted(
                agents[agent],
                key=lambda f: (0 if f.get("finding_type") == "agent_activity" else 1, _sev_rank(f)),
            )
            for f in af:
                if f.get("finding_type") == "agent_activity":
                    lines.append(f"- **{agent}**: {f.get('title', '')}")
                else:
                    posture = _operator_posture(f)
                    lines.append(f"  - [{f.get('severity')} | {posture}] {f.get('title', '')}")
    else:
        lines.append("_No autonomous agent activity in the last 24h._")
    lines.append("")

    # 6. System health
    lines.append("## 6. System Health")
    lines.append("")
    if selfmonitor_failures:
        lines.append("**Pipeline failures:**")
        for f in selfmonitor_failures:
            lines.append(f"- {f}")
    else:
        lines.append("- Scan pipeline: running")
        lines.append("- Daily report: on schedule")
        lines.append("- Snapshot DB: growing")
    lines.append("")

    # 7. Incident reports — links to the committed system-of-record reports for
    #    every P0/P1 event filed under reports/incidents/. Telegram alerts and
    #    this report both point here; the report holds the full 6W/evidence.
    lines.append("## 7. Incident Reports")
    lines.append("")
    _today = datetime.now(UTC).strftime("%Y-%m-%d")
    created_today = _incidents_created_today(_today)

    # Day-level SO WHAT — why the operator should care about today, in one line.
    lines.append(f"**SO WHAT (today):** {_day_so_what(created_today)}")
    lines.append("")

    # Incident Reports Created Today — the day's permanent operational memory.
    lines.append("**Incident Reports Created Today:**")
    if created_today:
        for sev, title, rp in created_today:
            name = rp.rsplit("/", 1)[-1].removesuffix(".md")
            lines.append(f"- [{sev or '—'}] [{title or name}]({rp})")
    else:
        lines.append("- _None — no P0/P1 events required an incident report today._")
    lines.append("")

    # Navigation: full index + open incidents, so an operator can reach every
    # relevant incident report directly (V4 report-loading model).
    lines.append(
        "**Navigate:** [full incident index](reports/incidents/index.md) · "
        "[open incidents](reports/incidents/open_incidents.md)"
    )
    lines.append("")

    # Recent incident reports (cross-reference window) — system of record holding
    # full PROJECT CONTEXT / 6W / WHY / SO WHAT / WHICH LLMS / CORRELATION.
    if incidents_listed:
        lines.append(f"Recent incident reports (most recent {2} day(s)):")
        for day, rp in incidents_listed:
            name = rp.rsplit("/", 1)[-1].removesuffix(".md")
            lines.append(f"- `{day}` — [{name}]({rp})")
    lines.append("")

    # 8. Coverage gaps
    lines.append("## 8. Coverage Gaps")
    lines.append("")
    if unscanned:
        lines.append(f"{len(unscanned)} service(s) without scan coverage:")
        for svc in sorted(unscanned):
            lines.append(f"- `{svc}`")
    else:
        lines.append("_No coverage gaps detected._")
    lines.append("")

    # 8. Recommendations — every recommendation derives from 4W context
    #    (Observed 4W → Evidence → Recommendation → Expected impact). No 4W, no rec.
    from cognition.four_w import format_recommendation_markdown

    lines.append("## 9. Recommendations")
    lines.append("")

    rec_findings: list[dict] = []
    # Economic HIGH/CRITICAL — richest 4W
    rec_findings += [f for f in _econ if f.get("severity") in ("HIGH", "CRITICAL")]
    # Survivability — actionable posture with a recommendation
    rec_findings += [
        f for f in _surv
        if _operator_posture(f) in ("immediate_attention", "investigate") and f.get("recommendation")
    ]
    # Security HIGH (vps scan dicts) — normalise so build_4w / get_4w works
    for s in high_sec:
        rec_findings.append({
            "finding_type": s.get("finding_type") or s.get("type", "security"),
            "target_id": "vps",
            "resource": s.get("unit") or s.get("path") or s.get("resource", ""),
            "collector_type": "security_scanner",
            "severity": "HIGH",
            "title": s.get("recommendation", ""),
            "recommendation": s.get("recommendation", ""),
            "evidence": [s.get("unit") or s.get("path") or ""],
        })

    # Deterministic order: severity, then finding_type
    rec_findings.sort(key=lambda f: (_sev_rank(f), f.get("finding_type", "")))

    if rec_findings:
        for i, f in enumerate(rec_findings[:6], 1):
            lines.append(f"### R{i}. {f.get('title') or f.get('finding_type')}")
            lines.extend(format_recommendation_markdown(f))
            lines.append("")
    else:
        lines.append("_No 4W-derived recommendations this cycle._")
        lines.append("")

    # 10. Pipeline status + delivery integrity
    lines.append("## 10. Pipeline Status")
    lines.append("")
    lines += [
        f"- Scans completed (24h): {len(scan_snapshots)}",
        f"- Targets active: {len(targets)}",
        f"- Total snapshots: {snapshot_count}",
        f"- LLM providers seen: {', '.join(sorted(providers)) or 'none'}",
    ]
    if vps_data:
        lines += [
            f"- VPS services tracked: {len(vps_data.get('service_names', []))}",
            f"- VPS ports tracked: {len(vps_data.get('port_set', []))}",
            f"- Docker containers: {len(vps_data.get('container_names', []))}",
        ]
    lines.append("")
    lines.append("**Delivery integrity:**")
    lines.append(f"- Last git push: {last_git}{' (' + str(git_fails) + ' failures since)' if git_fails else ''}")
    lines.append(f"- Last Telegram: {last_tg}{' (' + str(tg_fails) + ' failures since)' if tg_fails else ''}")
    lines.append(f"- Report generated: {generated_at}")
    lines += [
        "",
        "---",
        "",
        "*Advisory only — operational decisions require human review.*",
    ]

    # Calibration metadata: per-finding density/trend/actionability for review purposes.
    # These are computed values, not stored in DB — used for calibration analysis.
    calibration_metadata = []
    for f in _surv:
        count = f.get("occurrence_count", 1)
        first = f.get("first_seen", "")
        last = f.get("last_seen", "")
        d = _persistence_density(count, first, last) if count > 1 else 0.0
        ftype = f.get("finding_type", "")
        calibration_metadata.append({
            "finding_type": ftype,
            "resource": f.get("resource", ""),
            "severity": f.get("severity", ""),
            "occurrence_count": count,
            "persistence_density": d,
            "trend": _trend_label(count, d),
            "operational_relevance": "actionable",   # all survivability findings
            "actionability": _ACTIONABILITY_MAP.get(ftype, "medium"),
            "operator_posture": _operator_posture(f),
        })

    # Structured data for Telegram summary builder
    structured = {
        "drift_events": drift_events,
        "security_high": [f.get("unit", f.get("path", "?")) for f in high_sec],
        "security_medium_count": len(med_sec),
        "health_failures": selfmonitor_failures,
        "unscanned_services": unscanned,
        "new_recs": [title for title, _, _r in surfaced_recs[:3]],
        "scan_count": len(scan_snapshots),
        "target_count": len(targets),
        "snapshot_count": snapshot_count,
        "survivability_critical": len(crit_surv),
        "survivability_high": len(high_surv),
        "calibration_metadata": calibration_metadata,
    }

    return "\n".join(lines), structured


def main():
    generated_at = datetime.now(UTC).isoformat()
    ts = datetime.now(UTC)
    log.info("=== Daily report starting — %s ===", generated_at)

    _load_env()

    surv_findings: list = []
    graph_store = None
    try:
        from memory.finding_store import FindingStore
        from memory.store import OperationalStore

        db_path = PROJECT_ROOT / "data" / "operational_memory.db"
        store = OperationalStore(str(db_path))
        store.connect()

        # Graph store powers the consequence-framed "Needs Attention" lead. Best-effort:
        # if it can't connect, the lead degrades to intrinsic-only framing (no crash).
        try:
            from memory.graph_store import GraphStore
            graph_store = GraphStore(str(db_path))
            graph_store.connect()
        except Exception as _gexc:
            log.warning("Graph store unavailable for consequence framing: %s", _gexc)
            graph_store = None

        scan_snapshots = store.get_snapshots_in_window("full_scan", days=1, max_count=200)
        vps_snap = store.get_latest_snapshot("vps_state")
        snapshot_count = store.count_snapshots()

        finding_store = FindingStore(str(db_path))
        finding_store.connect()
        surv_findings = finding_store.get_active_findings(
            target_id="vps", collector_type="survivability_scanner"
        )
        project_findings = finding_store.get_active_findings(
            collector_type="git_activity_scanner"
        )
        economic_findings = finding_store.get_active_findings(
            collector_type="economic_observability"
        )
        agent_findings = finding_store.get_active_findings(
            collector_type="agent_observability"
        )
        econ_snap = store.get_latest_snapshot("economic_state")
        spend_summary = econ_snap.get("data", {}) if econ_snap else {}

        log.info(
            "Loaded %d scan snapshots, VPS: %s, total: %d, surv: %d, project: %d, economic: %d, agent: %d",
            len(scan_snapshots),
            "present" if vps_snap else "absent",
            snapshot_count,
            len(surv_findings),
            len(project_findings),
            len(economic_findings),
            len(agent_findings),
        )
    except Exception as exc:
        log.error("Failed to load data: %s", exc, exc_info=True)
        scan_snapshots = []
        vps_snap = {}
        snapshot_count = 0
        project_findings = []
        economic_findings = []
        agent_findings = []
        spend_summary = {}

    from delivery.formatting import format_operational_summary
    from delivery.pipeline import deliver, get_delivery_state

    delivery_state = get_delivery_state()

    report_content, structured = _build_report(
        generated_at, snapshot_count, scan_snapshots, vps_snap, delivery_state,
        surv_findings=surv_findings,
        project_findings=project_findings,
        economic_findings=economic_findings,
        agent_findings=agent_findings,
        spend_summary=spend_summary,
        graph_store=graph_store,
    )

    tg_summary = format_operational_summary(
        report_type="daily",
        timestamp=ts.strftime("%Y-%m-%d %H:%M UTC"),
        drift_events=structured["drift_events"],
        security_high=structured["security_high"],
        security_medium_count=structured["security_medium_count"],
        health_failures=structured["health_failures"],
        unscanned_services=structured["unscanned_services"],
        new_recs=structured["new_recs"],
        scan_count=structured["scan_count"],
        target_count=structured["target_count"],
        snapshot_count=structured["snapshot_count"],
        delivery_state=delivery_state,
    )

    result = deliver(
        report_type="daily",
        content=report_content,
        summary=tg_summary,
        timestamp=ts,
    )

    log.info(
        "=== Daily report complete — git=%s telegram=%s ===",
        "ok" if result.git_ok else "FAIL",
        "ok" if result.telegram_ok else "FAIL",
    )

    if not result.fully_delivered:
        log.warning(
            "Delivery incomplete — git_error=%s telegram_error=%s",
            result.git_error,
            result.telegram_error,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
