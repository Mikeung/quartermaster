"""Economic observability — Phase A.

Reads spend from the append-only llm_events store (populated by the spend-ledger
importer and/or any project that emits LLM events) and produces advisory findings
about cost. Every threshold is a fixed constant in config.observability_config;
every finding records the exact numbers and the comparison that fired it.

The system answers, for spend:
  - How much did it cost?        (window total, per provider/workflow/project)
  - Which agent caused it?        (workflow + project attribution)
  - Was the spend expected?       (spike vs trailing baseline; burn rate; runaway)

Finding types: economic_anomaly, spend_spike, abnormal_burn_rate, runaway_agent_cost.
Supported providers: Claude (anthropic), Gemini/Google, OpenAI.

This layer never changes spending or touches provider accounts. Advisory only.
"""

from __future__ import annotations

import statistics
from typing import Any

from config import observability_config as cfg
from memory.llm_store import LLMEventStore

COLLECTOR_TYPE = "economic_observability"
TARGET_ID = "economic"
SCOPE = "spend"


def _finding(
    *,
    finding_type: str,
    resource: str,
    severity: str,
    title: str,
    recommendation: str,
    evidence: list[str],
    four_w: dict | None = None,
) -> dict[str, Any]:
    return {
        "target_id": TARGET_ID,
        "finding_type": finding_type,
        "resource": resource,
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": severity,
        "title": title,
        "description": title,
        "recommendation": recommendation,
        "evidence": evidence,
        "confidence": 1.0,
        "four_w": four_w or {},
    }


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def summarize_spend(store: LLMEventStore, window_hours: int = cfg.WINDOW_HOURS) -> dict[str, Any]:
    """Structured spend summary for the report layer (no thresholds applied)."""
    bounds = store.window_spend_bounds(window_hours)
    by_provider = store.aggregate_by_provider(window_hours)
    by_workflow = store.aggregate_workflow_spend(window_hours)
    by_project = store.aggregate_project_spend(window_hours)
    span = bounds.get("active_span_hours", 0.0) or 0.0
    total = bounds.get("total_cost", 0.0)
    burn = round(total / span, 2) if span > 0 else 0.0
    return {
        "window_hours": window_hours,
        "total_cost": total,
        "event_count": bounds.get("event_count", 0),
        "active_span_hours": span,
        "burn_rate_usd_per_hr": burn,
        "by_provider": by_provider,
        "by_workflow": by_workflow,
        "by_project": by_project,
        # 4W "cost/day, model/day, agent/day" breakdowns
        "by_model": store.aggregate_cost_by_model(window_hours),
        "cost_by_day": store.aggregate_daily_totals(window_days=7),
        "model_by_day": store.aggregate_daily_by_model(window_days=7),
        "agent_by_day": store.aggregate_daily_by_agent(window_days=7),
    }


