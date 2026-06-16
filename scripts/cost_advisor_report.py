#!/usr/bin/env python3
"""Cost advisor — gather real spend evidence, build the advisory, write the artifact.

Read-only and advisory. The evidence-gathering lives in economics.runner.build_live
(shared with the `qm cost` CLI command); this script writes the markdown artifact and
can optionally emit the money findings for the notifier.

Usage:
    python scripts/cost_advisor_report.py [--window-hours 24] [--print] [--emit-findings]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import observability_config as cfg  # noqa: E402
from economics.runner import build_live  # noqa: E402
from reports.cost_advisor_report import render_cost_advisor_report  # noqa: E402

_DB_PATH = str(PROJECT_ROOT / "data" / "operational_memory.db")
_OUT = PROJECT_ROOT / "reports" / "economics" / "COST_ADVISOR.md"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the cost advisory artifact")
    ap.add_argument("--window-hours", type=int, default=cfg.WINDOW_HOURS)
    ap.add_argument("--print", action="store_true", dest="do_print")
    ap.add_argument("--emit-findings", action="store_true")
    args = ap.parse_args()

    built = build_live(window_hours=args.window_hours)
    advisory, investigations = built["advisory"], built["investigations"]
    for e in built["key_errors"]:
        print(f"WARN cost_advisor.yml: {e}", file=sys.stderr)

    report = render_cost_advisor_report(advisory, investigations)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(report)
    print(f"Wrote {_OUT} ({len(advisory['findings'])} money finding(s))")

    if args.do_print:
        print("\n" + report)

    if args.emit_findings and advisory["findings"]:
        _emit(advisory["findings"])


def _emit(findings: list[dict]) -> None:
    """Persist money findings so the existing notifier pushes the criticals."""
    try:
        from memory.finding_store import FindingStore, compute_finding_id
        fs = FindingStore(_DB_PATH)
        fs.connect()
        try:
            for f in findings:
                fid = compute_finding_id(
                    target_id=f["target_id"], finding_type=f["finding_type"],
                    resource=f["resource"], scope=f["scope"],
                    collector_type=f["collector_type"],
                )
                fs.upsert(
                    finding_id=fid, target_id=f["target_id"],
                    finding_type=f["finding_type"], resource=f["resource"],
                    scope=f["scope"], severity=f["severity"].upper(),
                    collector_type=f["collector_type"], title=f["title"],
                    description=f.get("description", ""),
                    recommendation=f.get("recommendation", ""),
                    evidence=f.get("evidence", []), confidence=f.get("confidence", 1.0),
                    four_w=f.get("four_w"),
                )
            print(f"Emitted {len(findings)} finding(s) to the FindingStore.")
        finally:
            fs.disconnect()
    except Exception as exc:  # never let emission break the advisory
        print(f"WARN could not emit findings: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
