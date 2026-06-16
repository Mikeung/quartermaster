"""Render the cost advisory + Unattributed investigations as markdown.

Pure formatting: takes the advisory dict (cognition.cost_advisor.build_advisory)
and the investigations (cognition.cost_investigation.investigate_advisory) and
produces an operator-facing artifact — the whole view, attributed agents, and
each Unattributed bucket carrying its investigation. No I/O, no computation.
"""

from __future__ import annotations

from typing import Any


def _usd(x: Any) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def render_cost_advisor_report(
    advisory: dict[str, Any],
    investigations: list[dict[str, Any]] | None = None,
) -> str:
    investigations = investigations or []
    whole = advisory.get("whole_view", {})
    attr = advisory.get("attribution", {})
    trend = advisory.get("trend", {})
    budget = advisory.get("budget", {})

    lines: list[str] = ["# Cost Advisor — Agent API Spend", ""]
    gen = advisory.get("generated_at")
    win = advisory.get("window_hours")
    lines.append(
        "_Advisory only — observes and explains spend; never throttles, pauses, or spends._"
    )
    if gen:
        lines.append(f"_Generated {gen} · window {win}h._")
    lines.append("")

    # --- WHOLE VIEW (headline) ---
    lines += ["## Whole view — total spend per provider", ""]
    lines.append(f"**Total observed spend: {_usd(whole.get('total_usd', 0))}**")
    lines.append("")
    providers = whole.get("providers", [])
    if providers:
        lines.append("| Provider | Spend | Source | Confidence |")
        lines.append("|---|---|---|---|")
        for p in providers:
            src = p.get("source", "")
            note = f" — {p['reason']}" if p.get("reason") else ""
            lines.append(
                f"| {p.get('provider')} | {_usd(p.get('cost_usd'))} | "
                f"{src}{note} | {p.get('confidence')} |"
            )
    else:
        lines.append("_No spend observed in this window._")
    lines.append("")

    # --- ATTRIBUTION ---
    lines += ["## Attribution — bound to agents by evidence", ""]
    lines.append(
        f"Attributed {_usd(attr.get('attributed_total', 0))} · "
        f"Unattributed {_usd(attr.get('unattributed_total', 0))}."
    )
    lines.append("")
    attributed = attr.get("attributed", [])
    if attributed:
        lines.append("### Attributed agents")
        lines.append("| Agent | Spend | Basis | Confidence | Evidence |")
        lines.append("|---|---|---|---|---|")
        for a in attributed:
            lines.append(
                f"| `{a.get('agent_node') or a.get('agent')}` | {_usd(a.get('cost_usd'))} | "
                f"{a.get('basis')} | {a.get('confidence')} | {a.get('evidence', '')} |"
            )
        lines.append("")

    # --- UNATTRIBUTED + investigations ---
    unattr = attr.get("unattributed", [])
    inv_by_key = {(i["bucket"]["provider"], i["bucket"]["key_hint"]): i for i in investigations}
    lines.append("### Unattributed buckets")
    if not unattr:
        lines.append("_None — all observed spend is attributed._")
        lines.append("")
    else:
        for b in unattr:
            prov = b.get("provider")
            hint = b.get("key_hint") or b.get("key_id") or "no-key-split"
            lines.append(f"#### {prov} · key {hint} — {_usd(b.get('cost_usd'))}")
            lines.append(f"- Why unattributed: {b.get('reason', 'owner not determinable')}")
            inv = inv_by_key.get((prov, hint))
            if inv:
                lines.append(f"- **Investigation** ({inv.get('confidence')} confidence): {inv.get('summary')}")
                if inv.get("evidence"):
                    lines.append("  - Evidence:")
                    for e in inv["evidence"]:
                        lines.append(f"    - {e}")
                if inv.get("candidates"):
                    lines.append("  - Candidates (narrowed, not confirmed):")
                    for c in inv["candidates"]:
                        agent = f" → {c['agent']}" if c.get("agent") else ""
                        lines.append(
                            f"    - `{c['process']}` (pid {c['pid']}){agent} "
                            f"[{c['confidence']}] — {c['basis']}"
                        )
                else:
                    lines.append("  - Candidates: none could be observed — owner remains a candidate set.")
                lines.append("  - Resolutions:")
                for r in inv.get("resolutions", []):
                    lines.append(f"    - **{r['action']}**: {r['detail']}")
            else:
                lines.append("- _Below the investigation threshold._")
            lines.append("")

    # --- TREND ---
    lines += ["## Trend", ""]
    lines.append(f"Direction: **{trend.get('direction', 'unknown')}**.")
    by_day = trend.get("by_day", [])
    if by_day:
        lines.append("")
        lines.append("| Day | Spend |")
        lines.append("|---|---|")
        for d in by_day:
            lines.append(f"| {d.get('day')} | {_usd(d.get('cost_usd'))} |")
    lines.append("")

    # --- BUDGET ---
    lines += ["## Budget (human-declared)", ""]
    if not budget.get("declared"):
        lines.append(
            "_No budget declared. Set one in `config/cost_advisor.yml` to enable "
            "warn-as-approached and a money-critical alert on exceed._"
        )
    else:
        lines.append(
            f"{budget['period'].capitalize()} {budget['scope']} budget "
            f"{_usd(budget['limit_usd'])} · spent {_usd(budget['spend_usd'])} "
            f"({budget['fraction']:.0%}) → **{budget['state']}**."
        )
    lines.append("")

    return "\n".join(lines)
