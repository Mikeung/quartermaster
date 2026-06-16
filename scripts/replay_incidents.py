#!/usr/bin/env python3
"""Replay representative incidents to validate the incident-reporting chain.

Builds three real-shaped findings — the Gemini spend runaway (from the actual
Lesia P7 ledger), a kernel OOM kill, and a subsystem rebuild — and runs them
through the notification pipeline with a CAPTURING sender (no Telegram send).
It writes the incident reports under reports/incidents/<today>/ and prints the
short alerts, demonstrating that each alert references its committed report.

This proves: report created (file on disk) + Telegram references report. The
git commit/push of these example reports is performed by the phase's
implementation commit (so the pushed evidence carries a real commit hash);
this script does NOT push, by design (git_sync stays off here).

  python -m scripts.replay_incidents
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def _gemini_finding() -> dict:
    """The real Gemini spend incident, detected from the Lesia P7 audit ledger."""
    from memory.llm_store import LLMEventStore
    from observability.economic import detect_economic_findings
    from schemas.llm_event_schema import LLMEvent

    ledger = PROJECT_ROOT / "data" / "spend" / "lesia_p7_audit.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    tmp_db = PROJECT_ROOT / "data" / "_replay_tmp.db"
    store = LLMEventStore(str(tmp_db))
    store.connect()
    n = len(rows)
    base = datetime.now(UTC).timestamp()
    for i, r in enumerate(rows):
        ts = datetime.fromtimestamp(base - (n - i) * 2400, UTC).isoformat()
        store.append(LLMEvent(timestamp=ts, provider=r["provider"], model=r["model"],
                              workflow=r["workflow"], prompt_tokens=0, completion_tokens=0,
                              total_tokens=0, latency_ms=0.0, success=True,
                              estimated_cost=r["estimated_cost"]), project_id=r.get("project_id"))
    findings = detect_economic_findings(store, 24)
    store.disconnect()
    tmp_db.unlink(missing_ok=True)
    runaway = [f for f in findings if f["finding_type"] == "runaway_agent_cost"]
    return runaway[0] if runaway else findings[0]


def _oom_finding() -> dict:
    return {"target_id": "vps", "finding_type": "kernel_oom_kill", "resource": "node",
            "scope": "survivability", "collector_type": "survivability_scanner",
            "severity": "CRITICAL", "title": "OOM kill: node terminated (anon-rss 3.7 GB)",
            "description": "Kernel OOM killer terminated the node process under memory pressure.",
            "evidence": ["Out of memory: Killed process (node) total-vm:5.2GB anon-rss:3.7GB",
                         "occurred during overnight window"],
            "recommendation": "Add a memory limit / fix the leak; in-flight work was lost.",
            "first_seen": "2026-05-30T02:14:00+00:00", "last_seen": "2026-05-30T02:14:00+00:00"}


def _rebuild_finding() -> dict:
    return {"target_id": "lesia", "finding_type": "subsystem_rebuild",
            "resource": "lesia:backend/services", "scope": "project",
            "collector_type": "git_activity_scanner", "severity": "MEDIUM",
            "title": "Subsystem rebuild: backend/services (28 of 52 changed files)",
            "description": "backend/services was substantially rewritten in the window.",
            "evidence": ["28 of 52 changed files under backend/services",
                         "commits by aider-driven automation"],
            "recommendation": "Review the rewrite before regressions ship.",
            "first_seen": "2026-05-30T08:05:00+00:00", "last_seen": "2026-05-30T12:40:00+00:00"}


def main() -> int:
    from delivery.notifications import NotificationPipeline
    from reports.incident_report import incident_relpath

    now = datetime.now(UTC)
    findings = [_gemini_finding(), _oom_finding(), _rebuild_finding()]

    captured: list[str] = []
    # persist=True writes the report files; git_sync stays OFF (the impl commit
    # pushes them). State/log isolated to a temp dir so dedup state isn't touched.
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    pipe = NotificationPipeline(
        send_fn=lambda t: captured.append(t) or True,
        persist=True, state_path=tmp / "s.json", log_path=tmp / "l.jsonl",
        incident_root=PROJECT_ROOT, git_sync=False,
    )
    result = pipe.process(findings, now=now)

    print(f"\n=== Replay: {len(findings)} incidents — {result.summary()} ===\n")
    for f in findings:
        rp = incident_relpath(f, now)
        exists = (PROJECT_ROOT / rp).exists()
        print(f"[{f['finding_type']}] report {'CREATED' if exists else 'MISSING'}: {rp}")
    print("\n=== Telegram alerts (each references its report) ===")
    for m in captured:
        print("\n--- alert ---\n" + m)
    print("\nNext: `git add reports/incidents && git commit && git push` "
          "commits these example reports (system of record).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
