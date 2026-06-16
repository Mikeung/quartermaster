"""Cost investigation — make an Unattributed bucket investigable.

The recommendations-layer pattern (task 239: consequence says what's affected,
this says what to check) applied to money. For an Unattributed spend bucket it
surfaces only what the evidence supports:

  - which KEY spent it,
  - WHEN the spend clustered,
  - which on-box PROCESS was calling that provider around then,

then narrows to CANDIDATES with a confidence — never a fabricated owner. Where
the evidence cannot separate one agent from another, it says "candidates" and
offers the two deterministic resolutions:

  (a) label the key once → the key→agent mapping becomes human_declared and
      sticky (a one-time tag, NOT a new key);
  (b) for a shared key, isolate the agent's key to confirm.

Pure and deterministic. No I/O — the caller passes the observed connections and
an optional process→agent map. It never invents WHO.
"""

from __future__ import annotations

from typing import Any

from config import observability_config as cfg
from economics.connection_evidence import Connection, connections_to_provider


def _label_resolution(bucket: dict[str, Any]) -> dict[str, str]:
    prov = bucket.get("provider", "<provider>")
    hint = bucket.get("key_hint") or bucket.get("key_id") or "<key>"
    return {
        "action": "label_key_once",
        "detail": (
            f"If you know whose key {hint} is, label it once in config/cost_advisor.yml "
            f"(keys: provider={prov}, key_id={bucket.get('key_id') or '<id>'}, agent=repo:<agent>) "
            "and run scripts/load_cost_keys.py. The key→agent mapping becomes human_declared "
            "and sticky — a one-time tag, NOT a new key. All future spend on this key attributes "
            "automatically and reconciliation will never overwrite it."
        ),
    }


def _isolate_resolution(bucket: dict[str, Any]) -> dict[str, str]:
    return {
        "action": "isolate_agent_key",
        "detail": (
            "This key serves more than one agent, so the evidence cannot split its spend 1:1. "
            "Give the agent in question its own provider key; once spend lands on a dedicated "
            "key it separates cleanly and can be labelled and attributed with confidence."
        ),
    }


def investigate_bucket(
    bucket: dict[str, Any],
    connections: list[Connection],
    *,
    process_to_agent: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an investigation for one Unattributed bucket. Deterministic."""
    process_to_agent = process_to_agent or {}
    provider = str(bucket.get("provider", ""))
    hint = bucket.get("key_hint") or bucket.get("key_id") or "no-key-split"
    cost = float(bucket.get("cost_usd") or 0.0)

    # --- evidence the bucket itself supports ---
    evidence: list[str] = [f"${cost:,.2f} attributed to no agent via {provider} key {hint}"]
    if bucket.get("when_first") or bucket.get("when_last"):
        evidence.append(
            f"spend clustered {bucket.get('when_first') or '?'} → {bucket.get('when_last') or '?'}"
        )
    if bucket.get("reason"):
        evidence.append(f"why unattributed: {bucket['reason']}")

    # --- who was calling that provider, on the box, around then ---
    prov_conns = connections_to_provider(provider, connections) if provider != "ledger" else []
    by_process: dict[str, Connection] = {}
    for c in prov_conns:
        by_process.setdefault(c.process, c)

    candidates: list[dict[str, Any]] = []
    if by_process:
        # Point-in-time connection vs day-granular spend → never "High" from this alone.
        conf = "Medium" if len(by_process) == 1 else "Low"
        for proc, c in sorted(by_process.items()):
            agent = process_to_agent.get(proc)
            basis = (
                f"process '{proc}' (pid {c.pid}) had an active outbound connection to "
                f"{provider} at {c.observed_at}"
                + (f"; process maps to agent {agent}" if agent else "; no declared agent for this process")
            )
            candidates.append({
                "process": proc, "pid": c.pid, "agent": agent,
                "confidence": conf, "basis": basis,
            })
            evidence.append(
                f"on-box: '{proc}' (pid {c.pid}) → {provider} observed {c.observed_at}"
            )
    else:
        evidence.append(
            f"no on-box process was observed talking to {provider} at snapshot time "
            "(connection snapshots are point-in-time; provider spend is day-granular)"
        )

    # --- confidence in the narrowing as a whole ---
    if len(candidates) == 1:
        overall = "Medium"
        summary = (
            f"{provider} key {hint} spent ${cost:,.2f} with no declared owner. One on-box "
            f"process ('{candidates[0]['process']}') was talking to {provider} — a candidate, "
            "not a confirmation."
        )
    elif len(candidates) > 1:
        overall = "Low"
        names = ", ".join(c["process"] for c in candidates)
        summary = (
            f"{provider} key {hint} spent ${cost:,.2f} with no declared owner. Several on-box "
            f"processes were talking to {provider} ({names}); the evidence cannot separate them."
        )
    else:
        overall = "Low"
        summary = (
            f"{provider} key {hint} spent ${cost:,.2f} with no declared owner, and no on-box "
            f"process was observed talking to {provider} at snapshot time. Owner is a candidate set, not known."
        )

    # --- deterministic resolutions ---
    resolutions = [_label_resolution(bucket)]
    is_shared = bool(bucket.get("shared_label")) or "shared" in str(bucket.get("reason", "")).lower()
    if is_shared or len(candidates) > 1:
        resolutions.append(_isolate_resolution(bucket))

    return {
        "bucket": {"provider": provider, "key_hint": hint, "cost_usd": round(cost, 2)},
        "summary": summary,
        "evidence": evidence,
        "candidates": candidates,
        "resolutions": resolutions,
        "confidence": overall,
    }


def investigate_advisory(
    advisory: dict[str, Any],
    connections: list[Connection],
    *,
    process_to_agent: dict[str, str] | None = None,
    min_usd: float = cfg.UNATTRIBUTED_INVESTIGATE_MIN_USD,
) -> list[dict[str, Any]]:
    """Investigate every Unattributed bucket in an advisory at/above the threshold."""
    buckets = advisory.get("attribution", {}).get("unattributed", [])
    out: list[dict[str, Any]] = []
    for b in buckets:
        if float(b.get("cost_usd") or 0.0) >= min_usd:
            out.append(investigate_bucket(b, connections, process_to_agent=process_to_agent))
    return out
