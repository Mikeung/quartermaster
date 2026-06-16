"""Gather live spend evidence and build the cost advisory (importable runner).

Used by the `qm cost` CLI command and by scripts/cost_advisor_report.py. Read-only.
Paths resolve relative to the current working directory (the project root), so the
command works from a clone or an installed package and degrades gracefully when the
store/config are absent (empty advisory rather than an error).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cognition import cost_advisor, cost_investigation
from config import observability_config as cfg
from economics.connection_evidence import collect_outbound_connections
from economics.key_registry import load_budget, load_key_labels
from economics.provider_usage import read_all_provider_usage
from memory.llm_store import LLMEventStore

DB_PATH = "data/operational_memory.db"
CONFIG_PATH = Path("config/cost_advisor.yml")


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
    """Sum spend over the declared budget period/scope from the ledger."""
    if not budget:
        return None
    period = budget.get("period", "monthly")
    if period == "daily":
        daily = store.aggregate_daily_totals(window_days=2)
        today = now.strftime("%Y-%m-%d")
        return next((float(d.get("total_estimated_cost") or 0.0)
                     for d in daily if d.get("day") == today), 0.0)
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

    Returns {"advisory", "investigations", "key_errors"}. Read-only; the
    provider-usage reader degrades when no usage key is configured, and a missing
    store/config yields an empty advisory rather than an error.
    """
    now = now or datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    start = now.replace(day=1).strftime("%Y-%m-%d")

    key_labels, errors = load_key_labels(CONFIG_PATH)
    budget = load_budget(CONFIG_PATH)
    provider_usage = read_all_provider_usage(start_day=start, end_day=today)

    store = LLMEventStore(DB_PATH)
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
