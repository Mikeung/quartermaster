#!/usr/bin/env python3
"""Cost advisor — gather real spend evidence, build the advisory, write the artifact.

Read-only and advisory. Gathers:
  - provider account usage (env-only key; degrades to ledger when unconfigured),
  - the self-reported ledger (data/spend/ → llm_events),
  - the operator's key→agent labels + human-declared budget,
  - on-box outbound connections (for the Unattributed investigation),
then builds the advisory + investigations and writes reports/economics/COST_ADVISOR.md.

Usage:
    python scripts/cost_advisor_report.py [--window-hours 24] [--print] [--emit-findings]

--emit-findings persists the money findings via the FindingStore so the existing
real-time notifier pushes the intrinsic-critical ones (P0) — the advisor itself
never notifies or spends.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from cognition import cost_advisor, cost_investigation  # noqa: E402
from config import observability_config as cfg  # noqa: E402
from economics.connection_evidence import collect_outbound_connections  # noqa: E402
from economics.key_registry import load_budget, load_key_labels  # noqa: E402
from economics.provider_usage import read_all_provider_usage  # noqa: E402
from memory.llm_store import LLMEventStore  # noqa: E402
from reports.cost_advisor_report import render_cost_advisor_report  # noqa: E402

_DB_PATH = str(PROJECT_ROOT / "data" / "operational_memory.db")
_CONFIG = PROJECT_ROOT / "config" / "cost_advisor.yml"
_OUT = PROJECT_ROOT / "reports" / "economics" / "COST_ADVISOR.md"


def _normalise_ledger(store: LLMEventStore, window_hours: int) -> dict:
    """Shape the llm_store aggregates into the cost_advisor ledger contract."""
    by_provider = [
        {"provider": r.get("provider"),
         "cost_usd": float(r.get("total_estimated_cost") or 0.0),
         "event_count": int(r.get("event_count") or 0)}
        for r in store.aggregate_by_provider(window_hours)
    ]
    by_project = [
        {"project_id": r.get("project_id"),
         "cost_usd": float(r.get("total_cost") or 0.0),
         "event_count": int(r.get("event_count") or 0),
         "first_ts": r.get("first_ts"), "last_ts": r.get("last_ts")}
        for r in store.aggregate_project_spend(window_hours)
    ]
    by_day = [
        {"day": r.get("day"), "cost_usd": float(r.get("total_estimated_cost") or 0.0)}
        for r in store.aggregate_daily_totals(window_days=cfg.SPEND_SPIKE_BASELINE_DAYS)
    ]
    bounds = store.window_spend_bounds(window_hours)
    return {
        "total_cost": float(bounds.get("total_cost") or 0.0),
        "by_provider": by_provider, "by_project": by_project, "by_day": by_day,
    }


def _budget_period_spend(store: LLMEventStore, budget: dict, now: datetime) -> float | None:
    """Sum spend over the declared budget period/scope from the ledger (calendar-aligned)."""
    if not budget:
        return None
    period = budget.get("period", "monthly")
    if period == "daily":
        daily = store.aggregate_daily_totals(window_days=2)
        today = now.strftime("%Y-%m-%d")
        return next((float(d.get("total_estimated_cost") or 0.0)
                     for d in daily if d.get("day") == today), 0.0)
    # monthly: sum days within the current calendar month
    daily = store.aggregate_daily_totals(window_days=31)
    month = now.strftime("%Y-%m")
    return round(sum(float(d.get("total_estimated_cost") or 0.0)
                     for d in daily if str(d.get("day", "")).startswith(month)), 4)


def _process_to_agent() -> dict[str, str]:
    """Map process name → owning agent from the project context registry."""
    try:
        from config.project_context import SERVICE_OWNERSHIP
        return {name: own.project_id for name, own in SERVICE_OWNERSHIP.items()
                if getattr(own, "project_id", None)}
    except Exception:  # registry shape drift must never break the advisor
        return {}


def build_live(window_hours: int = cfg.WINDOW_HOURS, now: datetime | None = None) -> dict:
    """Gather live evidence and build the advisory + investigations.

    Returns {"advisory", "investigations", "key_errors"}. Reusable by both the
    CLI and the scheduler. Read-only; the provider-usage reader degrades when no
    usage key is configured.
    """
    now = now or datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    start = now.replace(day=1).strftime("%Y-%m-%d")

    key_labels, errors = load_key_labels(_CONFIG)
    budget = load_budget(_CONFIG)
    provider_usage = read_all_provider_usage(start_day=start, end_day=today)

    store = LLMEventStore(_DB_PATH)
    store.connect()
    try:
        ledger = _normalise_ledger(store, window_hours)
        budget_spend = _budget_period_spend(store, budget, now)
    finally:
        store.disconnect()

    advisory = cost_advisor.build_advisory(
        provider_usage=provider_usage, ledger=ledger, key_labels=key_labels,
        budget=budget, budget_spend_usd=budget_spend,
        window_hours=window_hours, now=now,
    )
    connections = collect_outbound_connections(now=now)
    investigations = cost_investigation.investigate_advisory(
        advisory, connections, process_to_agent=_process_to_agent(),
    )
    return {"advisory": advisory, "investigations": investigations, "key_errors": errors}


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
