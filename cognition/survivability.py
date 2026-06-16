"""
Survivability assessment — 4-layer host health model.

Layer 1: Process/listener existence  (informational — vps_scanner owns inventory)
Layer 2: Service restart recurrence  (systemd NRestarts threshold)
Layer 3: Dependency integrity        (Postgres via pg_isready, Redis via redis-cli)
Layer 4: Kernel pressure             (OOM kills, IO errors, kernel panics)

Also checks monitor staleness via selfmonitor_state.json.

Integrates with FindingStore for persistent identity and severity escalation.
All output is advisory only — no infrastructure changes.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.finding_store import FindingStore

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_RESTART_WARN = 5         # NRestarts threshold for MEDIUM finding
_RESTART_HIGH = 10        # NRestarts threshold for HIGH finding
_OOM_CRITICAL_COUNT = 3   # occurrence_count at which OOM escalates to CRITICAL
_STALE_MONITOR_HOURS = 4  # hours since last_successful_run → monitor_stale finding

_TARGET_ID = "vps"
_COLLECTOR = "survivability_scanner"

# OS/infra units excluded from restart checks — same whitelist as vps_scanner
_OS_UNITS = {
    "dbus.service", "atd.service", "cron.service", "ssh.service",
    "rsyslog.service", "fail2ban.service", "multipathd.service",
    "syslog.service", "systemd-journald.service", "systemd-logind.service",
    "systemd-networkd.service", "systemd-resolved.service",
    "systemd-timesyncd.service", "systemd-udevd.service",
    "polkit.service", "qemu-guest-agent.service",
    "getty@tty1.service", "serial-getty@ttyS0.service",
    "unattended-upgrades.service", "tailscaled.service",
    "postgresql@16-main.service", "containerd.service", "docker.service",
}


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class SurvivabilityReport:
    """4-layer survivability assessment output."""
    findings: list[dict[str, Any]]
    active_finding_ids: set[str]
    kernel_events: dict[str, Any]
    layer_summaries: dict[str, str]
    overall_status: str    # "ok", "degraded", "critical"

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": self.findings,
            "kernel_events": self.kernel_events,
            "layer_summaries": self.layer_summaries,
            "overall_status": self.overall_status,
            "finding_count": len(self.findings),
        }


# ── Shell helpers ────────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    """Run a command. Returns (returncode, stdout). Returns (-1, '') when unavailable."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or ""
    except FileNotFoundError:
        return -1, ""   # tool not installed — caller interprets as N/A
    except Exception as exc:
        logger.debug("survivability: command %s failed: %s", cmd, exc)
        return -1, ""


# ── Layer 2: Service restart recurrence ─────────────────────────────────────

def _check_systemd_restarts() -> list[dict[str, Any]]:
    """Return non-OS services whose NRestarts ≥ _RESTART_WARN."""
    rc, raw = _run(
        ["systemctl", "list-units", "--type=service",
         "--no-pager", "--no-legend", "--plain"],
        timeout=15,
    )
    if rc == -1 or not raw.strip():
        return []

    units = []
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        if unit in _OS_UNITS or unit.startswith("user@"):
            continue
        if unit.endswith(".service"):
            units.append(unit)

    if not units:
        return []

    # Batch systemctl show for all app units at once
    rc2, show_raw = _run(
        ["systemctl", "show"] + units + ["--property=Id,NRestarts", "--no-pager"],
        timeout=30,
    )
    if rc2 == -1:
        return []

    results: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in show_raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if "id" in current and "nrestarts" in current:
                if current["nrestarts"] >= _RESTART_WARN:
                    results.append({"unit": current["id"], "restarts": current["nrestarts"]})
            current = {}
        elif stripped.startswith("Id="):
            current["id"] = stripped[3:]
        elif stripped.startswith("NRestarts="):
            try:
                current["nrestarts"] = int(stripped[10:])
            except ValueError:
                current["nrestarts"] = 0
    # Flush last block (no trailing blank line)
    if "id" in current and "nrestarts" in current:
        if current["nrestarts"] >= _RESTART_WARN:
            results.append({"unit": current["id"], "restarts": current["nrestarts"]})

    return results


