"""
Ecosystem review reports — markdown output for Phase 6 ecosystem intelligence.

Produces:
- ecosystem review (full synthesis)
- operational theme report
- systemic concern report
- ecosystem drift report
- ecosystem complexity report

All output is markdown with advisory footer.
No frontend. No streaming. No autonomous action.
Emphasis on synthesis, prioritization, compression, and operational themes — NOT raw telemetry.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def generate_ecosystem_review(
    summary: dict[str, Any],
    clusters: list[dict[str, Any]] | None = None,
    drift: dict[str, Any] | None = None,
    consolidated: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a full ecosystem operational review in markdown."""
    now = _now()
    overall = summary.get("overall_health", "unknown")
    dominant = summary.get("dominant_theme", "none detected")
    confidence = summary.get("confidence", 0.0)
    snap_count = summary.get("snapshot_count", 0)
    themes = summary.get("themes", [])
    systemic = summary.get("systemic_concerns", [])
    trends = summary.get("trends", [])

    lines: list[str] = [
        "# Ecosystem Operational Review",
        f"**Generated:** {now}",
        f"**Overall health:** {overall.upper()}",
        f"**Dominant theme:** {dominant}",
        f"**Snapshots analyzed:** {snap_count}",
        f"**Synthesis confidence:** {confidence:.2f}",
        "",
        "> This review synthesizes operational signals into ecosystem-level understanding.",
        "> It reflects observed structure — not live runtime behavior unless runtime data was provided.",
        "",
    ]

    # Systemic concerns (most important — cross-cutting)
    if systemic:
        lines += ["## Systemic Concerns", ""]
        lines.append("> The following concerns appear cross-cutting — present across multiple themes.")
        lines.append("")
        for concern in systemic[:4]:
            sev = concern.get("severity", "?")
            lines.append(f"### [{sev.upper()}] {concern.get('title', '?')}")
            lines.append(concern.get("description", ""))
            lines.append(f"- **Contributing themes:** {', '.join(concern.get('contributing_themes', []))}")
            for ev in concern.get("evidence", [])[:2]:
                lines.append(f"- {ev}")
            lines.append("")

    # Active themes
    if themes:
        lines += ["## Operational Themes", ""]
        for theme in themes[:5]:
            sev = theme.get("severity_hint", "?")
            prevalence = theme.get("prevalence", 0.0)
            lines.append(f"### [{sev.upper()}] {theme.get('label', theme.get('name', '?'))}")
            lines.append(f"**Prevalence:** {prevalence:.0%} of signals")
            lines.append(theme.get("description", ""))
            for ev in theme.get("evidence", [])[:3]:
                lines.append(f"- {ev}")
            lines.append("")

    # Trends
    if trends:
        significant_trends = [t for t in trends if t.get("direction") != "stable"]
        if significant_trends:
            lines += ["## Ecosystem Trends", ""]
            for trend in significant_trends[:4]:
                dim = trend.get("dimension", "?").replace("_", " ").title()
                direction = trend.get("direction", "?")
                score = trend.get("score", 0.0)
                lines.append(f"- **{dim}:** {direction} (score {score:.2f})")
            lines.append("")

    # Active clusters
    if clusters:
        active = [c for c in clusters if c.get("active")]
        if active:
            lines += ["## Concern Clusters", ""]
            for cluster in active[:4]:
                sev = cluster.get("severity_hint", "?")
                score = cluster.get("cluster_score", 0.0)
                lines.append(f"- **[{sev.upper()}]** {cluster.get('label', '?')} (cluster score: {score:.2f})")
            lines.append("")

    # Consolidation summary
    if consolidated:
        lines += ["## Consolidated Concerns", ""]
        lines.append(f"{len(consolidated)} consolidated concern(s) derived from {sum(c.get('member_count', 0) for c in consolidated)} source recommendations.")
        lines.append("")
        for concern in consolidated[:4]:
            sev = concern.get("severity_hint", "?")
            lines.append(f"- **[{sev.upper()}]** {concern.get('title', '?')} ({concern.get('member_count', 0)} source(s))")
        lines.append("")

    # Drift summary
    if drift and drift.get("significant_drift_count", 0) > 0:
        lines += ["## Ecosystem Drift", ""]
        lines.append(f"{drift.get('significant_drift_count', 0)} significant drift trend(s) detected.")
        for ev in drift.get("evidence", [])[:3]:
            lines.append(f"- {ev}")
        lines.append("")

    lines += _advisory_footer()
    logger.info("Ecosystem review generated", extra={"overall_health": overall})
    return "\n".join(lines)


