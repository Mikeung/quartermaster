"""Cost advisor — the deterministic brain of the Economics slot.

Given spend evidence already gathered (provider account usage + the self-reported
ledger), the operator's key→agent labels, and a human-declared budget, it builds:

  1. WHOLE VIEW   — total spend per provider (the headline), each tagged with its
                    source (provider account usage > self-reported ledger) so the
                    operator always knows how trustworthy the number is.
  2. ATTRIBUTION  — spend bound to graph nodes by EVIDENCE: a provider key that
                    maps 1:1 to an agent, or an agent's own parseable ledger.
                    Everything else is honestly "Unattributed" — never guessed.
  3. TREND        — spend over time + direction.
  4. BUDGET       — warn as a human-declared budget is approached; money-critical
                    when exceeded.

Pure and deterministic: same inputs → same output. No I/O, no clock beyond the
`now` passed in, no network, no graph access. It observes and explains spend; it
never throttles, pauses, or spends. The builder (reports/scripts) gathers the
inputs; this module only reasons.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cognition.cost_accountability import economic_cost, economic_who
from cognition.four_w import make_4w
from config import observability_config as cfg
from economics.key_registry import KeyLabel, resolve_key_owner
from economics.provider_usage import ProviderUsageResult

TARGET_ID = "economic"
SCOPE = "spend"
COLLECTOR_TYPE = "cost_advisor"

# Source provenance → confidence in the headline number.
_SOURCE_CONFIDENCE = {
    "provider_account_usage": "High",
    "self_reported_ledger": "Medium",
    "unavailable": "Low",
}


def _agent_node(project_id: str) -> str:
    """Graph builder_node_id for a ledger project_id (agents are repo nodes)."""
    return f"repo:{project_id}"


# ---------------------------------------------------------------------------
# Whole view + attribution
# ---------------------------------------------------------------------------

def _provider_total_from_ledger(provider: str, by_provider: list[dict[str, Any]]) -> float:
    for r in by_provider:
        if str(r.get("provider", "")).lower() == provider.lower():
            return round(float(r.get("cost_usd") or 0.0), 4)
    return 0.0


def _attribute_provider(
    provider: str,
    usage: ProviderUsageResult | None,
    ledger: dict[str, Any],
    key_labels: list[KeyLabel],
) -> tuple[float, str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (provider_total, source, attributed, unattributed) for one provider.

    Evidence precedence per the spec:
      - account usage with a per-key split → attribute via 1:1 key labels;
        unlabelled or shared keys become Unattributed buckets.
      - otherwise → attribute via the agent's self-reported ledger project_id;
        ledger spend with no project_id becomes an Unattributed bucket.
    """
    attributed: list[dict[str, Any]] = []
    unattributed: list[dict[str, Any]] = []

    if usage is not None and usage.available and usage.per_key:
        source = "provider_account_usage"
        for key_id, cost in sorted(usage.per_key.items(), key=lambda kv: -kv[1]):
            if cost <= 0:
                continue
            hint = next((r.key_hint for r in usage.records if r.key_id == key_id), "")
            label = resolve_key_owner(provider, key_id, key_labels)
            if label and not label.shared:
                attributed.append({
                    "agent": label.agent, "agent_node": label.agent,
                    "provider": provider, "cost_usd": round(cost, 4),
                    "basis": "key_1to1", "confidence": "High",
                    "evidence": f"{provider} key {hint or key_id} labelled 1:1 → {label.agent}: {label.evidence}",
                })
            else:
                reason = ("shared key — cannot split 1:1; isolate the agent's key to confirm"
                          if (label and label.shared)
                          else "unlabelled provider key — owner not declared")
                unattributed.append({
                    "provider": provider, "key_id": key_id, "key_hint": hint,
                    "cost_usd": round(cost, 4), "reason": reason,
                    "shared_label": label.agent if (label and label.shared) else None,
                    "when_first": _usage_first_day(usage, key_id),
                    "when_last": _usage_last_day(usage, key_id),
                })
        return usage.total_cost, source, attributed, unattributed

    # Degraded / no per-key split → self-reported ledger attribution.
    source = "self_reported_ledger"
    total = _provider_total_from_ledger(provider, ledger.get("by_provider", []))
    # The ledger attributes by project across all providers; we cannot split a
    # single project's spend per provider from these aggregates, so provider-mode
    # attribution is reported at the ledger-wide level by the caller. Here we only
    # surface the provider total; project attribution is assembled once, below.
    return total, source, attributed, unattributed