# ── Layer 3: Dependency integrity ────────────────────────────────────────────

def _check_postgres() -> bool | None:
    """True = reachable, False = unreachable, None = pg_isready not available."""
    rc, _ = _run(["pg_isready", "-h", "localhost", "-p", "5432"], timeout=5)
    if rc == -1:
        return None
    return rc == 0


def _check_redis() -> bool | None:
    """True = reachable, False = unreachable, None = redis-cli not available."""
    rc, out = _run(["redis-cli", "-h", "localhost", "ping"], timeout=5)
    if rc == -1:
        return None
    return "PONG" in out


# ── Monitor staleness ────────────────────────────────────────────────────────

def _check_monitor_staleness(state_path: Path) -> dict[str, Any] | None:
    """Return staleness info if monitor hasn't run in _STALE_MONITOR_HOURS, else None."""
    try:
        if not state_path.exists():
            return {"last_run": None, "hours_since": None, "reason": "state file missing"}
        data = json.loads(state_path.read_text())
        last_str = data.get("last_successful_run") or data.get("last_run")
        if not last_str:
            return {"last_run": None, "hours_since": None, "reason": "no timestamp in state"}
        last_run = datetime.fromisoformat(last_str)
        hours = (datetime.now(UTC) - last_run).total_seconds() / 3600
        if hours > _STALE_MONITOR_HOURS:
            return {"last_run": last_str, "hours_since": round(hours, 1)}
        return None
    except Exception as exc:
        logger.warning("monitor staleness check failed: %s", exc)
        return None


# ── Finding helpers ──────────────────────────────────────────────────────────

def _projected_count(finding_store: FindingStore, finding_id: str) -> int:
    """Compute occurrence_count that will result after the next upsert call."""
    existing = finding_store.get_finding(finding_id)
    if existing is None:
        return 1
    if existing.get("resolved_at") is not None:
        return 1   # reactivation resets count
    return existing["occurrence_count"] + 1


def _upsert_or_build(
    finding_store: FindingStore | None,
    *,
    finding_id: str,
    target_id: str,
    finding_type: str,
    resource: str,
    scope: str,
    severity: str,
    collector_type: str,
    title: str,
    description: str,
    recommendation: str,
    evidence: list[str],
    confidence: float,
) -> dict[str, Any]:
    """Upsert into FindingStore if available, otherwise return an ephemeral dict."""
    if finding_store is not None:
        row = finding_store.upsert(
            finding_id=finding_id,
            target_id=target_id,
            finding_type=finding_type,
            resource=resource,
            scope=scope,
            severity=severity,
            collector_type=collector_type,
            title=title,
            description=description,
            recommendation=recommendation,
            evidence=evidence,
            confidence=confidence,
        )
        return dict(row)
    return {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "resource": resource,
        "severity": severity,
        "occurrence_count": 1,
        "title": title,
        "recommendation": recommendation,
        "evidence": evidence,
    }


# ── Public API ───────────────────────────────────────────────────────────────

