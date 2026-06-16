"""
LLM Usage Reports — operational visibility into LLM workload behavior.

Reports answer: "How are LLM workloads actually behaving operationally?"
NOT: "How should models be optimized automatically?"

All reports:
- Are markdown strings
- Use bounded language (appears, suggests, historically associated)
- Never claim certainty
- Include evidence for every observation
- Include data coverage notes
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _coverage_note(total_events: int, window_hours: int) -> str:
    if total_events == 0:
        return (
            "> **Data coverage:** No events found in this window. "
            "Ensure ingestion is configured and operational.\n"
        )
    return (
        f"> **Data coverage:** {total_events:,} events over {window_hours}h window. "
        "Estimates are based on ingested events only — not complete billing visibility.\n"
    )


# ---------------------------------------------------------------------------
# Provider Usage Report
# ---------------------------------------------------------------------------

def generate_provider_usage_report(summary: dict[str, Any]) -> str:
    window = summary.get("window_hours", 168)
    total_events = summary.get("total_events", 0)
    total_tokens = summary.get("total_tokens", 0)
    total_cost = summary.get("total_estimated_cost", 0.0)
    providers = summary.get("provider_summaries", [])
    generated = _now()

    lines = [
        "# LLM Provider Usage Report",
        f"Generated: {generated}  |  Window: {window}h",
        "",
        _coverage_note(total_events, window),
        "## Overview",
        "",
        f"- **Total events:** {total_events:,}",
        f"- **Total tokens:** {total_tokens:,}",
        f"- **Estimated cost (USD):** ${total_cost:.4f}",
        f"- **Active providers:** {len(providers)}",
        "",
    ]

    if not providers:
        lines.append("_No provider data available for this window._")
        return "\n".join(lines)

    lines.append("## Provider Breakdown")
    lines.append("")

    for p in providers:
        name = p.get("provider", "unknown")
        events = p.get("event_count", 0)
        tokens = p.get("total_tokens", 0)
        avg_lat = p.get("avg_latency_ms", 0)
        errors = p.get("error_count", 0)
        error_rate = p.get("error_rate", 0)
        cost = p.get("total_estimated_cost", 0.0)
        obs = p.get("observations", [])

        lines += [
            f"### {name}",
            "",
            f"- Events: {events:,}",
            f"- Tokens: {tokens:,} (prompt: {p.get('prompt_tokens', 0):,} / completion: {p.get('completion_tokens', 0):,})",
            f"- Avg latency: {avg_lat:.0f}ms  |  Max: {p.get('max_latency_ms', 0):.0f}ms",
            f"- Errors: {errors} ({error_rate:.1%} error rate)",
            f"- Estimated cost: ${cost:.4f}",
        ]
        if obs:
            lines.append("")
            for o in obs:
                lines.append(f"> {o}")
        lines.append("")

    system_obs = summary.get("system_observations", [])
    if system_obs:
        lines += ["## System Observations", ""]
        for o in system_obs:
            lines.append(f"- {o}")
        lines.append("")

    lines += [
        "---",
        "_Advisory only. Costs are estimates. Consult provider billing dashboards for authoritative figures._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Workflow Economics Report
# ---------------------------------------------------------------------------

def generate_workflow_economics_report(summary: dict[str, Any]) -> str:
    window = summary.get("window_hours", 168)
    total_events = summary.get("total_events", 0)
    total_tokens = summary.get("total_tokens", 0)
    total_cost = summary.get("total_estimated_cost", 0.0)
    workflows = summary.get("workflow_summaries", [])
    high_cost = summary.get("high_cost_workflows", [])
    generated = _now()

    lines = [
        "# LLM Workflow Economics Report",
        f"Generated: {generated}  |  Window: {window}h",
        "",
        _coverage_note(total_events, window),
        "## Overview",
        "",
        f"- **Total tokens:** {total_tokens:,}",
        f"- **Estimated cost (USD):** ${total_cost:.4f}",
        f"- **Active workflows:** {len(workflows)}",
    ]

    if high_cost:
        lines.append(f"- **High-token workflows:** {', '.join(high_cost)}")
    lines.append("")

    if not workflows:
        lines.append("_No workflow data available for this window._")
        return "\n".join(lines)

    lines.append("## Workflow Breakdown")
    lines.append("")

    for w in workflows:
        name = w.get("workflow", "unknown")
        tokens = w.get("total_tokens", 0)
        token_share = w.get("token_share", 0)
        cost = w.get("total_estimated_cost", 0.0)
        cost_share = w.get("cost_share", 0)
        events = w.get("event_count", 0)
        err_rate = w.get("error_rate", 0)
        obs = w.get("observations", [])

        lines += [
            f"### {name}",
            "",
            f"- Events: {events:,}",
            f"- Tokens: {tokens:,} ({token_share:.1%} of total)",
            f"- Estimated cost: ${cost:.4f} ({cost_share:.1%} of total)",
            f"- Avg latency: {w.get('avg_latency_ms', 0):.0f}ms",
            f"- Error rate: {err_rate:.1%}",
        ]
        if obs:
            lines.append("")
            for o in obs:
                lines.append(f"> {o}")
        lines.append("")

    lines += [
        "---",
        "_Workflow cost shares are estimates based on ingested events only._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Latency Trend Report
# ---------------------------------------------------------------------------

def generate_latency_trend_report(
    latency_trends: list[dict[str, Any]],
    window_hours: int = 168,
    total_events: int = 0,
) -> str:
    generated = _now()

    lines = [
        "# LLM Latency Trend Report",
        f"Generated: {generated}  |  Window: {window_hours}h",
        "",
        _coverage_note(total_events, window_hours),
    ]

    if not latency_trends:
        lines.append("_No latency data available for this window._")
        return "\n".join(lines)

    for trend in latency_trends:
        provider = trend.get("provider") or "All providers"
        direction = trend.get("trend_direction", "unknown")
        avg_lat = trend.get("avg_latency_ms", 0)
        max_lat = trend.get("max_latency_ms", 0)
        obs = trend.get("observations", [])

        direction_label = {
            "stable": "Stable",
            "increasing": "Increasing (notable)",
            "decreasing": "Decreasing",
            "insufficient_data": "Insufficient data",
        }.get(direction, direction)

        lines += [
            f"## {provider}",
            "",
            f"- Trend direction: **{direction_label}**",
            f"- Average latency: {avg_lat:.0f}ms",
            f"- Peak latency: {max_lat:.0f}ms",
            f"- Time buckets analyzed: {trend.get('bucket_count', 0)}",
        ]
        if obs:
            lines.append("")
            for o in obs:
                lines.append(f"> {o}")
        lines.append("")

    lines += [
        "---",
        "_Latency trends are based on event-reported measurements only. "
        "Network conditions, provider infrastructure, and model size all contribute._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token Concentration Report
# ---------------------------------------------------------------------------

def generate_token_concentration_report(
    workflow_summaries: list[dict[str, Any]],
    total_tokens: int,
    window_hours: int = 168,
    total_events: int = 0,
) -> str:
    generated = _now()

    lines = [
        "# LLM Token Concentration Report",
        f"Generated: {generated}  |  Window: {window_hours}h",
        "",
        _coverage_note(total_events, window_hours),
        "## Token Distribution by Workflow",
        "",
    ]

    if not workflow_summaries:
        lines.append("_No workflow token data available for this window._")
        return "\n".join(lines)

    sorted_wf = sorted(
        workflow_summaries,
        key=lambda w: w.get("total_tokens", 0),
        reverse=True,
    )

    lines.append(f"Total tokens in window: **{total_tokens:,}**")
    lines.append("")

    cumulative = 0
    for w in sorted_wf:
        name = w.get("workflow", "unknown")
        tokens = w.get("total_tokens", 0)
        share = w.get("token_share", 0)
        cumulative += tokens

        bar_len = int(share * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)

        lines.append(f"**{name}**")
        lines.append(f"  `{bar}` {share:.1%} ({tokens:,} tokens)")
        lines.append("")

    lines += [
        "---",
        "_Token concentration reflects observed workload distribution in the ingestion window._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Error Trend Report
# ---------------------------------------------------------------------------

def generate_error_trend_report(
    error_rows: list[dict[str, Any]],
    window_hours: int = 168,
    total_events: int = 0,
) -> str:
    generated = _now()

    lines = [
        "# LLM Error Trend Report",
        f"Generated: {generated}  |  Window: {window_hours}h",
        "",
        _coverage_note(total_events, window_hours),
    ]

    if not error_rows:
        lines.append("_No error events recorded in this window._")
        return "\n".join(lines)

    lines += ["## Error Breakdown", ""]

    by_provider: dict[str, list[dict[str, Any]]] = {}
    for row in error_rows:
        provider = str(row.get("provider", "unknown"))
        by_provider.setdefault(provider, []).append(row)

    for provider, rows in sorted(by_provider.items()):
        total_errors = sum(r.get("error_count", 0) for r in rows)
        lines += [
            f"### {provider}",
            f"Total errors: {total_errors:,}",
            "",
        ]
        for row in sorted(rows, key=lambda r: r.get("error_count", 0), reverse=True):
            etype = row.get("error_type") or "unknown"
            count = row.get("error_count", 0)
            lines.append(f"- `{etype}`: {count:,} occurrences")
        lines.append("")

    lines += [
        "---",
        "_Error patterns may correlate with provider reliability, quota limits, or context overflow. "
        "Retry libraries can amplify error counts — check whether errors were retried._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Operational Cost Concentration Report
# ---------------------------------------------------------------------------

def generate_cost_concentration_report(
    workflow_summaries: list[dict[str, Any]],
    provider_summaries: list[dict[str, Any]],
    total_cost: float,
    window_hours: int = 168,
    total_events: int = 0,
) -> str:
    generated = _now()

    lines = [
        "# LLM Operational Cost Concentration Report",
        f"Generated: {generated}  |  Window: {window_hours}h",
        "",
        _coverage_note(total_events, window_hours),
        f"**Total estimated cost (USD):** ${total_cost:.4f}",
        "",
    ]

    if not workflow_summaries and not provider_summaries:
        lines.append("_No cost data available for this window._")
        return "\n".join(lines)

    if provider_summaries:
        lines += ["## By Provider", ""]
        for p in sorted(provider_summaries, key=lambda x: x.get("total_estimated_cost", 0), reverse=True):
            name = p.get("provider", "unknown")
            cost = p.get("total_estimated_cost", 0.0)
            pct = cost / max(total_cost, 1e-9)
            lines.append(f"- **{name}**: ${cost:.4f} ({pct:.1%} of total)")
        lines.append("")

    if workflow_summaries:
        lines += ["## By Workflow", ""]
        for w in sorted(workflow_summaries, key=lambda x: x.get("total_estimated_cost", 0), reverse=True):
            name = w.get("workflow", "unknown")
            cost = w.get("total_estimated_cost", 0.0)
            share = w.get("cost_share", 0)
            lines.append(f"- **{name}**: ${cost:.4f} ({share:.1%} of total)")
        lines.append("")

    # Flag high concentration
    top_wf = sorted(
        workflow_summaries,
        key=lambda x: x.get("cost_share", 0),
        reverse=True,
    )
    if top_wf and top_wf[0].get("cost_share", 0) >= 0.6:
        top_name = top_wf[0].get("workflow", "unknown")
        top_share = top_wf[0].get("cost_share", 0)
        lines += [
            "> **Concentration notice:** "
            f"'{top_name}' accounts for {top_share:.1%} of estimated cost. "
            "High concentration in a single workflow historically correlates with cost volatility.",
            "",
        ]

    lines += [
        "---",
        "_Cost estimates are derived from event-level data. "
        "These are operational approximations — not authoritative billing figures._",
    ]
    return "\n".join(lines)
