"""Push policy — what earns a real-time push / P0 incident, and what stays silent.

The product line (CLAUDE.md / UNDERSTANDING_ERA): **silence over impact-free activity.**
A finding earns a push only if it carries a real owner-facing CONSEQUENCE or is
INTRINSICALLY critical (security, resource/OOM, money, a declared dependency down).

Pure development / activity churn — deploys, subsystem rebuilds, engineering or agent
commit bursts — does NOT page the operator unless the consequence graph shows the change
takes an owner-facing capability with it. And the tool's OWN dev/git activity is never an
operational incident (the self-feedback loop): quartermaster committing reports or code about
itself must not alert.

This module is PURE and DETERMINISTIC: it takes a finding dict + an optional consequence
framing dict (produced by cognition.consequence_mapper.get_consequence_framing) and
returns a verdict. No I/O, no clock, no graph access — the caller supplies the framing.

Suppression is NARROW by construction. Only the explicitly-enumerated ACTIVITY_TYPES can
be demoted, and only when they have no owner-facing consequence. Security, OOM, economic,
dependency, and service-loss findings are never gated here — the policy can only ever
*demote* impact-free activity, never an intrinsically critical finding. This is the hard
line from the task: suppression must NEVER hide a security or resource-critical finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Finding-type categories (the single source of truth for push-worthiness)
# ---------------------------------------------------------------------------

# Intrinsically critical: these always earn a push regardless of graph consequence.
# Security, resource exhaustion, money, and a declared dependency going down are
# owner-impacting by their nature — the graph is not required to prove it.
INTRINSIC_CRITICAL_TYPES: frozenset[str] = frozenset({
    # resource exhaustion
    "kernel_oom_kill",
    # security
    "port_exposed_publicly", "credential_in_unit_file", "world_readable_env_file",
    # availability — a declared dependency is unreachable
    "dependency_unreachable",
    # economic — the operator's money is owner-facing by definition
    "spend_spike", "economic_anomaly", "runaway_agent_cost",
    "abnormal_burn_rate", "unknown_cost_owner", "agent_cost",
    "budget_exceeded",
})

# Pure activity / change findings: informational unless the consequence graph shows the
# change takes an owner-facing capability with it. These are the noise source the daily
# report should absorb, not the push channel.
ACTIVITY_TYPES: frozenset[str] = frozenset({
    "deployment_event", "subsystem_rebuild", "engineering_burst",
    "agent_burst", "agent_runtime", "project_activity", "agent_activity",
})

# The tool's own repository identity. Activity findings from git/activity scanners on
# this repo are the system observing its OWN development — never an operational incident.
# Operational-HEALTH findings about the tool (e.g. monitor_stale) are a different scanner
# and a different finding type, so they are unaffected and still push.
SELF_REPO_IDENTIFIERS: frozenset[str] = frozenset({"quartermaster"})


def is_intrinsically_critical(finding: dict[str, Any]) -> bool:
    return finding.get("finding_type", "") in INTRINSIC_CRITICAL_TYPES


def has_owner_facing_consequence(framing: dict[str, Any] | None) -> bool:
    """True when the consequence walk proved an owner-facing capability is lost."""
    return bool(framing and framing.get("owner_facing_lost"))


def is_self_dev_activity(finding: dict[str, Any]) -> bool:
    """True for the tool's own development/git activity (the self-feedback loop).

    Scoped narrowly to ACTIVITY_TYPES on the quartermaster repo. Operational-health findings
    about the tool are NOT activity types, so this never silences "is the system
    running / delivering" — the operator must still learn if quartermaster itself stopped.
    """
    if finding.get("finding_type", "") not in ACTIVITY_TYPES:
        return False
    target = str(finding.get("target_id", ""))
    return any(target == s or target.endswith("/" + s) for s in SELF_REPO_IDENTIFIERS)


@dataclass
class PushVerdict:
    push: bool          # True → earns a real-time push + P0/P1 incident
    reason: str         # "intrinsic" | "owner_facing_consequence" | "self_activity"
                        # | "no_consequence" | "unclassified_pass"
    basis: str          # short human explanation (for the audit / report)

    @property
    def suppressed(self) -> bool:
        return not self.push


def evaluate(finding: dict[str, Any], framing: dict[str, Any] | None) -> PushVerdict:
    """Decide whether a finding earns a push. Deterministic; narrow suppression.

    Order matters:
      1. The tool's own dev/git activity is never an operational incident.
      2. Intrinsically critical findings always push (security / OOM / money / dependency).
      3. Anything with a real owner-facing consequence pushes.
      4. Pure activity/change with no owner-facing consequence is demoted (daily line only).
      5. Everything else is unchanged — not an activity type, so the policy does not
         silence it (e.g. service_disappeared, repeated_service_restart keep their
         existing classification).
    """
    ftype = finding.get("finding_type", "")

    if is_self_dev_activity(finding):
        return PushVerdict(False, "self_activity",
                           "the tool's own development activity — not an operational incident")

    if is_intrinsically_critical(finding):
        return PushVerdict(True, "intrinsic",
                           "intrinsically critical finding type (security / OOM / money / dependency)")

    if has_owner_facing_consequence(framing):
        label = (framing or {}).get("mapped_node_label") or "an owner-facing capability"
        return PushVerdict(True, "owner_facing_consequence",
                           f"owner-facing consequence via {label}")

    if ftype in ACTIVITY_TYPES:
        return PushVerdict(False, "no_consequence",
                           "activity/change with no owner-facing consequence")

    return PushVerdict(True, "unclassified_pass",
                       "not a gated activity type — left to existing classification")
