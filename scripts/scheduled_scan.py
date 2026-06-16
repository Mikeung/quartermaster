#!/usr/bin/env python3
"""Scheduled scan — runs every 6 hours via cron.

Scans all configured VPS targets, stores snapshots, logs results.
Also collects a VPS-level state snapshot for real infrastructure drift detection.

Cron: 0 0,6,12,18 * * *
"""

import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Log destination is configurable and degrades gracefully: a tester without
# write access to /var/log falls back to a repo-local path rather than crashing.
LOG_FILE = os.environ.get("QM_LOG_FILE", "/var/log/ai-quartermaster-scan.log")
try:
    _file_handler = logging.FileHandler(LOG_FILE)
except OSError:
    _fallback = PROJECT_ROOT / "data" / "logs" / "scan.log"
    _fallback.parent.mkdir(parents=True, exist_ok=True)
    _file_handler = logging.FileHandler(str(_fallback))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[_file_handler, logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scheduled_scan")

# Default scan targets. Override with QM_SCAN_TARGETS (comma-separated absolute
# paths); when unset, fall back to this list. A fresh checkout with no env set
# should edit this or set the env var to point at its own projects.
_DEFAULT_SCAN_TARGETS = ["."]
_env_targets = os.environ.get("QM_SCAN_TARGETS", "").strip()
SCAN_TARGETS = (
    [p.strip() for p in _env_targets.split(",") if p.strip()]
    if _env_targets else _DEFAULT_SCAN_TARGETS
)


def build_dependencies():
    from memory.drift_detector import DriftDetector
    from memory.finding_store import FindingStore
    from memory.graph_store import GraphStore
    from memory.snapshot_engine import SnapshotEngine
    from memory.store import OperationalStore
    from reports.generator import ReportGenerator
    from scanners.process_scanner import ProcessScanner
    from scanners.registry import ScannerRegistry
    from scanners.repo_scanner import RepoScanner
    from scanners.runtime_scanner import RuntimeScanner
    from scanners.service_scanner import ServiceScanner

    db_path = str(PROJECT_ROOT / "data" / "operational_memory.db")
    store = OperationalStore(db_path)
    store.connect()
    snapshot_engine = SnapshotEngine(store)
    drift_detector = DriftDetector()
    report_generator = ReportGenerator(output_dir=str(PROJECT_ROOT / "data" / "reports"))
    finding_store = FindingStore(db_path)
    finding_store.connect()
    graph_store = GraphStore(db_path)
    graph_store.connect()

    registry = ScannerRegistry()
    registry.register(RepoScanner())
    registry.register(ProcessScanner())
    registry.register(ServiceScanner())
    registry.register(RuntimeScanner())

    return registry, snapshot_engine, drift_detector, report_generator, finding_store, graph_store


def _persist_security_findings(finding_store, findings: list) -> None:
    """Upsert VPS security findings into FindingStore; enriches each dict with occurrence_count."""
    from memory.finding_store import compute_finding_id
    active_ids: set[str] = set()
    for f in findings:
        fid = compute_finding_id(
            target_id="vps",
            finding_type=f.get("finding_type", f.get("type", "unknown")),
            resource=f.get("resource", ""),
            scope=f.get("scope", "host"),
            collector_type=f.get("collector_type", "security_scanner"),
        )
        row = finding_store.upsert(
            finding_id=fid,
            target_id="vps",
            finding_type=f.get("finding_type", f.get("type", "unknown")),
            resource=f.get("resource", ""),
            scope=f.get("scope", "host"),
            severity=f.get("severity", "medium").upper(),
            collector_type=f.get("collector_type", "security_scanner"),
            title=f.get("recommendation", f.get("type", "")),
            recommendation=f.get("recommendation", ""),
            evidence=[f.get("unit", f.get("path", f.get("resource", "")))],
            confidence=1.0,
        )
        f["finding_id"] = fid
        f["occurrence_count"] = row["occurrence_count"]
        f["first_seen"] = row["first_seen"]
        active_ids.add(fid)
    finding_store.mark_resolved(active_ids, target_id="vps", collector_type="security_scanner")


def _persist_findings(finding_store, findings: list, reconcile_scopes: set) -> None:
    """Upsert observability findings and resolve any that disappeared this cycle.

    Generic counterpart to _persist_security_findings, for the project / agent /
    economic finding flows. `reconcile_scopes` is the set of (target_id,
    collector_type) pairs that COULD have findings — every one is reconciled
    (mark_resolved) even if it produced nothing this cycle, so a repo that goes
    quiet has its activity findings correctly closed out.
    """
    from collections import defaultdict

    from memory.finding_store import compute_finding_id

    active: dict[tuple, set] = defaultdict(set)
    for f in findings:
        fid = compute_finding_id(
            target_id=f["target_id"], finding_type=f["finding_type"],
            resource=f["resource"], scope=f["scope"], collector_type=f["collector_type"],
        )
        row = finding_store.upsert(
            finding_id=fid,
            target_id=f["target_id"], finding_type=f["finding_type"],
            resource=f["resource"], scope=f["scope"],
            severity=f["severity"].upper(), collector_type=f["collector_type"],
            title=f["title"], description=f.get("description", ""),
            recommendation=f.get("recommendation", ""),
            evidence=f.get("evidence", []), confidence=f.get("confidence", 1.0),
            four_w=f.get("four_w"),
        )
        f["finding_id"] = fid
        f["occurrence_count"] = row["occurrence_count"]
        f["first_seen"] = row["first_seen"]
        f["last_seen"] = row["last_seen"]
        active[(f["target_id"], f["collector_type"])].add(fid)

    for scope in reconcile_scopes | set(active.keys()):
        tid, ctype = scope
        finding_store.mark_resolved(active.get(scope, set()), target_id=tid, collector_type=ctype)


def run_activity_observability(snapshot_engine, finding_store) -> dict:
    """Economic + project + agent observability over the detection window.

    Collects git activity (Phase B), imports + analyses spend (Phase A), and
    attributes activity/cost to agents (Phase C). Persists findings and writes
    append-only state snapshots. Read-only and advisory: never mutates any repo,
    provider account, or agent.
    """
    from cognition.project_activity import analyze_project_activity
    from config import observability_config as cfg
    from memory.llm_store import LLMEventStore
    from observability.agent_activity import analyze_agent_activity
    from observability.economic import detect_economic_findings, summarize_spend
    from scanners.git_activity_scanner import collect_all_git_activity
    from scripts.import_spend import import_spend

    summary = {"project_findings": 0, "economic_findings": 0, "agent_findings": 0}
    try:
        win = cfg.WINDOW_HOURS

        # Phase B — git activity (live, deterministic)
        git_activity = collect_all_git_activity(SCAN_TARGETS, window_hours=win)
        project_findings = analyze_project_activity(git_activity)
        snapshot_engine.create_snapshot(
            {"window_hours": win, "repos": git_activity}, "project_activity_state"
        )

        # Phase A — spend (observe-only ledger import, then detect)
        try:
            import_spend()  # idempotent
        except Exception as exc:
            log.warning("Spend import failed (continuing): %s", exc)
        db_path = str(PROJECT_ROOT / "data" / "operational_memory.db")
        llm_store = LLMEventStore(db_path)
        llm_store.connect()
        economic_findings = detect_economic_findings(llm_store, win)
        spend_summary = summarize_spend(llm_store, win)
        snapshot_engine.create_snapshot(spend_summary, "economic_state")

        # Phase C — agent attribution (git authorship + spend)
        agent_findings = analyze_agent_activity(git_activity, llm_store, win)
        llm_store.disconnect()

        # Reconcile universes so quiet repos/agents get their findings resolved.
        repo_names = {a["repo"] for a in git_activity}
        project_scopes = {(r, "git_activity_scanner") for r in repo_names}
        agent_scopes = {(r, "agent_observability") for r in repo_names}
        agent_scopes |= {(f["target_id"], "agent_observability") for f in agent_findings}
        economic_scopes = {("economic", "economic_observability")}

        _persist_findings(finding_store, project_findings, project_scopes)
        _persist_findings(finding_store, economic_findings, economic_scopes)
        _persist_findings(finding_store, agent_findings, agent_scopes)

        summary = {
            "project_findings": len(project_findings),
            "economic_findings": len(economic_findings),
            "agent_findings": len(agent_findings),
            "active_repos": len(repo_names),
            "window_spend_usd": spend_summary.get("total_cost", 0.0),
        }
        log.info(
            "Activity observability: repos=%d project=%d economic=%d agent=%d spend=$%.2f",
            len(repo_names), len(project_findings), len(economic_findings),
            len(agent_findings), spend_summary.get("total_cost", 0.0),
        )
    except Exception as exc:
        log.error("Activity observability failed: %s", exc, exc_info=True)
    return summary


def run_cost_advisor(finding_store) -> dict:
    """Cost advisor — provider/attribution/budget view + the artifact (opt-in, fail-safe).

    Reuses existing money finding types (unknown_cost_owner / budget_*), so the
    intrinsic-critical ones route through the same real-time push path. Wrapped so
    a failure here can never take down the scan cycle. It never spends.
    """
    summary = {"cost_findings": 0, "unattributed_buckets": 0}
    try:
        from reports.cost_advisor_report import render_cost_advisor_report
        from scripts.cost_advisor_report import build_live

        built = build_live(window_hours=cfg_window())
        advisory = built["advisory"]
        findings = advisory.get("findings", [])

        out = PROJECT_ROOT / "reports" / "economics" / "COST_ADVISOR.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_cost_advisor_report(advisory, built["investigations"]))

        if finding_store is not None and findings:
            _persist_findings(finding_store, findings, {("economic", "cost_advisor")})

        summary["cost_findings"] = len(findings)
        summary["unattributed_buckets"] = len(advisory["attribution"]["unattributed"])
        log.info("Cost advisor: total=$%.2f attributed=$%.2f unattributed=$%.2f findings=%d",
                 advisory["whole_view"]["total_usd"],
                 advisory["attribution"]["attributed_total"],
                 advisory["attribution"]["unattributed_total"], len(findings))
    except Exception as exc:
        log.error("Cost advisor failed (continuing): %s", exc, exc_info=True)
    return summary


def cfg_window() -> int:
    from config import observability_config as cfg
    return cfg.WINDOW_HOURS


def run_vps_snapshot(snapshot_engine, finding_store=None) -> dict:
    """Collect VPS-level state, compare to previous, deliver if changes detected."""
    from cognition.survivability import assess_survivability
    from memory.drift_detector import VpsDriftDetector
    from scanners.security_scanner import run_security_scan
    from scanners.vps_scanner import collect_vps_state

    t0 = time.monotonic()
    try:
        vps_state = collect_vps_state(scan_targets=SCAN_TARGETS)
        security = run_security_scan()
        if finding_store is not None:
            _persist_security_findings(finding_store, security.get("findings", []))
        vps_state["security"] = security

        kernel_state_path = PROJECT_ROOT / "data" / "kernel_scan_state.json"
        selfmonitor_state_path = PROJECT_ROOT / "data" / "selfmonitor_state.json"
        survivability = assess_survivability(
            finding_store=finding_store,
            kernel_state_path=kernel_state_path,
            selfmonitor_state_path=selfmonitor_state_path,
        )
        vps_state["survivability"] = survivability.to_dict()
        log.info(
            "Survivability: status=%s findings=%d oom_kills=%d",
            survivability.overall_status,
            len(survivability.findings),
            len(survivability.kernel_events.get("oom_kills", [])),
        )

        previous_snap = snapshot_engine.get_latest("vps_state")
        drift: dict = {"change_count": 0, "changes": [], "human_readable": [],
                       "summary": "No previous VPS snapshot — baseline established."}

        if previous_snap:
            drift = VpsDriftDetector().compare(
                previous_snap.get("data", {}), vps_state
            )

        vps_state["drift"] = drift
        snapshot_engine.create_snapshot(vps_state, "vps_state")

        duration = round(time.monotonic() - t0, 3)
        log.info(
            "VPS snapshot complete | services=%d ports=%d containers=%d "
            "unscanned=%d security_high=%d drift_changes=%d | %.2fs",
            len(vps_state.get("service_names", [])),
            len(vps_state.get("port_set", [])),
            len(vps_state.get("container_names", [])),
            len(vps_state.get("unscanned_services", [])),
            security.get("high_count", 0),
            drift["change_count"],
            duration,
        )

        # Deliver drift or security findings if noteworthy
        _deliver_vps_if_needed(vps_state, drift, security)

        return vps_state
    except Exception as exc:
        log.error("VPS snapshot failed: %s", exc, exc_info=True)
        return {}


def _deliver_vps_if_needed(vps_state: dict, drift: dict, security: dict) -> None:
    """Deliver a report if there are meaningful changes or new high findings."""
    from datetime import UTC, datetime

    from delivery.formatting import format_drift_summary
    from delivery.pipeline import deliver

    drift_events = drift.get("human_readable", [])
    unscanned = vps_state.get("unscanned_services", [])

    # Decide whether to deliver:
    # - Any VPS drift event: always deliver
    # - High security findings: always deliver on first run of the day (handled by daily report)
    # - No changes: skip (daily report already covers static state)
    if not drift_events:
        log.info("VPS snapshot: no drift — skipping inter-cycle delivery")
        return

    ts = datetime.now(UTC)

    # Build compact drift markdown
    drift_lines = [
        "# Drift Detection Report",
        f"Generated: {ts.isoformat()}",
        "",
        "## Infrastructure Changes",
        "",
    ]
    for ev in drift_events:
        drift_lines.append(f"- {ev}")
    drift_lines += [
        "",
        "## VPS State",
        "",
        f"- Services: {len(vps_state.get('service_names', []))}",
        f"- Listening ports: {len(vps_state.get('port_set', []))}",
        f"- Docker containers: {len(vps_state.get('container_names', []))}",
        f"- Unscanned services: {len(unscanned)}",
        "",
        "---",
        "",
        "*Advisory only — operational decisions require human review.*",
    ]
    report_content = "\n".join(drift_lines)

    tg_summary = format_drift_summary(
        changes=drift_events,
        target="VPS",
        timestamp=ts.strftime("%Y-%m-%d %H:%M UTC"),
    )

    result = deliver(
        report_type="drift",
        content=report_content,
        summary=tg_summary,
        timestamp=ts,
        filename_suffix=ts.strftime("%H%M"),
    )
    log.info(
        "Drift delivery: git=%s telegram=%s",
        "ok" if result.git_ok else "FAIL",
        "ok" if result.telegram_ok else "FAIL",
    )


def run_notifications(finding_store, graph_store=None) -> dict:
    """Push P0/P1 notifications for active findings detected this cycle.

    Reads persisted findings (with finding_id + occurrence_count) and routes them
    through the deterministic NotificationPipeline. Dedup is shared with
    scripts/notify.py via data/notification_state.json. Advisory only.
    """
    from delivery.notifications import NotificationPipeline

    try:
        findings = finding_store.get_active_findings()
        pipe = NotificationPipeline(
            persist=True, finding_store=finding_store,
            git_sync=True, graph_store=graph_store,
        )
        result = pipe.process(findings)
        log.info(
            "Notifications: sent=%d (P0=%d P1=%d) suppressed=%d",
            len(result.sent), result.p0_sent, result.p1_sent, len(result.suppressed),
        )
        return {"sent": len(result.sent), "p0": result.p0_sent, "p1": result.p1_sent}
    except Exception as exc:
        log.error("Notification pass failed: %s", exc, exc_info=True)
        return {"sent": 0}


def scan_target(
    target: str,
    registry,
    snapshot_engine,
    drift_detector,
    report_generator,
    finding_store=None,
    graph_store=None,
):
    from backend.operations import run_full_scan

    if not Path(target).exists():
        log.warning("Target does not exist, skipping: %s", target)
        return None

    t0 = time.monotonic()
    try:
        result = run_full_scan(
            target=target,
            registry=registry,
            snapshot_engine=snapshot_engine,
            drift_detector=drift_detector,
            report_generator=report_generator,
            finding_store=finding_store,
        )

        # Persist the topology graph so the WHAT-IF brain has a standing,
        # queryable substrate between scan runs.
        if graph_store is not None:
            try:
                from topology.persistence import persist_topology
                topo_summary = persist_topology(result["topology"], target, graph_store)
                log.info(
                    "Topology persisted: %s | nodes=%d edges=%d "
                    "resolved_nodes=%d resolved_edges=%d",
                    target,
                    topo_summary["nodes_upserted"],
                    topo_summary["edges_upserted"],
                    topo_summary["nodes_resolved"],
                    topo_summary["edges_resolved"],
                )
            except Exception as exc:
                log.error(
                    "Topology persistence failed for %s (scan continues): %s",
                    target,
                    exc,
                    exc_info=True,
                )

        duration = round(time.monotonic() - t0, 3)
        log.info(
            "Scan complete: %s | snapshot=%s | nodes=%s | workflows=%s | recs=%s | drift=%s | %.2fs",
            target,
            result["snapshot_id"],
            result["topology"]["node_count"],
            len(result["workflows"]),
            len(result["recommendations"]),
            result["drift"]["change_count"] if result["drift"] else 0,
            duration,
        )
        return result
    except Exception as exc:
        log.error("Scan failed for %s: %s", target, exc, exc_info=True)
        return None


def main():
    started_at = datetime.now(UTC).isoformat()
    log.info("=== Scheduled scan starting — %s ===", started_at)

    try:
        registry, snapshot_engine, drift_detector, report_generator, finding_store, graph_store = build_dependencies()
    except Exception as exc:
        log.error("Failed to initialise scan dependencies: %s", exc, exc_info=True)
        sys.exit(1)

    # VPS-level snapshot first — captures infrastructure reality before per-target scans
    run_vps_snapshot(snapshot_engine, finding_store=finding_store)

    # Economic + project + agent observability (Phases A/B/C)
    run_activity_observability(snapshot_engine, finding_store=finding_store)

    # Cost advisor — provider/attribution/budget view (Economics slot); persists
    # its money findings before notifications so the criticals page on this cycle.
    run_cost_advisor(finding_store)

    # Real-time notifications for newly-detected P0/P1 findings (PRIORITY ZERO).
    # Shares dedup state with scripts/notify.py so nothing double-fires.
    run_notifications(finding_store, graph_store=graph_store)

    results = []
    for target in SCAN_TARGETS:
        result = scan_target(
            target, registry, snapshot_engine, drift_detector, report_generator,
            finding_store=finding_store, graph_store=graph_store,
        )
        results.append((target, result))

    successful = sum(1 for _, r in results if r is not None)
    failed = len(results) - successful
    log.info(
        "=== Scan cycle complete — %d/%d targets succeeded ===",
        successful,
        len(results),
    )
    if failed:
        log.warning("%d target(s) failed or skipped", failed)


if __name__ == "__main__":
    main()
