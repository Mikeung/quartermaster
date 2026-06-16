"""
Investigation report generators — markdown output for Phase 5 intelligence.

Produces:
- operational investigation report
- snapshot comparison report
- recommendation continuity report
- persistent concern report

All output is markdown + advisory footer.
No frontend. No streaming. No autonomous action.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def generate_investigation_report(
    result: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
    evidence_tree: dict[str, Any] | None = None,
    explanation: dict[str, Any] | None = None,
) -> str:
    """Generate a full operational investigation report in markdown."""
    now = _now()
    kind = result.get("kind", "?")
    summary = result.get("summary", "")
    confidence = result.get("confidence", 0.0)

    lines: list[str] = [
        "# Operational Investigation Report",
        f"**Generated:** {now}",
        f"**Investigation kind:** {kind}",
        f"**Confidence:** {confidence:.2f}",
        "",
        f"> {summary}",
        "",
    ]

    # Evidence chain
    evidence = result.get("evidence_chain", [])
    if evidence:
        lines += ["## Evidence Chain", ""]
        for i, ev in enumerate(evidence, 1):
            lines.append(f"{i}. {ev}")
        lines.append("")

    # Uncertainty
    uncertainty = result.get("uncertainty_notes", [])
    if uncertainty:
        lines += ["## Uncertainty Notes", ""]
        for note in uncertainty:
            lines.append(f"- {note}")
        lines.append("")

    # Related items
    related_recs = result.get("related_recommendations", [])
    if related_recs:
        lines += ["## Related Recommendations", ""]
        for rec in related_recs:
            lines.append(f"- {rec}")
        lines.append("")

    related_wfs = result.get("related_workflows", [])
    if related_wfs:
        lines += ["## Related Workflows", ""]
        for wf in related_wfs:
            lines.append(f"- {wf}")
        lines.append("")

    related_runtime = result.get("related_runtime_events", [])
    if related_runtime:
        lines += ["## Related Runtime Events", ""]
        for ev in related_runtime:
            lines.append(f"- {ev}")
        lines.append("")

    # Matched patterns
    if patterns:
        matched = [p for p in patterns if p.get("matched")]
        if matched:
            lines += ["## Matched Operational Patterns", ""]
            for p in matched[:5]:
                sev = p.get("severity_hint", "?")
                lines.append(f"### [{sev.upper()}] {p.get('name', '?')}")
                lines.append(p.get("description", ""))
                for ev in p.get("matching_evidence", [])[:3]:
                    lines.append(f"- {ev}")
                lines.append("")

    # Explanation
    if explanation:
        lines += ["## Guided Explanation", ""]
        lines.append(explanation.get("why_it_matters", ""))
        lines.append("")
        contributed = explanation.get("what_contributed", [])
        if contributed:
            lines.append("**Contributing factors:**")
            for c in contributed[:4]:
                lines.append(f"- {c}")
            lines.append("")
        exp_uncertainty = explanation.get("uncertainty_notes", [])
        if exp_uncertainty:
            lines.append("**Explanation uncertainty:**")
            for n in exp_uncertainty[:2]:
                lines.append(f"- {n}")
            lines.append("")

    lines += _advisory_footer()
    logger.info("Investigation report generated", extra={"kind": kind})
    return "\n".join(lines)


def generate_comparison_report(comparison: dict[str, Any]) -> str:
    """Generate a snapshot comparison report in markdown."""
    now = _now()
    snap_a = comparison.get("snapshot_a_id", "?")
    snap_b = comparison.get("snapshot_b_id", "?")
    change_count = comparison.get("change_count", 0)
    summary = comparison.get("overall_summary", "")

    lines: list[str] = [
        "# Snapshot Comparison Report",
        f"**Generated:** {now}",
        f"**Comparing:** Snapshot #{snap_a} → #{snap_b}",
        f"**Total changes:** {change_count}",
        "",
        f"> {summary}",
        "",
    ]

    # Severity delta
    sev = comparison.get("severity_delta", {})
    if sev.get("level_changed") or abs(sev.get("score_delta", 0.0)) > 0.05:
        direction = "escalated" if sev.get("escalated") else "improved"
        lines += [
            "## Severity",
            f"**{direction.upper()}:** {sev.get('level_a')} → {sev.get('level_b')} "
            f"(score delta: {sev.get('score_delta', 0.0):+.3f})",
            "",
        ]
        factors = sev.get("contributing_factors", [])
        for f in factors[:4]:
            lines.append(f"- {f}")
        lines.append("")

    # Topology delta
    topo = comparison.get("topology_delta", {})
    if topo.get("nodes_added") or topo.get("nodes_removed"):
        lines += ["## Topology Changes", ""]
        for n in topo.get("nodes_added", []):
            lines.append(f"- **Added:** {n}")
        for n in topo.get("nodes_removed", []):
            lines.append(f"- **Removed:** {n}")
        lines.append(
            f"Net: {topo.get('node_count_delta', 0):+d} nodes, "
            f"{topo.get('edge_count_delta', 0):+d} edges"
        )
        lines.append("")

    # Workflow delta
    wf = comparison.get("workflow_delta", {})
    if wf.get("workflows_added") or wf.get("workflows_removed"):
        lines += ["## Workflow Changes", ""]
        for w in wf.get("workflows_added", []):
            lines.append(f"- **Added:** {w}")
        for w in wf.get("workflows_removed", []):
            lines.append(f"- **Removed:** {w}")
        for c in wf.get("confidence_changes", []):
            lines.append(f"- {c}")
        lines.append("")

    # Runtime delta
    rt = comparison.get("runtime_delta", {})
    if rt.get("status_changed") or rt.get("new_instability_signals"):
        lines += ["## Runtime Changes", ""]
        if rt.get("status_changed"):
            lines.append(f"- Status: {rt.get('status_a')} → {rt.get('status_b')}")
        delta = rt.get("health_score_delta", 0.0)
        if abs(delta) > 0.02:
            lines.append(f"- Health score delta: {delta:+.3f}")
        for sig in rt.get("new_instability_signals", []):
            lines.append(f"- New instability: {sig}")
        for sig in rt.get("resolved_instability_signals", []):
            lines.append(f"- Resolved: {sig}")
        lines.append("")

    # Recommendation delta
    rec = comparison.get("recommendation_delta", {})
    if rec.get("new_recommendations") or rec.get("resolved_recommendations"):
        lines += ["## Recommendation Changes", ""]
        for r in rec.get("new_recommendations", [])[:5]:
            lines.append(f"- **New:** {r}")
        for r in rec.get("resolved_recommendations", [])[:5]:
            lines.append(f"- **Resolved:** {r}")
        if rec.get("persisting_recommendations"):
            lines.append(
                f"- **Persisting:** {len(rec['persisting_recommendations'])} recommendation(s) unchanged"
            )
        lines.append("")

    # Cost delta
    cost = comparison.get("cost_delta", {})
    if cost.get("new_cost_concerns") or cost.get("severity_escalations"):
        lines += ["## Cost Changes", ""]
        for c in cost.get("new_cost_concerns", [])[:4]:
            lines.append(f"- New concern: {c}")
        for e in cost.get("severity_escalations", [])[:3]:
            lines.append(f"- Escalated: {e}")
        lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_continuity_report(lifespans: list[dict[str, Any]]) -> str:
    """Generate a recommendation continuity report in markdown."""
    now = _now()
    persistent = [l for l in lifespans if l.get("status") == "persistent"]
    recurring = [l for l in lifespans if l.get("status") == "recurring"]
    resolved = [l for l in lifespans if l.get("status") == "resolved"]
    new_items = [l for l in lifespans if l.get("status") == "new"]

    lines: list[str] = [
        "# Recommendation Continuity Report",
        f"**Generated:** {now}",
        f"**Tracked recommendations:** {len(lifespans)}",
        f"**Persistent:** {len(persistent)} | **Recurring:** {len(recurring)} | "
        f"**Resolved:** {len(resolved)} | **New:** {len(new_items)}",
        "",
    ]

    if persistent:
        lines += ["## Persistent Concerns (Present in 80%+ of scans)", ""]
        for item in persistent[:8]:
            sev = item.get("severity_hint", "?")
            lines.append(f"### [{sev.upper()}] {item.get('title', '?')}")
            lines.append(item.get("summary_statement", ""))
            lines.append(
                f"- **Category:** {item.get('category', '?')} | "
                f"**Scans:** {item.get('occurrence_count', 0)} | "
                f"**Duration:** {item.get('duration_days', 0.0):.1f} days"
            )
            lines.append("")

    if recurring:
        lines += ["## Recurring Concerns", ""]
        for item in recurring[:6]:
            sev = item.get("severity_hint", "?")
            lines.append(f"- **[{sev.upper()}]** {item.get('summary_statement', '?')}")
        lines.append("")

    if new_items:
        lines += ["## Newly Detected", ""]
        for item in new_items[:4]:
            lines.append(f"- {item.get('title', '?')} (Category: {item.get('category', '?')})")
        lines.append("")

    if resolved:
        lines += ["## Recently Resolved", ""]
        for item in resolved[:4]:
            lines.append(f"- {item.get('title', '?')} — no longer present in latest scan")
        lines.append("")

    if not lifespans:
        lines += ["_No recommendations tracked — insufficient snapshot history._", ""]

    lines += _advisory_footer()
    return "\n".join(lines)


def generate_persistent_concerns_report(
    lifespans: list[dict[str, Any]],
    recurring_issues: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a persistent operational concerns report — chronic issues only."""
    now = _now()
    chronic = [l for l in lifespans if l.get("status") in ("persistent", "recurring")]
    chronic_sorted = sorted(chronic, key=lambda l: -l.get("occurrence_count", 0))

    lines: list[str] = [
        "# Persistent Operational Concerns Report",
        f"**Generated:** {now}",
        f"**Chronic concerns:** {len(chronic)}",
        "",
        "> Persistent and recurring concerns indicate structural issues that have not been resolved.",
        "> These are not one-time anomalies — they represent ongoing operational patterns.",
        "",
    ]

    if chronic_sorted:
        lines += ["## Chronic Operational Concerns", ""]
        for item in chronic_sorted[:10]:
            sev = item.get("severity_hint", "?")
            status = item.get("status", "?")
            lines.append(f"### [{sev.upper()} / {status.upper()}] {item.get('title', '?')}")
            lines.append(item.get("summary_statement", ""))
            lines.append(
                f"- Category: {item.get('category', '?')} | "
                f"Occurrences: {item.get('occurrence_count', 0)} | "
                f"Duration: {item.get('duration_days', 0.0):.1f} days | "
                f"First seen: {item.get('first_seen', '?')[:10]}"
            )
            lines.append("")
    else:
        lines += ["_No persistent or recurring concerns detected._", ""]

    # Cross-type recurring issues (from RecurrenceEngine)
    if recurring_issues:
        runtime_failures = [i for i in recurring_issues if i.get("kind") == "runtime_failure"]
        drift_issues = [i for i in recurring_issues if i.get("kind") == "drift"]

        if runtime_failures:
            lines += ["## Recurring Runtime Failures", ""]
            for issue in runtime_failures[:5]:
                hint = issue.get("severity_hint", "?")
                lines.append(
                    f"- **[{hint.upper()}]** {issue.get('pattern', '?')} "
                    f"({issue.get('occurrences', 0)} occurrences)"
                )
            lines.append("")

        if drift_issues:
            lines += ["## Recurring Drift Events", ""]
            for issue in drift_issues[:5]:
                hint = issue.get("severity_hint", "?")
                lines.append(
                    f"- **[{hint.upper()}]** {issue.get('pattern', '?')} "
                    f"({issue.get('occurrences', 0)} changes)"
                )
            lines.append("")

    lines += _advisory_footer()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Phase 13C: Quality-scored and triage report generators