def generate_operational_theme_report(themes: list[dict[str, Any]]) -> str:
    """Generate an operational theme report in markdown."""
    now = _now()
    lines: list[str] = [
        "# Operational Theme Report",
        f"**Generated:** {now}",
        f"**Themes detected:** {len(themes)}",
        "",
        "> Operational themes group related signals into named patterns.",
        "> They reflect observed signal co-occurrence, not confirmed causal relationships.",
        "",
    ]

    if not themes:
        lines += ["_No operational themes detected — insufficient signal density._", ""]
        lines += _advisory_footer()
        return "\n".join(lines)

    for theme in themes:
        sev = theme.get("severity_hint", "?")
        prevalence = theme.get("prevalence", 0.0)
        lines.append(f"## [{sev.upper()}] {theme.get('label', theme.get('name', '?'))}")
        lines.append(f"**Prevalence:** {prevalence:.0%} of observed signals")
        lines.append(theme.get("description", ""))
        lines.append("")

        patterns = theme.get("contributing_patterns", [])
        if patterns:
            lines.append(f"**Matched patterns:** {', '.join(patterns)}")

        categories = theme.get("contributing_categories", [])
        if categories:
            lines.append(f"**Recommendation categories:** {', '.join(categories)}")

        evidence = theme.get("evidence", [])
        if evidence:
            lines.append("")
            lines.append("**Evidence:**")
            for ev in evidence[:4]:
                lines.append(f"- {ev}")
        lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_systemic_concern_report(concerns: list[dict[str, Any]]) -> str:
    """Generate a systemic concern report in markdown."""
    now = _now()
    lines: list[str] = [
        "# Systemic Concern Report",
        f"**Generated:** {now}",
        f"**Systemic concerns:** {len(concerns)}",
        "",
        "> Systemic concerns span multiple operational themes.",
        "> They represent cross-cutting issues that are not isolated to a single domain.",
        "",
    ]

    if not concerns:
        lines += [
            "_No systemic concerns detected — operational themes are not co-occurring._",
            "",
        ]
        lines += _advisory_footer()
        return "\n".join(lines)

    for concern in concerns:
        sev = concern.get("severity", "?")
        lines.append(f"## [{sev.upper()}] {concern.get('title', '?')}")
        lines.append(concern.get("description", ""))
        lines.append("")
        themes = concern.get("contributing_themes", [])
        if themes:
            lines.append(f"**Contributing themes:** {', '.join(t.replace('_', ' ').title() for t in themes)}")
        for ev in concern.get("evidence", [])[:3]:
            lines.append(f"- {ev}")
        lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_ecosystem_drift_report(drift: dict[str, Any]) -> str:
    """Generate an ecosystem drift report in markdown."""
    now = _now()
    overall_score = drift.get("overall_drift_score", 0.0)
    sig_count = drift.get("significant_drift_count", 0)
    snap_count = drift.get("snapshot_count", 0)
    window_days = drift.get("window_days", 0)
    trends = drift.get("drift_trends", [])
    indicators = drift.get("instability_indicators", [])
    complexity = drift.get("complexity_trend", {})

    lines: list[str] = [
        "# Ecosystem Drift Report",
        f"**Generated:** {now}",
        f"**Snapshots analyzed:** {snap_count} | **Window:** {window_days} days",
        f"**Overall drift score:** {overall_score:.2f} | **Significant trends:** {sig_count}",
        "",
        "> Drift reflects observed change between early and recent snapshot windows.",
        "> Direction describes historical trend — NOT predicted future behavior.",
        "",
    ]

    if trends:
        lines += ["## Drift Trends", ""]
        for trend in sorted(trends, key=lambda t: -t.get("magnitude", 0)):
            dim = trend.get("dimension", "?").replace("_", " ").title()
            direction = trend.get("direction", "?")
            magnitude = trend.get("magnitude", 0.0)
            significant = trend.get("significant", False)
            flag = " ⚑" if significant else ""
            lines.append(f"### {dim}{flag}")
            lines.append(f"**Direction:** {direction} | **Magnitude:** {magnitude:.2f}")
            early = trend.get("early_score", 0.0)
            recent = trend.get("recent_score", 0.0)
            lines.append(f"**Early window:** {early:.2f} → **Recent window:** {recent:.2f}")
            for ev in trend.get("evidence", [])[:2]:
                lines.append(f"- {ev}")
            lines.append("")

    # Complexity trend
    if complexity:
        current = complexity.get("current_score", 0.0)
        prev = complexity.get("previous_score", 0.0)
        direction = complexity.get("direction", "stable")
        lines += [
            "## Operational Complexity Trend",
            f"**Current score:** {current:.2f} | **Previous:** {prev:.2f} | **Direction:** {direction}",
            "",
        ]
        for dim in complexity.get("dimensions", [])[:3]:
            lines.append(f"- Driving dimension: {dim.replace('_', ' ')}")
        for ev in complexity.get("evidence", [])[:2]:
            lines.append(f"- {ev}")
        lines.append("")

    # Active instability indicators
    active_indicators = [i for i in indicators if i.get("active")]
    if active_indicators:
        lines += ["## Active Instability Indicators", ""]
        for ind in active_indicators:
            lines.append(f"- **{ind.get('name', '?').replace('_', ' ').title()}** (score {ind.get('score', 0.0):.2f})")
        lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_ecosystem_complexity_report(
    complexity: dict[str, Any],
    drift: dict[str, Any] | None = None,
) -> str:
    """Generate an ecosystem complexity report in markdown."""
    now = _now()
    current = complexity.get("current_score", 0.0)
    prev = complexity.get("previous_score", 0.0)
    delta = complexity.get("delta", 0.0)
    direction = complexity.get("direction", "stable")
    dimensions = complexity.get("dimensions", [])

    lines: list[str] = [
        "# Ecosystem Complexity Report",
        f"**Generated:** {now}",
        f"**Current complexity score:** {current:.2f}",
        f"**Previous complexity score:** {prev:.2f}",
        f"**Delta:** {delta:+.2f} | **Direction:** {direction}",
        "",
        "> Complexity score combines orchestration depth, recommendation volume, and provider diversity.",
        "> Higher scores correlate with increased cognitive and operational overhead.",
        "",
    ]

    if dimensions:
        lines += ["## Contributing Dimensions", ""]
        for dim in dimensions:
            lines.append(f"- {dim.replace('_', ' ').replace('-', ' ').title()}")
        lines.append("")

    for ev in complexity.get("evidence", [])[:4]:
        lines.append(f"- {ev}")
    lines.append("")

    if drift:
        drift_trends = drift.get("drift_trends", [])
        orch_trend = next((t for t in drift_trends if t.get("dimension") == "orchestration_complexity"), None)
        if orch_trend:
            lines += [
                "## Orchestration Complexity Detail",
                f"- Early window: {orch_trend.get('early_score', 0.0):.2f}",
                f"- Recent window: {orch_trend.get('recent_score', 0.0):.2f}",
                f"- Trend: {orch_trend.get('direction', 'stable')}",
                "",
            ]

    lines += _advisory_footer()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public report quality helpers (Task 5 — report quality improvements)