def assess_survivability(
    finding_store: FindingStore | None = None,
    kernel_state_path: Path | str | None = None,
    selfmonitor_state_path: Path | str | None = None,
    max_lookback_hours: int = 26,
) -> SurvivabilityReport:
    """Run the 4-layer survivability assessment and persist findings.

    Returns a SurvivabilityReport with all detected issues.
    If finding_store is None, findings are returned ephemerally (no persistence).
    """
    from memory.finding_store import compute_finding_id
    from scanners.kernel_scanner import scan_kernel_events

    findings: list[dict[str, Any]] = []
    active_ids: set[str] = set()
    layer_summaries: dict[str, str] = {}

    # ── Layer 4: Kernel pressure ─────────────────────────────────────────────
    ksp = Path(kernel_state_path) if kernel_state_path else None
    kernel_events = scan_kernel_events(
        state_path=ksp,
        max_lookback_hours=max_lookback_hours,
    )

    oom_labels: list[str] = []
    for oom in kernel_events.get("oom_kills", []):
        proc = oom["process_name"]
        pid = oom.get("pid", 0)
        rss_kb = oom.get("memory_rss_kb")
        rss_str = f"{rss_kb // 1024} MB" if rss_kb else "unknown"

        fid = compute_finding_id(
            target_id=_TARGET_ID,
            finding_type="kernel_oom_kill",
            resource=proc,
            scope="host",
            collector_type=_COLLECTOR,
        )

        count = _projected_count(finding_store, fid) if finding_store else 1
        severity = "CRITICAL" if count >= _OOM_CRITICAL_COUNT else "HIGH"

        evidence = [
            f"Process: {proc} (pid {pid})",
            f"Memory RSS at kill: {rss_str}",
            f"Timestamp: {oom.get('timestamp', 'unknown')}",
        ]
        rec = (
            f"Investigate OOM kill of '{proc}'. "
            "Check for memory leaks, unbounded caches, or missing memory limits."
        )
        if count >= _OOM_CRITICAL_COUNT:
            rec += f" Process has been OOM-killed {count} times — investigate urgently."

        f_dict = _upsert_or_build(
            finding_store,
            finding_id=fid,
            target_id=_TARGET_ID,
            finding_type="kernel_oom_kill",
            resource=proc,
            scope="host",
            severity=severity,
            collector_type=_COLLECTOR,
            title=f"OOM kill: {proc}",
            description=f"Kernel OOM killer terminated {proc} (pid {pid}). RSS: {rss_str}.",
            recommendation=rec,
            evidence=evidence,
            confidence=0.95,
        )
        f_dict.setdefault("finding_type", "kernel_oom_kill")
        findings.append(f_dict)
        active_ids.add(fid)
        oom_labels.append(f"{proc}(pid={pid})")

    io_count = len(kernel_events.get("io_errors", []))
    kerr_count = len(kernel_events.get("kernel_errors", []))
    if oom_labels:
        parts = [f"OOM kills: {', '.join(oom_labels)}"]
        if io_count:
            parts.append(f"IO errors: {io_count}")
        layer_summaries["layer4_kernel"] = "; ".join(parts)
    elif io_count or kerr_count:
        layer_summaries["layer4_kernel"] = f"IO errors: {io_count}, kernel errors: {kerr_count}"
    else:
        layer_summaries["layer4_kernel"] = "ok"

    # ── Layer 2: Service restart recurrence ──────────────────────────────────
    restart_issues = _check_systemd_restarts()
    for svc in restart_issues:
        unit = svc["unit"]
        restarts = svc["restarts"]
        severity = "HIGH" if restarts >= _RESTART_HIGH else "MEDIUM"

        fid = compute_finding_id(
            target_id=_TARGET_ID,
            finding_type="repeated_service_restart",
            resource=unit,
            scope="host",
            collector_type=_COLLECTOR,
        )

        f_dict = _upsert_or_build(
            finding_store,
            finding_id=fid,
            target_id=_TARGET_ID,
            finding_type="repeated_service_restart",
            resource=unit,
            scope="host",
            severity=severity,
            collector_type=_COLLECTOR,
            title=f"Repeated restart: {unit}",
            description=f"{unit} has restarted {restarts} times since last boot.",
            recommendation=(
                f"Review crash logs: journalctl -u {unit} -n 100. "
                "Check for OOM, crash loops, or misconfiguration."
            ),
            evidence=[f"Service: {unit}", f"NRestarts: {restarts}"],
            confidence=0.90,
        )
        f_dict.setdefault("finding_type", "repeated_service_restart")
        findings.append(f_dict)
        active_ids.add(fid)

    if restart_issues:
        layer_summaries["layer2_restarts"] = (
            f"Elevated restarts: {', '.join(s['unit'] for s in restart_issues)}"
        )
    else:
        layer_summaries["layer2_restarts"] = "ok"

    # ── Layer 3: Dependency integrity ────────────────────────────────────────
    dep_checks = [
        ("postgres", _check_postgres(), 5432),
        ("redis", _check_redis(), 6379),
    ]
    dep_issues: list[str] = []
    for dep_name, reachable, port in dep_checks:
        if reachable is None:
            continue   # tool not installed — not a finding
        if reachable is False:
            fid = compute_finding_id(
                target_id=_TARGET_ID,
                finding_type="dependency_unreachable",
                resource=dep_name,
                scope="host",
                collector_type=_COLLECTOR,
            )
            f_dict = _upsert_or_build(
                finding_store,
                finding_id=fid,
                target_id=_TARGET_ID,
                finding_type="dependency_unreachable",
                resource=dep_name,
                scope="host",
                severity="HIGH",
                collector_type=_COLLECTOR,
                title=f"Dependency unreachable: {dep_name}",
                description=f"{dep_name} is not responding on localhost:{port}.",
                recommendation=(
                    f"Check {dep_name} service status and logs. "
                    f"Verify it is running and listening on port {port}."
                ),
                evidence=[
                    f"Dependency: {dep_name} (port {port})",
                    "Reachability probe returned failure",
                ],
                confidence=0.85,
            )
            f_dict.setdefault("finding_type", "dependency_unreachable")
            findings.append(f_dict)
            active_ids.add(fid)
            dep_issues.append(dep_name)

    layer_summaries["layer3_deps"] = (
        f"Unreachable: {', '.join(dep_issues)}" if dep_issues else "ok"
    )

    # ── Monitor staleness ────────────────────────────────────────────────────
    smp = Path(selfmonitor_state_path) if selfmonitor_state_path else None
    if smp:
        stale = _check_monitor_staleness(smp)
        if stale:
            hours = stale.get("hours_since", "?")
            reason = stale.get("reason", "")
            fid = compute_finding_id(
                target_id=_TARGET_ID,
                finding_type="monitor_stale",
                resource="selfmonitor",
                scope="host",
                collector_type=_COLLECTOR,
            )
            evidence = [f"Last successful run: {stale.get('last_run', 'unknown')}"]
            if hours is not None:
                evidence.append(f"Hours elapsed: {hours}")
            if reason:
                evidence.append(f"Reason: {reason}")

            f_dict = _upsert_or_build(
                finding_store,
                finding_id=fid,
                target_id=_TARGET_ID,
                finding_type="monitor_stale",
                resource="selfmonitor",
                scope="host",
                severity="MEDIUM",
                collector_type=_COLLECTOR,
                title="Self-monitor is stale",
                description=f"Self-monitor has not run successfully in {hours}h.",
                recommendation=(
                    "Check cron job and /var/log/ai-quartermaster-scan.log for errors. "
                    "Verify the scan pipeline is running."
                ),
                evidence=evidence,
                confidence=0.90,
            )
            f_dict.setdefault("finding_type", "monitor_stale")
            findings.append(f_dict)
            active_ids.add(fid)
            layer_summaries["monitor"] = f"Stale: {hours}h since last run"
        else:
            layer_summaries["monitor"] = "ok"

    # ── Layer 1: Process existence ───────────────────────────────────────────
    # vps_scanner owns process inventory; no findings generated here
    layer_summaries["layer1_processes"] = "ok"

    # ── Resolve absent findings ──────────────────────────────────────────────
    if finding_store is not None:
        resolved = finding_store.mark_resolved(
            active_ids, target_id=_TARGET_ID, collector_type=_COLLECTOR
        )
        if resolved:
            logger.info("Survivability: %d finding(s) auto-resolved", resolved)

    # ── Overall status ───────────────────────────────────────────────────────
    severities = {f.get("severity", "LOW") for f in findings}
    if "CRITICAL" in severities:
        overall = "critical"
    elif "HIGH" in severities or findings:
        overall = "degraded"
    else:
        overall = "ok"

    logger.info(
        "Survivability assessment: %d findings, status=%s "
        "(oom=%d, restarts=%d, dep_issues=%d)",
        len(findings), overall,
        len(kernel_events.get("oom_kills", [])),
        len(restart_issues),
        len(dep_issues),
    )

    return SurvivabilityReport(
        findings=findings,
        active_finding_ids=active_ids,
        kernel_events=kernel_events,
        layer_summaries=layer_summaries,
        overall_status=overall,
    )
