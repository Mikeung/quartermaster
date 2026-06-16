#!/usr/bin/env python3
"""Self-monitor — checks that the operational memory pipeline is functioning.

Every execution:
  1. Checks heartbeat freshness (detects missed cron cycles via selfmonitor_state.json)
  2. Runs health checks (scan freshness, report freshness, DB growth, delivery state)
  3. Writes selfmonitor_state.json with last_run, duration, status
  4. Writes a brief status file to reports/history/YYYY-MM-DD/selfmonitor_HHMM.md
  5. Git commits + pushes the status file
  6. Sends Telegram CRITICAL alert if heartbeat stale; alert for any other failures

Cron: 0 */2 * * *
"""

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

LOG_FILE = "/var/log/ai-quartermaster-selfmonitor.log"
SCAN_LOG = Path("/var/log/ai-quartermaster-scan.log")
DAILY_LOG = Path("/var/log/ai-quartermaster-daily.log")
HISTORY_DIR = PROJECT_ROOT / "reports" / "history"
DB_PATH = PROJECT_ROOT / "data" / "operational_memory.db"
SELFMONITOR_STATE_PATH = PROJECT_ROOT / "data" / "selfmonitor_state.json"

_SCAN_STALE_HOURS = 8
_REPORT_STALE_HOURS = 26
_DELIVERY_STALE_HOURS = 30
# Heartbeat: selfmonitor runs every 2h; alert if gap exceeds 3h (1 missed cycle + buffer)
_HEARTBEAT_EXPECTED_INTERVAL_HOURS = 2
_HEARTBEAT_STALE_THRESHOLD_HOURS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("selfmonitor")


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


def _load_selfmonitor_state() -> dict:
    """Read persisted selfmonitor state. Returns empty dict on first run."""
    try:
        if SELFMONITOR_STATE_PATH.exists():
            return json.loads(SELFMONITOR_STATE_PATH.read_text())
    except Exception as exc:
        log.warning("Cannot read selfmonitor_state.json: %s", exc)
    return {}


def _save_selfmonitor_state(
    *,
    status: str,
    duration_s: float,
    checks_passed: int,
    checks_failed: int,
    ts: datetime,
) -> None:
    """Persist selfmonitor execution state for heartbeat detection."""
    state: dict = {
        "last_run": ts.isoformat(),
        "duration_s": round(duration_s, 3),
        "status": status,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
    }
    # last_successful_run only advances when all checks pass
    existing = _load_selfmonitor_state()
    if status == "ok":
        state["last_successful_run"] = ts.isoformat()
    else:
        state["last_successful_run"] = existing.get("last_successful_run")

    try:
        SELFMONITOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        SELFMONITOR_STATE_PATH.write_text(json.dumps(state, indent=2))
        log.info("selfmonitor_state.json written: status=%s duration=%.3fs", status, duration_s)
    except Exception as exc:
        log.warning("Cannot write selfmonitor_state.json: %s", exc)


def _check_heartbeat_freshness() -> tuple[bool, str]:
    """Detect missed selfmonitor cron cycles by comparing to persisted last_run.

    First run returns True (no prior state = not a failure).
    Fires CRITICAL if the gap since last_run exceeds the stale threshold.
    This catches: broken cron, system downtime, crontab misconfiguration.
    """
    state = _load_selfmonitor_state()
    if not state:
        return True, "No prior state — first run, baseline established"

    last_run_raw = state.get("last_run")
    if not last_run_raw:
        return True, "No prior timestamp in state — treating as first run"

    try:
        last_run = datetime.fromisoformat(last_run_raw)
        age_hours = (datetime.now(UTC) - last_run).total_seconds() / 3600
        if age_hours > _HEARTBEAT_STALE_THRESHOLD_HOURS:
            return False, (
                f"CRITICAL: selfmonitor last ran {age_hours:.1f}h ago "
                f"(expected every {_HEARTBEAT_EXPECTED_INTERVAL_HOURS}h, "
                f"alert threshold {_HEARTBEAT_STALE_THRESHOLD_HOURS}h) — "
                f"cron may be broken or system was restarted"
            )
        return True, (
            f"Heartbeat current: {age_hours:.1f}h since last run "
            f"(threshold {_HEARTBEAT_STALE_THRESHOLD_HOURS}h)"
        )
    except Exception as exc:
        return False, f"Cannot parse last_run timestamp '{last_run_raw}': {exc}"


def _age_hours(path: Path) -> float | None:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return (datetime.now(UTC) - mtime).total_seconds() / 3600
    except Exception:
        return None


def _check_scan_freshness() -> tuple[bool, str]:
    if not SCAN_LOG.exists():
        return False, "Scan log missing — pipeline may never have run"
    age = _age_hours(SCAN_LOG)
    if age is None or age > _SCAN_STALE_HOURS:
        return False, f"Scan log last updated {age:.1f}h ago (threshold: {_SCAN_STALE_HOURS}h)"
    return True, f"Scan log fresh: {age:.1f}h old"


def _check_report_freshness() -> tuple[bool, str]:
    reports: list[Path] = []
    if HISTORY_DIR.exists():
        # Match daily.md written by delivery pipeline
        reports = sorted(HISTORY_DIR.glob("*/daily.md"))
    if not reports:
        return False, "No daily reports found in reports/history/"
    latest = reports[-1]
    age = _age_hours(latest)
    if age is None or age > _REPORT_STALE_HOURS:
        return False, f"Latest daily report is {age:.1f}h old (threshold: {_REPORT_STALE_HOURS}h)"
    return True, f"Daily report fresh: {latest.parent.name}/{latest.name}, {age:.1f}h old"


