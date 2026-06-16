"""Cost accountability policy — the economic half of the 4W/6W model.

Created by the Cost Accountability hotfix (2026-05-30) after a production
failure: the system detected Gemini spend but could not, as structured data,
say WHO spent it, or hold the COST in first-class fields.

This module is the deterministic policy layer that the economic detector uses
to guarantee every paid-activity finding answers:

    WHO / WHAT / WHERE / WHEN / WHICH / COST

It provides:
  - owner resolution            (project/agent → accountable human)
  - WHO and COST builders        (economic_who / economic_cost)
  - the accountability gate       (has_full_accountability / missing_dimensions)
  - the unknown_cost_owner finding (spend exists, owner cannot be determined)
  - the insufficient_context finding (recommendation withheld for lack of 4W)

Advisory and observational only — nothing here changes spend or touches any
provider account. Same inputs → same outputs.
"""

from __future__ import annotations

from typing import Any

from cognition.four_w import UNKNOWN, make_cost, make_who
from config import observability_config as cfg

COLLECTOR_TYPE = "economic_observability"
TARGET_ID = "economic"
SCOPE = "spend"


# ---------------------------------------------------------------------------
# Owner resolution + WHO / COST builders
# ---------------------------------------------------------------------------

def resolve_owner(agent: str | None) -> str:
    """Map an agent/project to its accountable human owner.

    Configured owners win; otherwise the agent name itself is the best-effort
    owner; a missing agent resolves to the explicit UNKNOWN sentinel.
    """
    if not agent:
        return UNKNOWN
    return cfg.COST_OWNER_MAP.get(str(agent).lower(), str(agent))


def economic_who(agent: str | None, automation: str | None = None) -> dict[str, Any]:
    """WHO for an economic finding: agent, resolved owner, automation/workflow."""
    return make_who(
        agent=agent or UNKNOWN,
        owner=resolve_owner(agent),
        automation=automation or agent or UNKNOWN,
    )


def economic_cost(
    *, spend=None, burn_rate=None, cumulative_cost=None, unknown_reason: str | None = None
) -> dict[str, Any]:
    """COST for an economic finding. None spend becomes UNKNOWN with a reason so
    the gap is explicit rather than silently dropped."""
    if spend is None:
        return make_cost(
            spend=UNKNOWN, burn_rate=burn_rate, cumulative_cost=cumulative_cost,
            unknown_reason=unknown_reason or "spend could not be determined",
        )
    return make_cost(
        spend=round(float(spend), 2),
        burn_rate=round(float(burn_rate), 2) if burn_rate is not None else None,
        cumulative_cost=round(float(cumulative_cost), 2) if cumulative_cost is not None else None,
        unknown_reason=unknown_reason,
    )


# ---------------------------------------------------------------------------
# Phase 7 — accountability gate
# ---------------------------------------------------------------------------

_REQUIRED = ("WHO", "WHAT", "WHERE", "WHEN", "WHICH", "COST")


# Values that look like attribution but carry none. The lowercase UNKNOWN
# sentinel is covered here too, so a literal "unknown" owner never passes.
_UNKNOWN_LITERALS = {"unknown", "none", "n/a", "na", "?", "-", "—"}


def _present(val: Any) -> bool:
    """A value counts as present only if it is a real, non-placeholder value."""
    if val is None:
        return False
    if isinstance(val, (list, tuple, set)):
        return any(_present(v) for v in val)
    s = str(val).strip()
    return bool(s) and s.lower() not in _UNKNOWN_LITERALS


def missing_dimensions(four_w: dict[str, dict] | None) -> list[str]:
    """Return the accountability dimensions that cannot be determined from this 4W.

    A dimension is satisfied when at least one of its identifying fields is
    present (and not UNKNOWN):
      WHO   → agent or owner
      WHAT  → activity_type
      WHERE → repository or service
      WHEN  → (start and end) or first_seen
      WHICH → model or provider
      COST  → spend
    """
    fw = four_w or {}
    who = fw.get("who") or {}
    what = fw.get("what") or {}
    where = fw.get("where") or {}
    when = fw.get("when") or {}
    which = fw.get("which") or {}
    cost = fw.get("cost") or {}

    ok = {
        "WHO": _present(who.get("agent")) or _present(who.get("owner")),
        "WHAT": _present(what.get("activity_type")),
        "WHERE": _present(where.get("repository")) or _present(where.get("service")),
        "WHEN": (_present(when.get("start")) and _present(when.get("end")))
        or _present(when.get("first_seen")),
        "WHICH": _present(which.get("model")) or _present(which.get("provider")),
        "COST": _present(cost.get("spend")),
    }
    return [dim for dim in _REQUIRED if not ok[dim]]