# ---------------------------------------------------------------------------

def generate_report_metadata_block(
    *,
    report_type: str,
    snapshot_count: int = 0,
    confidence: float | None = None,
    evidence_count: int | None = None,
    generated_at: str | None = None,
) -> str:
    """
    Generate a standardized metadata block for any report type.

    Produces consistent report headers across all ecosystem reports.
    Confidence is presented as evidence strength, not probability.
    """
    now = generated_at or _now()
    lines = [
        f"**Report type:** {report_type}",
        f"**Generated:** {now}",
        f"**Snapshots analyzed:** {snapshot_count}",
    ]
    if confidence is not None:
        interp = _confidence_interpretation(confidence)
        lines.append(
            f"**Evidence confidence:** {confidence:.2f} ({interp}) "
            f"— reflects signal density, not probability of correctness"
        )
    if evidence_count is not None:
        lines.append(f"**Evidence items:** {evidence_count}")
    return "\n".join(lines)


def generate_confidence_note(confidence: float, evidence_count: int = 0) -> str:
    """
    Generate a one-line confidence interpretation note for report footers.

    Uses bounded language — confidence reflects evidence density only.
    """
    interp = _confidence_interpretation(confidence)
    return (
        f"*Confidence: {confidence:.2f} ({interp}) — "
        f"based on {evidence_count} supporting signal(s). "
        f"Confidence reflects evidence density, not probability of correctness.*"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _confidence_interpretation(score: float) -> str:
    if score >= 0.80:
        return "strong"
    if score >= 0.60:
        return "moderate"
    if score >= 0.40:
        return "low"
    if score >= 0.20:
        return "very low"
    return "insufficient"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _advisory_footer() -> list[str]:
    return [
        "---",
        "*Advisory only — all operational decisions require human review.*",
        "*Generated by Quartermaster — Observe automatically. Decide manually.*",
    ]