def detect_economic_findings(
    store: LLMEventStore, window_hours: int = cfg.WINDOW_HOURS
) -> list[dict[str, Any]]:
    """Deterministic economic findings over the spend window."""
    findings: list[dict[str, Any]] = []
    bounds = store.window_spend_bounds(window_hours)
    total = bounds.get("total_cost", 0.0)
    events = bounds.get("event_count", 0)
    if events == 0 or total <= 0:
        return findings  # no spend observed → nothing to surface

    span = bounds.get("active_span_hours", 0.0) or 0.0

    # --- 4W window context (WHO/WHEN/WHICH/COST shared by economic findings) ---
    from cognition.cost_accountability import economic_cost, economic_who
    from cognition.four_w import classify_llm_activity, make_4w
    providers_list = [p.get("provider") for p in store.aggregate_by_provider(window_hours) if p.get("provider")]
    models_list = [m.get("model") for m in store.aggregate_cost_by_model(window_hours) if m.get("model")]
    projects_list = [p.get("project_id") for p in store.aggregate_project_spend(window_hours) if p.get("project_id")]
    win_start, win_end = bounds.get("first_ts"), bounds.get("last_ts")
    # Cumulative cost = the full window total; every economic finding carries it
    # so the operator always sees the running total, not just the local slice.
    window_total = total

    def _window_who_agent():
        # Single contributing project → attribute to it; several → the list (WHO
        # is still determinable — it is all of them); none → UNKNOWN via builder.
        if len(projects_list) == 1:
            return projects_list[0]
        return projects_list or None

    def _econ_4w(activity_type, task, *, repository=None, subsystem=None, workflow=None,
                 agent=None, start=None, end=None, duration=None, providers=None, models=None,
                 service=None, spend=None, burn_rate=None, automation=None):
        # Economic activity always has a WHERE: the project repo, or the LLM/API
        # spend surface. Guarantees a populated 4W (no fallback derivation).
        if service is None and repository is None:
            service = "LLM/API spend"
        who_agent = agent if agent is not None else _window_who_agent()
        return make_4w(
            who=economic_who(who_agent, automation or workflow),
            what={"activity_type": activity_type, "task": task, "workflow": workflow},
            where={"repository": repository, "subsystem": subsystem,
                   "service": service, "component": workflow or repository},
            when={"start": start or win_start, "end": end or win_end, "duration": duration,
                  "first_seen": win_start, "last_seen": win_end},
            which={"agent": who_agent,
                   "provider": providers if providers is not None else providers_list,
                   "model": models if models is not None else models_list,
                   "workflow": workflow, "service": None},
            cost=economic_cost(
                spend=spend if spend is not None else window_total,
                burn_rate=burn_rate,
                cumulative_cost=window_total,
            ),
        )

    # --- Baseline from prior full days (exclude the current rolling window) ---
    daily = store.aggregate_daily_totals(window_days=cfg.SPEND_SPIKE_BASELINE_DAYS + 1)
    prior_day_costs = [
        float(r.get("total_estimated_cost") or 0.0) for r in daily[:-1]
    ] if len(daily) > 1 else []
    baseline = statistics.median(prior_day_costs) if prior_day_costs else None

    # --- 1. spend_spike / absolute daily band ---
    spike_evidence = [
        f"window spend {_usd(total)} over {window_hours}h across {events} events",
    ]
    ratio = None
    if baseline is not None and baseline > 0:
        ratio = total / baseline
        spike_evidence.append(
            f"trailing median daily spend {_usd(baseline)} (×{ratio:.1f}); "
            f"spike factor ≥{cfg.SPEND_SPIKE_FACTOR}"
        )
    fired_by_ratio = (
        baseline is not None and baseline > 0
        and ratio is not None and ratio >= cfg.SPEND_SPIKE_FACTOR
        and total >= cfg.SPEND_SPIKE_MIN_USD
    )
    fired_by_absolute = total >= cfg.DAILY_SPEND_WARN_USD
    if fired_by_ratio or fired_by_absolute:
        if total >= cfg.DAILY_SPEND_HIGH_USD:
            sev = "HIGH"
        else:
            sev = "MEDIUM"
        title = f"Spend spike: {_usd(total)} in {window_hours}h"
        if ratio is not None:
            title += f" (×{ratio:.1f} baseline)"
        findings.append(_finding(
            finding_type="spend_spike",
            resource="daily_spend",
            severity=sev,
            title=title,
            recommendation="Confirm the increased spend was expected; review the dominant provider/workflow below.",
            evidence=spike_evidence,
            four_w=_econ_4w("economic: spend spike", title,
                            repository=(projects_list[0] if len(projects_list) == 1 else None)),
        ))

    # --- 2. abnormal_burn_rate ---
    effective_span = span if span > 0 else float(window_hours)
    burn = total / effective_span if effective_span > 0 else 0.0
    if burn >= cfg.BURN_RATE_WARN_USD_PER_HR:
        sev = "HIGH" if burn >= cfg.BURN_RATE_HIGH_USD_PER_HR else "MEDIUM"
        findings.append(_finding(
            finding_type="abnormal_burn_rate",
            resource="burn_rate",
            severity=sev,
            title=f"Burn rate {_usd(burn)}/hr over {effective_span:.1f}h active",
            recommendation="Sustained spend rate is elevated — verify no unattended loop is driving it.",
            evidence=[
                f"{_usd(total)} over {effective_span:.1f}h active span = {_usd(burn)}/hr",
                f"thresholds: warn ≥{_usd(cfg.BURN_RATE_WARN_USD_PER_HR)}/hr, high ≥{_usd(cfg.BURN_RATE_HIGH_USD_PER_HR)}/hr",
            ],
            four_w=_econ_4w("economic: abnormal burn rate", f"{_usd(burn)}/hr sustained",
                            duration=f"{effective_span:.1f}h", spend=total, burn_rate=burn),
        ))

    # --- 3. runaway_agent_cost ---
    workflows = store.aggregate_workflow_spend(window_hours)
    if workflows:
        top = workflows[0]
        top_cost = top.get("total_cost", 0.0)
        share = top_cost / total if total > 0 else 0.0
        top_span = top.get("active_span_hours", 0.0) or 0.0
        if (
            top_cost >= cfg.RUNAWAY_MIN_USD
            and share >= cfg.RUNAWAY_SINGLE_WORKFLOW_SHARE
            and top_span >= cfg.RUNAWAY_MIN_HOURS
        ):
            proj = top.get("project_id") or "unknown"
            proj_attr = top.get("project_id")  # None when unattributed → WHO=UNKNOWN, gated
            wf = top.get("workflow") or "unknown"
            subsystem = wf.split(".")[0] if "." in wf else None
            findings.append(_finding(
                finding_type="runaway_agent_cost",
                resource=f"{proj}:{wf}",
                severity="HIGH",
                title=f"Runaway cost: {wf} = {_usd(top_cost)} ({share:.0%}) over {top_span:.1f}h",
                recommendation="One workflow dominated spend across a long uninterrupted run — confirm it was intended; consider a budget cap or kill-switch.",
                evidence=[
                    f"workflow '{wf}' (project {proj}): {_usd(top_cost)} = {share:.0%} of {_usd(total)}",
                    f"uninterrupted span {top_span:.1f}h, {top.get('event_count', 0)} calls",
                    f"thresholds: ≥{_usd(cfg.RUNAWAY_MIN_USD)}, share ≥{cfg.RUNAWAY_SINGLE_WORKFLOW_SHARE:.0%}, span ≥{cfg.RUNAWAY_MIN_HOURS}h",
                ],
                four_w=_econ_4w(
                    "economic: runaway agent cost",
                    f"{classify_llm_activity(wf)} ({wf})",
                    repository=proj_attr, subsystem=subsystem, workflow=wf, agent=proj_attr,
                    automation=wf,
                    start=top.get("first_ts"), end=top.get("last_ts"),
                    duration=f"{top_span:.1f}h",
                    spend=top_cost,
                    burn_rate=round(top_cost / top_span, 2) if top_span > 0 else None,
                ),
            ))

    # --- 4. economic_anomaly (new spender vs baseline, or cold-start baseline) ---
    if baseline is None:
        # No prior days: we cannot yet call anything a deviation. Surface the
        # baseline itself once, honestly labelled, so spend is never invisible.
        provs = [p.get("provider") for p in store.aggregate_by_provider(window_hours)]
        findings.append(_finding(
            finding_type="economic_anomaly",
            resource="baseline",
            severity="MEDIUM",
            title=f"First economic baseline established: {_usd(total)} across {len(provs)} provider(s)",
            recommendation="No prior spend history existed — this window is now the baseline. Confirm it looks right.",
            evidence=[
                f"{_usd(total)} over {window_hours}h, providers: {', '.join(str(p) for p in provs)}",
                "deviation detection activates once ≥1 prior day of spend exists",
            ],
            four_w=_econ_4w("economic: anomaly", f"first baseline {_usd(total)}"),
        ))
    else:
        prior_providers = _baseline_providers(store)
        for p in store.aggregate_by_provider(window_hours):
            prov = p.get("provider", "")
            cost = float(p.get("total_estimated_cost") or 0.0)
            if cost >= cfg.ANOMALY_NEW_SPENDER_MIN_USD and prov not in prior_providers:
                findings.append(_finding(
                    finding_type="economic_anomaly",
                    resource=f"new_spender:{prov}",
                    severity="MEDIUM",
                    title=f"New spender: {prov} {_usd(cost)} (absent from baseline)",
                    recommendation="A provider that was not spending before now is — confirm the new workload is expected.",
                    evidence=[
                        f"{prov}: {_usd(cost)} this window, not present in trailing {cfg.SPEND_SPIKE_BASELINE_DAYS}d baseline",
                    ],
                    four_w=_econ_4w("economic: anomaly", f"new spender {prov} {_usd(cost)}",
                                    providers=[prov], service=f"{prov} API", spend=cost),
                ))

    # --- 5. unknown_cost_owner (Phase 3) ---
    # Spend that cannot be attributed to any project_id/agent. The operator must
    # never discover paid consumption before the system can explain ownership.
    from cognition.cost_accountability import unknown_cost_owner_finding
    attributed = sum(
        float(r.get("total_cost") or 0.0)
        for r in store.aggregate_project_spend(window_hours)
        if r.get("project_id")
    )
    unattributed = round(total - attributed, 2)
    if unattributed >= cfg.UNKNOWN_COST_OWNER_MIN_USD:
        findings.append(unknown_cost_owner_finding(
            total_cost=unattributed,
            window_hours=window_hours,
            providers=[str(p) for p in providers_list],
            models=[str(m) for m in models_list],
            first_ts=win_start,
            last_ts=win_end,
            cumulative_cost=window_total,
        ))

    # --- Phase 7: recommendation accountability gate ---
    # No economic recommendation survives without full who/what/where/when/which/
    # cost. Where a core economic finding lacks it, suppress its recommendation
    # and emit an explicit insufficient_context finding naming the gap.
    findings = _apply_recommendation_gate(findings)

    return findings