def _check_db_growth() -> tuple[bool, str]:
    if not DB_PATH.exists():
        return False, "Operational DB missing"
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cutoff = (datetime.now(UTC) - timedelta(hours=26)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE created_at > ?", (cutoff,)
        ).fetchone()
        conn.close()
        count = row[0] if row else 0
        if count == 0:
            return False, "No new snapshots in the last 26h — scan pipeline stuck"
        return True, f"{count} snapshots written in the last 26h"
    except Exception as exc:
        return False, f"DB check error: {exc}"


def _check_delivery_state() -> tuple[bool, str]:
    """Check that git and Telegram have succeeded recently."""
    from delivery.pipeline import get_delivery_state
    state = get_delivery_state()
    issues = []

    for channel, key in [("git", "last_git_push_success"), ("Telegram", "last_telegram_success")]:
        last = state.get(key)
        if last is None:
            issues.append(f"No successful {channel} delivery recorded")
            continue
        try:
            dt = datetime.fromisoformat(last)
            age = (datetime.now(UTC) - dt).total_seconds() / 3600
            if age > _DELIVERY_STALE_HOURS:
                fails = state.get(f"{'git' if channel == 'git' else 'telegram'}_failures_since_success", 0)
                issues.append(f"Last {channel} push was {age:.1f}h ago ({fails} failures since)")
        except Exception:
            issues.append(f"Cannot parse {channel} timestamp: {last}")

    if issues:
        return False, "; ".join(issues)
    return True, "Git and Telegram delivery both current"


def _build_report_markdown(checks: list[tuple[str, bool, str]], ts: str, delivery_state: dict) -> str:
    lines = [
        "# Self-Monitor Report",
        f"Generated: {ts}",
        "",
        "## Check Results",
        "",
    ]
    failures = [(name, msg) for name, ok, msg in checks if not ok]
    for name, ok, msg in checks:
        icon = "✓" if ok else "✗"
        lines.append(f"- [{icon}] {name}: {msg}")

    lines.append("")
    lines.append("## Delivery State")
    lines.append("")
    lines.append(f"- Last git push: {delivery_state.get('last_git_push_success', 'never')}")
    lines.append(f"- Last Telegram: {delivery_state.get('last_telegram_success', 'never')}")
    lines.append(f"- Git failures since success: {delivery_state.get('git_failures_since_success', 0)}")
    lines.append(f"- Telegram failures since success: {delivery_state.get('telegram_failures_since_success', 0)}")
    lines.append("")

    if failures:
        lines.append("## Action Required")
        lines.append("")
        for name, msg in failures:
            lines.append(f"- **{name}**: {msg}")
        lines.append("")

    lines += [
        "---",
        "",
        "*Advisory only — operational decisions require human review.*",
    ]
    return "\n".join(lines)


def main():
    t_start = time.monotonic()
    ts_dt = datetime.now(UTC)
    ts = ts_dt.isoformat()
    log.info("=== Self-monitor check — %s ===", ts)

    _load_env()

    from delivery.formatting import format_operational_summary, format_selfmonitor_alert
    from delivery.pipeline import deliver, get_delivery_state

    delivery_state = get_delivery_state()

    # heartbeat_freshness runs first: detects missed cron cycles before any
    # other check. A CRITICAL heartbeat failure means the pipeline was blind
    # for longer than expected — this takes precedence in the alert summary.
    checks = [
        ("heartbeat_freshness", *_check_heartbeat_freshness()),
        ("scan_freshness", *_check_scan_freshness()),
        ("report_freshness", *_check_report_freshness()),
        ("db_growth", *_check_db_growth()),
        ("delivery_state", *_check_delivery_state()),
    ]

    failures = [(name, msg) for name, ok, msg in checks if not ok]
    for name, ok, msg in checks:
        log.info("[%s] %s: %s", "OK" if ok else "FAIL", name, msg)

    if failures:
        log.warning("Self-monitor: %d check(s) failed", len(failures))
    else:
        log.info("Self-monitor: all checks passed")

    # Always write + commit self-monitor report (even on all-pass)
    report_md = _build_report_markdown(checks, ts, delivery_state)

    if failures:
        tg_summary = format_selfmonitor_alert(
            failures=[msg for _, msg in failures],
            timestamp=ts_dt.strftime("%Y-%m-%d %H:%M UTC"),
            delivery_state=delivery_state,
        )
    else:
        tg_summary = format_operational_summary(
            report_type="selfmonitor",
            timestamp=ts_dt.strftime("%Y-%m-%d %H:%M UTC"),
            drift_events=[],
            health_failures=[],
            delivery_state=delivery_state,
        )

    # Deliver: always git-commit, only Telegram on failure
    # (success Telegram skipped to avoid noise — git serves as audit trail)
    result = deliver(
        report_type="selfmonitor",
        content=report_md,
        summary=tg_summary if failures else "",  # empty = skip Telegram on success
        timestamp=ts_dt,
        filename_suffix=ts_dt.strftime("%H%M"),
    )

    # Persist state for next cycle's heartbeat check.
    # Written after delivery so duration includes full execution time.
    duration_s = time.monotonic() - t_start
    _save_selfmonitor_state(
        status="ok" if not failures else "degraded",
        duration_s=duration_s,
        checks_passed=len(checks) - len(failures),
        checks_failed=len(failures),
        ts=ts_dt,
    )

    log.info(
        "=== Self-monitor complete — git=%s telegram=%s duration=%.2fs ===",
        "ok" if result.git_ok else "FAIL",
        "ok" if result.telegram_ok else "FAIL",
        duration_s,
    )


if __name__ == "__main__":
    main()