def _usage_first_day(usage: ProviderUsageResult, key_id: str) -> str | None:
    days = sorted(r.day for r in usage.records if r.key_id == key_id and r.day)
    return days[0] if days else None


def _usage_last_day(usage: ProviderUsageResult, key_id: str) -> str | None:
    days = sorted(r.day for r in usage.records if r.key_id == key_id and r.day)
    return days[-1] if days else None


def _ledger_attribution(ledger: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attribute ledger spend by project_id (agent self-logged). No project → Unattributed."""
    attributed: list[dict[str, Any]] = []
    unattributed: list[dict[str, Any]] = []
    for r in ledger.get("by_project", []):
        pid = (r.get("project_id") or "").strip()
        cost = round(float(r.get("cost_usd") or 0.0), 4)
        if cost <= 0:
            continue
        if pid:
            attributed.append({
                "agent": pid, "agent_node": _agent_node(pid),
                "provider": "ledger", "cost_usd": cost,
                "basis": "agent_self_logged", "confidence": "Medium",
                "evidence": f"agent '{pid}' logged this spend itself in data/spend/ ({r.get('event_count', 0)} events)",
            })
        else:
            unattributed.append({
                "provider": "ledger", "key_id": "", "key_hint": "",
                "cost_usd": cost,
                "reason": "ledger spend carries no project_id — emitter did not tag an owner",
                "shared_label": None,
                "when_first": r.get("first_ts"), "when_last": r.get("last_ts"),
            })
    return attributed, unattributed


# ---------------------------------------------------------------------------
# Findings (money) — reuse existing finding types + the money push category
# ---------------------------------------------------------------------------

def _unattributed_finding(bucket: dict[str, Any], window_hours: int, total_window: float) -> dict[str, Any]:
    """HIGH unknown_cost_owner finding scoped to one Unattributed bucket.

    finding_type is the existing 'unknown_cost_owner' (already P0 + intrinsic
    money), so it pages fast. The resource is bucket-specific so distinct keys
    are distinct findings, not collapsed into one.
    """
    from cognition.four_w import UNKNOWN

    prov = bucket.get("provider", "unknown")
    key_hint = bucket.get("key_hint") or bucket.get("key_id") or "no-key-split"
    cost = float(bucket.get("cost_usd") or 0.0)
    resource = f"unattributed:{prov}:{key_hint}"
    four_w = make_4w(
        who=economic_who(None),
        what={"activity_type": "economic: unattributed spend",
              "task": f"${cost:,.2f} via {prov} key {key_hint} with no owner", "workflow": None},
        where={"repository": None, "subsystem": None,
               "service": f"{prov} API spend", "component": key_hint},
        when={"start": bucket.get("when_first"), "end": bucket.get("when_last"),
              "duration": None, "first_seen": bucket.get("when_first"),
              "last_seen": bucket.get("when_last")},
        which={"agent": UNKNOWN, "provider": [prov], "model": [UNKNOWN],
               "workflow": None, "service": None},
        cost=economic_cost(spend=cost, cumulative_cost=total_window),
    )
    return {
        "target_id": TARGET_ID,
        "finding_type": "unknown_cost_owner",
        "resource": resource,
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": "HIGH",
        "title": f"Unattributed spend: ${cost:,.2f} on {prov} (key {key_hint})",
        "description": f"${cost:,.2f} of {prov} spend cannot be attributed to an agent.",
        "recommendation": (
            f"Investigate this bucket (see the cost-advisor investigation): {bucket.get('reason', '')}. "
            "Label the key once to attribute it permanently, or isolate a shared key."
        ),
        "evidence": [
            f"${cost:,.2f} on {prov}, key {key_hint}, over {window_hours}h",
            f"reason: {bucket.get('reason', 'owner not determinable')}",
            f"threshold: ≥${cfg.UNATTRIBUTED_INVESTIGATE_MIN_USD:,.2f} opens an investigation",
        ],
        "confidence": 1.0,
        "four_w": four_w,
    }


def _budget_finding(budget_view: dict[str, Any], total_window: float) -> dict[str, Any] | None:
    state = budget_view.get("state")
    if state not in ("approaching", "exceeded"):
        return None
    limit = budget_view["limit_usd"]
    spend = budget_view["spend_usd"]
    frac = budget_view["fraction"]
    period = budget_view["period"]
    scope = budget_view["scope"]
    exceeded = state == "exceeded"
    ftype = "budget_exceeded" if exceeded else "budget_approaching"
    sev = "HIGH" if exceeded else "MEDIUM"
    verb = "exceeded" if exceeded else f"at {frac:.0%} of"
    four_w = make_4w(
        who=economic_who(None),
        what={"activity_type": f"economic: budget {state}",
              "task": f"{period} {scope} spend ${spend:,.2f} vs budget ${limit:,.2f}", "workflow": None},
        where={"repository": None, "subsystem": None, "service": "LLM/API spend", "component": scope},
        when={"start": None, "end": None, "duration": None, "first_seen": None, "last_seen": None},
        which={"agent": None, "provider": [scope] if scope != "all" else [], "model": [],
               "workflow": None, "service": None},
        cost=economic_cost(spend=spend, cumulative_cost=total_window),
    )
    return {
        "target_id": TARGET_ID,
        "finding_type": ftype,
        "resource": f"budget:{scope}:{period}",
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": sev,
        "title": f"Budget {verb} declared ${limit:,.2f} {period} ({scope}): ${spend:,.2f}",
        "description": f"{period.capitalize()} {scope} spend is ${spend:,.2f} against a declared budget of ${limit:,.2f}.",
        "recommendation": (
            "Declared budget exceeded — review and curb or re-budget the spend deliberately."
            if exceeded else
            f"Spend has reached {frac:.0%} of the declared {period} budget — decide before it is exceeded."
        ),
        "evidence": [
            f"{period} {scope} spend ${spend:,.2f} / budget ${limit:,.2f} = {frac:.0%}",
            f"budget is human-declared (config/cost_advisor.yml); warn fraction ≥{cfg.BUDGET_APPROACHING_FRACTION:.0%}",
        ],
        "confidence": 1.0,
        "four_w": four_w,
    }


# ---------------------------------------------------------------------------
# Trend + budget views
# ---------------------------------------------------------------------------

def _trend(by_day: list[dict[str, Any]]) -> dict[str, Any]:
    days = [d for d in by_day if d.get("day")]
    costs = [round(float(d.get("cost_usd") or 0.0), 4) for d in days]
    if len(costs) < 2:
        return {"by_day": days, "direction": "insufficient",
                "latest": costs[-1] if costs else 0.0, "baseline": None}
    latest = costs[-1]
    baseline = round(sum(costs[:-1]) / len(costs[:-1]), 4)
    if baseline <= 0:
        direction = "rising" if latest > 0 else "flat"
    elif latest >= baseline * 1.2:
        direction = "rising"
    elif latest <= baseline * 0.8:
        direction = "falling"
    else:
        direction = "flat"
    return {"by_day": days, "direction": direction, "latest": latest, "baseline": baseline}


def _budget_view(budget: dict[str, Any], spend_usd: float | None) -> dict[str, Any]:
    if not budget:
        return {"declared": False, "state": "inactive"}
    limit = float(budget["limit_usd"])
    spend = float(spend_usd or 0.0)
    frac = round(spend / limit, 4) if limit > 0 else 0.0
    if frac >= 1.0:
        state = "exceeded"
    elif frac >= cfg.BUDGET_APPROACHING_FRACTION:
        state = "approaching"
    else:
        state = "ok"
    return {
        "declared": True, "period": budget["period"], "scope": budget["scope"],
        "limit_usd": round(limit, 2), "spend_usd": round(spend, 2),
        "fraction": frac, "state": state,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_advisory(
    *,
    provider_usage: dict[str, ProviderUsageResult],
    ledger: dict[str, Any],
    key_labels: list[KeyLabel] | None = None,
    budget: dict[str, Any] | None = None,
    budget_spend_usd: float | None = None,
    window_hours: int = cfg.WINDOW_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the full cost advisory. Pure; never raises on well-formed input."""
    key_labels = key_labels or []
    budget = budget or {}
    generated_at = (now.isoformat() if now else None)

    # --- per-provider whole view + attribution ---
    providers_view: list[dict[str, Any]] = []
    attributed: list[dict[str, Any]] = []
    unattributed: list[dict[str, Any]] = []
    ledger_mode_providers: list[str] = []

    seen: set[str] = set()
    candidate_providers = list(cfg.SUPPORTED_PROVIDERS)
    for r in ledger.get("by_provider", []):
        p = str(r.get("provider", "")).lower()
        if p and p not in candidate_providers:
            candidate_providers.append(p)

    for provider in candidate_providers:
        provider = provider.lower()
        if provider in seen:
            continue
        seen.add(provider)
        usage = provider_usage.get(provider)
        total, source, p_attr, p_unattr = _attribute_provider(provider, usage, ledger, key_labels)
        if total <= 0 and source != "provider_account_usage":
            continue  # no spend on this provider from any source → skip
        reason = ""
        if source == "self_reported_ledger" and usage is not None and not usage.available:
            reason = usage.reason
            ledger_mode_providers.append(provider)
        elif source == "self_reported_ledger":
            ledger_mode_providers.append(provider)
        providers_view.append({
            "provider": provider, "cost_usd": round(total, 4), "source": source,
            "confidence": _SOURCE_CONFIDENCE.get(source, "Low"), "reason": reason,
        })
        attributed.extend(p_attr)
        unattributed.extend(p_unattr)

    # If any provider is in ledger mode, attribute the ledger's spend by project
    # ONCE (the ledger aggregates are not split per provider).
    if ledger_mode_providers:
        l_attr, l_unattr = _ledger_attribution(ledger)
        attributed.extend(l_attr)
        unattributed.extend(l_unattr)

    total_usd = round(sum(p["cost_usd"] for p in providers_view), 4)
    attributed_total = round(sum(a["cost_usd"] for a in attributed), 4)
    unattributed_total = round(sum(u["cost_usd"] for u in unattributed), 4)

    # --- trend + budget ---
    trend = _trend(ledger.get("by_day", []))
    budget_view = _budget_view(budget, budget_spend_usd)

    # --- findings (money) ---
    findings: list[dict[str, Any]] = []
    for bucket in unattributed:
        if float(bucket.get("cost_usd") or 0.0) >= cfg.UNATTRIBUTED_INVESTIGATE_MIN_USD:
            findings.append(_unattributed_finding(bucket, window_hours, total_usd))
    bf = _budget_finding(budget_view, total_usd)
    if bf:
        findings.append(bf)

    return {
        "generated_at": generated_at,
        "window_hours": window_hours,
        "whole_view": {"total_usd": total_usd, "providers": providers_view},
        "attribution": {
            "attributed": attributed,
            "unattributed": unattributed,
            "attributed_total": attributed_total,
            "unattributed_total": unattributed_total,
        },
        "trend": trend,
        "budget": budget_view,
        "findings": findings,
    }