# ---------------------------------------------------------------------------

def generate_quality_scored_report(
    result: dict[str, Any],
    quality: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
) -> str:
    """
    Generate an investigation report prefixed with quality assessment context.

    result: InvestigationResult.to_dict()
    quality: InvestigationQualityAssessment.to_dict()
    """
    now = _now()
    kind = result.get("kind", "?")
    band = quality.get("quality_band", "?")
    score = float(quality.get("quality_score", 0.0))
    guidance = quality.get("guidance", [])

    lines: list[str] = [
        "# Operational Investigation Report (Quality-Scored)",
        f"**Generated:** {now}",
        f"**Investigation kind:** {kind}",
        f"**Quality band:** {band.upper()} (score: {score:.2f})",
        "",
    ]

    if band in ("limited", "insufficient"):
        lines += [
            f"> **Quality warning:** This result has **{band}** evidence coverage.",
            "",
        ]

    if guidance:
        lines += ["## Quality Guidance", ""]
        for item in guidance:
            lines.append(f"- {item}")
        lines.append("")

    # Append the full base investigation content (skip its duplicate header)
    base = generate_investigation_report(result, patterns=patterns)
    base_lines = base.split("\n")
    # Find first content section (Evidence, uncertainty, or the summary blockquote)
    body_start = 0
    for i, line in enumerate(base_lines):
        if line.startswith("> ") or line.startswith("## "):
            body_start = i
            break
    lines.extend(base_lines[body_start:])
    logger.info("Quality-scored investigation report generated", extra={"kind": kind, "band": band})
    return "\n".join(lines)