def has_full_accountability(four_w: dict[str, dict] | None) -> bool:
    """True iff WHO/WHAT/WHERE/WHEN/WHICH/COST are all determinable."""
    return not missing_dimensions(four_w)


# ---------------------------------------------------------------------------
# Phase 3 — unknown_cost_owner finding
# ---------------------------------------------------------------------------

def unknown_cost_owner_finding(
    *,
    total_cost: float,
    window_hours: int,
    providers: list[str],
    models: list[str],
    first_ts: str | None,
    last_ts: str | None,
    cumulative_cost: float | None = None,
    reason: str = "spend has no project_id/agent attribution",
) -> dict[str, Any]:
    """HIGH finding: paid spend exists but ownership cannot be determined.

    The operator must never discover paid resource consumption before the system
    can explain ownership. COST is always populated (the money is known); WHO is
    the explicitly-UNKNOWN dimension, with a reason.
    """
    from cognition.four_w import make_4w

    four_w = make_4w(
        who=make_who(agent=UNKNOWN, owner=UNKNOWN, automation=UNKNOWN),
        what={"activity_type": "economic: unattributed spend",
              "task": f"${total_cost:,.2f} with no owner", "workflow": None},
        where={"repository": None, "subsystem": None,
               "service": "LLM/API spend", "component": None},
        when={"start": first_ts, "end": last_ts, "duration": None,
              "first_seen": first_ts, "last_seen": last_ts},
        which={"agent": UNKNOWN, "provider": providers or [UNKNOWN],
               "model": models or [UNKNOWN], "workflow": None, "service": None},
        cost=economic_cost(spend=total_cost, cumulative_cost=cumulative_cost),
    )
    return {
        "target_id": TARGET_ID,
        "finding_type": "unknown_cost_owner",
        "resource": "unattributed_spend",
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": "HIGH",
        "title": f"Unknown cost owner: ${total_cost:,.2f} in {window_hours}h with no attribution",
        "description": f"${total_cost:,.2f} of paid spend cannot be attributed to any agent/project.",
        "recommendation": (
            "Establish ownership of this spend immediately — tag the emitting workflow "
            "with a project_id/agent so future cost is attributable."
        ),
        "evidence": [
            f"${total_cost:,.2f} over {window_hours}h, providers: {', '.join(providers) or UNKNOWN}",
            f"reason: {reason}",
            f"threshold: ≥${cfg.UNKNOWN_COST_OWNER_MIN_USD:,.2f} unattributed",
        ],
        "confidence": 1.0,
        "four_w": four_w,
    }


# ---------------------------------------------------------------------------
# Phase 7 — insufficient_context finding (recommendation withheld)
# ---------------------------------------------------------------------------

def insufficient_context_finding(
    *, source: dict[str, Any], missing: list[str]
) -> dict[str, Any]:
    """Emitted in place of an economic recommendation when accountability is
    incomplete. Names exactly which dimensions are missing — never a silent drop.
    """
    ftype = source.get("finding_type", "economic")
    resource = source.get("resource", "spend")
    return {
        "target_id": TARGET_ID,
        "finding_type": "insufficient_context",
        "resource": f"{ftype}:{resource}",
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": "LOW",
        "title": f"Recommendation suppressed for {ftype}: missing {', '.join(missing)}",
        "description": (
            f"An economic recommendation for '{ftype}' was withheld because these "
            f"accountability dimensions could not be determined: {', '.join(missing)}."
        ),
        "recommendation": (
            "Restore the missing attribution (tag workflow owner / model / window) "
            "to re-enable an actionable economic recommendation."
        ),
        "evidence": [
            f"source finding: {ftype} ({resource})",
            f"missing dimensions: {', '.join(missing)}",
            "gate: no economic recommendation without full who/what/where/when/which/cost",
        ],
        "confidence": 1.0,
        "four_w": source.get("four_w") or {},
    }