# Core economic types whose recommendations are gated on full accountability.
# unknown_cost_owner / insufficient_context are exempt — the first IS the
# missing-owner signal (and carries its own actionable recommendation), the
# second is the gate's own output.
_GATED_TYPES = frozenset({
    "spend_spike", "abnormal_burn_rate", "runaway_agent_cost", "economic_anomaly",
})


def _apply_recommendation_gate(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Withhold any gated economic recommendation lacking full accountability."""
    from cognition.cost_accountability import (
        has_full_accountability,
        insufficient_context_finding,
        missing_dimensions,
    )

    extra: list[dict[str, Any]] = []
    for f in findings:
        if f.get("finding_type") not in _GATED_TYPES:
            continue
        if not f.get("recommendation"):
            continue
        if has_full_accountability(f.get("four_w")):
            continue
        missing = missing_dimensions(f.get("four_w"))
        f["recommendation"] = (
            "Recommendation withheld — incomplete cost accountability "
            f"(missing: {', '.join(missing)})."
        )
        extra.append(insufficient_context_finding(source=f, missing=missing))
    return findings + extra


def _baseline_providers(store: LLMEventStore) -> set[str]:
    """Providers ESTABLISHED before the current window.

    A provider is established if it has events in the baseline window beyond those
    in the most recent WINDOW_HOURS (i.e. it was already spending before now).
    Used to distinguish a genuinely new spender from a continuing one.
    """
    full = {
        p.get("provider"): int(p.get("event_count") or 0)
        for p in store.aggregate_by_provider(cfg.SPEND_SPIKE_BASELINE_DAYS * 24)
    }
    recent = {
        p.get("provider"): int(p.get("event_count") or 0)
        for p in store.aggregate_by_provider(cfg.WINDOW_HOURS)
    }
    return {prov for prov, n in full.items() if n > recent.get(prov, 0)}