def generate_triage_report(triage: dict[str, Any]) -> str:
    """Generate a markdown triage report — quality summary + next-step suggestions."""
    now = _now()
    current_kind = triage.get("current_kind", "?")
    coverage = float(triage.get("coverage_fraction", 0.0))
    completed = triage.get("completed_kinds", [])
    remaining = triage.get("remaining_kinds", [])
    suggestions = triage.get("suggestions", [])
    quality = triage.get("quality_assessment", {})

    band = quality.get("quality_band", "?")
    score = float(quality.get("quality_score", 0.0))

    lines: list[str] = [
        "# Investigation Triage Report",
        f"**Generated:** {now}",
        f"**Current investigation kind:** {current_kind}",
        f"**Coverage:** {len(completed)}/6 kinds ({coverage:.0%} complete)",
        "",
        "## Current Investigation Quality",
        f"- Quality band: **{band.upper()}** (score: {score:.2f})",
    ]
    for obs in quality.get("observations", [])[:3]:
        lines.append(f"- {obs}")
    lines.append("")

    if completed:
        lines += [
            "## Investigation Progress",
            f"**Completed:** {', '.join(completed)}",
        ]
    if remaining:
        lines.append(f"**Remaining:** {', '.join(remaining)}")
    lines.append("")

    if suggestions:
        lines += ["## Suggested Next Steps", ""]
        for i, sug in enumerate(suggestions, 1):
            priority = sug.get("priority", "?").upper()
            kind_label = sug.get("kind") or "General guidance"
            rationale = sug.get("rationale", "")
            hint = sug.get("context_hint", "")
            lines.append(f"### {i}. [{priority}] {kind_label}")
            lines.append(f"- **Rationale:** {rationale}")
            if hint:
                lines.append(f"- **How to use:** {hint}")
            lines.append("")
    else:
        lines += [
            "## Next Steps",
            "_No additional suggestions — investigation coverage appears complete._",
            "",
        ]

    lines += _advisory_footer()
    logger.info("Triage report generated", extra={"current_kind": current_kind})
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _advisory_footer() -> list[str]:
    return [
        "---",
        "*Advisory only — all operational decisions require human review.*",
        "*Generated by Quartermaster — Observe automatically. Decide manually.*",
    ]
