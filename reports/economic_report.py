"""Economic accountability report (Cost Accountability hotfix, 2026-05-30).

Renders the economic picture with a deterministic header that answers, up front,
the six questions a production spend incident forces:

    WHO spent money?      WHAT was executed?    WHERE did it occur?
    WHEN did it run?      WHICH models/providers?    COST by agent/workflow/provider/model

Input is the structured `summarize_spend()` dict plus the economic findings list.
Markdown out, advisory language, every number traceable to the spend ledger.
Never authoritative billing — estimates from ingested events only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cognition.four_w import summarize_4w


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _usd(x: Any) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "UNKNOWN"


def _none(values: list[str]) -> str:
    return ", ".join(values) if values else "UNKNOWN"


def _cost_lines(label: str, rows: list[dict], name_key: str, total: float) -> list[str]:
    """A '- name: $x (y%)' block for a cost breakdown, costliest first."""
    out = [f"**By {label}:**"]
    if not rows:
        out.append("- _none observed_")
        return out
    ranked = sorted(rows, key=lambda r: float(r.get("total_cost") or r.get("total_estimated_cost") or 0.0), reverse=True)
    for r in ranked:
        name = r.get(name_key) or "UNKNOWN"
        cost = float(r.get("total_cost") or r.get("total_estimated_cost") or 0.0)
        share = (cost / total) if total > 0 else 0.0
        out.append(f"- {name}: {_usd(cost)} ({share:.0%})")
    return out


def generate_economic_report(
    spend_summary: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
) -> str:
    """Markdown economic report with a WHO/WHAT/WHERE/WHEN/WHICH/COST header."""
    findings = findings or []
    window = spend_summary.get("window_hours", 24)
    total = float(spend_summary.get("total_cost") or 0.0)
    events = spend_summary.get("event_count", 0)
    burn = spend_summary.get("burn_rate_usd_per_hr", 0.0)

    by_provider = spend_summary.get("by_provider", []) or []
    by_workflow = spend_summary.get("by_workflow", []) or []
    by_project = spend_summary.get("by_project", []) or []
    by_model = spend_summary.get("by_model", []) or []

    rollup = summarize_4w(findings)

    lines: list[str] = [
        "# Economic Accountability Report",
        f"Generated: {_now()}  |  Window: {window}h",
        "",
        f"> **Data coverage:** {events:,} spend events, {_usd(total)} total. "
        "Estimates from ingested events only — not authoritative billing.",
        "",
        "## Cost Accountability",
        "",
        f"- **WHO spent money?** {_none(rollup.get('who_owners') or rollup.get('who_actors', []))}",
        f"- **WHAT was executed?** {_none(rollup.get('what', []))}",
        f"- **WHERE did it occur?** {_none(rollup.get('where_repos', []) + rollup.get('where_subsystems', []))}",
        f"- **WHEN did it run?** {rollup.get('when_earliest') or 'UNKNOWN'} – {rollup.get('when_latest') or 'UNKNOWN'}",
        f"- **WHICH models/providers?** {_none(rollup.get('which_models', []))} via {_none(rollup.get('which_providers', []))}",
        f"- **COST:** {_usd(total)} total, burn {_usd(burn)}/hr",
        "",
        "### COST breakdown",
        "",
    ]
    lines += [*_cost_lines("agent", by_project, "project_id", total), ""]
    lines += [*_cost_lines("workflow", by_workflow, "workflow", total), ""]
    lines += [*_cost_lines("provider", by_provider, "provider", total), ""]
    lines += [*_cost_lines("model", by_model, "model", total), ""]

    # Economic findings, each with its full accountability block.
    econ = [f for f in findings if f.get("scope") == "spend" or f.get("collector_type") == "economic_observability"]
    if econ:
        from cognition.four_w import four_w_pairs, get_4w
        lines += ["## Economic Findings", ""]
        for f in sorted(econ, key=lambda x: x.get("severity", ""), reverse=True):
            lines.append(f"### [{f.get('severity', '?')}] {f.get('title', f.get('finding_type'))}")
            for label, val in four_w_pairs(get_4w(f)):
                lines.append(f"- **{label}:** {val}")
            rec = f.get("recommendation")
            if rec:
                lines.append(f"- **Recommendation:** {rec}")
            lines.append("")

    lines += [
        "---",
        "_Advisory only. Costs are estimates from ingested events — consult provider "
        "billing dashboards for authoritative figures. The system observes and reports; "
        "it never changes spend or touches provider accounts._",
    ]
    return "\n".join(lines)
