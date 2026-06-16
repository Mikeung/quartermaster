#!/usr/bin/env python3
"""Real-time notifier — the high-frequency arm of the notification layer.

Runs cheap, read-only detection (git activity + spend ledger + economic/agent
analysis) and pushes P0/P1 notifications the moment something important appears.
This is what turns "found in the next daily report" into "alerted within minutes".

Properties:
- READ-ONLY: never upserts findings (so occurrence_count is not inflated — the
  6-hourly scan remains the source of truth for recurrence) and never git-commits.
- Cheap: a few `git log` calls + an idempotent spend import + SQLite aggregates.
- Dedup is shared with the scan-cycle notifier via data/notification_state.json,
  keyed on the deterministic finding_id.

Modes:
  python -m scripts.notify            send notifications for new/changed events
  python -m scripts.notify --prime    mark current events as seen, send nothing
                                       (run once on install so the backlog
                                        doesn't blast the operator)
  python -m scripts.notify --dry-run  print what would be sent; no send, no state

Cron (every 15 min):
  */15 * * * * cd /opt/quartermaster && \
    /opt/quartermaster/venv/bin/python3 scripts/notify.py \
    >> /var/log/ai-quartermaster-notify.log 2>&1
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

LOG_FILE = "/var/log/ai-quartermaster-notify.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("notify")

# These collectors are detected fresh here (read-only). Persisted survivability /
# security findings (OOM, exposure, restarts) are pulled from FindingStore so the
# notifier covers them too, without re-detecting them.
_PERSISTED_COLLECTORS = ("survivability_scanner", "security_scanner")


def detect_findings() -> list[dict]:
    """Read-only detection of economic/project/agent findings + persisted P0/P1.

    Returns finding dicts with full identity fields (no DB writes). finding_ids
    computed downstream match exactly what the 6-hourly scan persists, so dedup
    is consistent across both notifier arms.
    """
    from cognition.project_activity import analyze_project_activity
    from config import observability_config as cfg
    from memory.finding_store import FindingStore
    from memory.llm_store import LLMEventStore
    from observability.agent_activity import analyze_agent_activity
    from observability.economic import detect_economic_findings
    from scanners.git_activity_scanner import collect_all_git_activity
    from scripts.import_spend import import_spend
    from scripts.scheduled_scan import SCAN_TARGETS

    win = cfg.WINDOW_HOURS
    findings: list[dict] = []

    # Phase B/C/A — fresh, read-only
    git_activity = collect_all_git_activity(SCAN_TARGETS, window_hours=win)
    findings.extend(analyze_project_activity(git_activity))

    try:
        import_spend()  # idempotent; picks up new ledger drops
    except Exception as exc:
        log.warning("Spend import failed (continuing): %s", exc)

    db_path = str(PROJECT_ROOT / "data" / "operational_memory.db")
    llm_store = LLMEventStore(db_path)
    llm_store.connect()
    try:
        findings.extend(detect_economic_findings(llm_store, win))
        findings.extend(analyze_agent_activity(git_activity, llm_store, win))
    finally:
        llm_store.disconnect()

    # Persisted survivability/security findings (detected by the 6h scan) so the
    # notifier surfaces OOM / public-exposure / restart bursts within minutes too.
    fs = FindingStore(db_path)
    fs.connect()
    try:
        for ctype in _PERSISTED_COLLECTORS:
            findings.extend(fs.get_active_findings(collector_type=ctype))
    finally:
        fs.disconnect()

    return findings


def main() -> int:
    from delivery.notifications import NotificationPipeline

    prime = "--prime" in sys.argv
    dry = "--dry-run" in sys.argv
    now = datetime.now(UTC)
    log.info("=== notify start (prime=%s dry_run=%s) ===", prime, dry)

    findings = detect_findings()
    log.info("Detected %d candidate findings", len(findings))

    if dry:
        captured: list[str] = []
        pipe = NotificationPipeline(send_fn=lambda t: captured.append(t) or True, persist=False)
        result = pipe.process(findings, now=now)
        print(f"[dry-run] {result.summary()}")
        for m in result.messages:
            print("---\n" + m)
        return 0

    # Real Telegram sender. git_sync=True: incident reports for sent P0/P1 are
    # committed + pushed (system of record). This stages ONLY reports/incidents/,
    # never findings state — occurrence_count integrity is preserved.
    pipe = NotificationPipeline(persist=True, git_sync=True)
    if prime:
        n = pipe.prime(findings, now=now)
        log.info("=== notify prime complete — %d findings marked seen ===", n)
        return 0

    result = pipe.process(findings, now=now)
    log.info("=== notify complete — %s ===", result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
