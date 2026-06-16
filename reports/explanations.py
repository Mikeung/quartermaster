"""
Guided explanation layer — generate bounded, human-readable explanations.

Explains:
- why severity is at a given level
- why a recommendation was surfaced
- why an operational pattern was matched
- what changed between two states

IMPORTANT — Bounded language rules:
  NEVER use: "will", "causes", "definitely", "certainly", "always", "proves"
  ALWAYS use: "appears to", "correlates with", "has been observed", "evidence suggests",
              "may indicate", "historically associated with", "pattern matches"

Explanations preserve uncertainty. They do not make causal claims.
They do not speculate beyond observed evidence.

Advisory only. Deterministic. Evidence-backed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_BOUNDED_QUALIFIERS = [
    "appears to",
    "correlates with",
    "has been observed to",
    "historically associated with",
    "evidence suggests",
    "may indicate",
    "pattern matches",
]

_SEVERITY_CONTEXT = {
    "informational": "No significant operational signals detected. System appears within normal parameters.",
    "low": "Low-severity signals detected. Items are worth monitoring but do not require immediate action.",
    "moderate": "Moderate-severity signals detected. Review recommended; some concerns may warrant attention.",
    "high": "High-severity signals detected. These patterns have historically correlated with operational risk.",
    "critical": "Critical-severity signals detected. Evidence suggests elevated operational risk requiring review.",
}


@dataclass
class Explanation:
    """A bounded, human-readable operational explanation."""
    title: str
    what_changed: list[str]
    what_contributed: list[str]
    why_it_matters: str
    uncertainty_notes: list[str]
    confidence: float
    language: str = "bounded"   # always "bounded" — no certainty claims

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "what_changed": self.what_changed,
            "what_contributed": self.what_contributed,
            "why_it_matters": self.why_it_matters,
            "uncertainty_notes": self.uncertainty_notes,
            "confidence": round(self.confidence, 3),
            "language": self.language,
        }


class ExplanationGenerator:
    """Generates bounded explanations for operational observations.

    All explanations use bounded language and preserve uncertainty.
    No causal claims. No predictions. Advisory only.
    """

    def explain_severity(
        self,
        severity: dict[str, Any],
        temporal: dict[str, Any] | None = None,
        recurrence: list[dict[str, Any]] | None = None,
    ) -> Explanation:
        """Explain why severity is at the current level.

        severity: serialized SeverityAssessment dict
        temporal: optional serialized TemporalAnalysis
        recurrence: optional list of serialized RecurringIssue dicts
        """
        level = severity.get("level", "unknown")
        score = severity.get("score", 0.0)
        factors = severity.get("factors", [])

        what_contributed: list[str] = []
        what_changed: list[str] = []

        # Break down factors by contribution
        for f in sorted(factors, key=lambda x: -x.get("contribution", 0.0)):
            contrib = f.get("contribution", 0.0)
            if contrib > 0.01:
                what_contributed.append(
                    f"{f.get('name', '?')} ({contrib:.3f}): {f.get('description', '')}"
                )

        # Temporal context
        if temporal:
            vol = temporal.get("volatility_score", 0.0)
            if vol >= 0.40:
                what_changed.append(
                    f"Infrastructure volatility appears elevated ({vol:.2f}) — "
                    f"{temporal.get('total_changes', 0)} change(s) detected in window"
                )
            for ind in temporal.get("churn_indicators", [])[:2]:
                what_changed.append(ind)

        # Recurrence context
        if recurrence:
            persistent = [r for r in recurrence if r.get("occurrences", 0) >= 3]
            if persistent:
                what_changed.append(
                    f"{len(persistent)} concern(s) have been observed across 3+ scans "
                    "(pattern suggests these are structural, not transient)"
                )

        severity_evidence = severity.get("evidence", [])
        what_contributed.extend(severity_evidence[:2])

        why = _SEVERITY_CONTEXT.get(level, f"Severity level: {level}")
        if score >= 0.60:
            why += (
                " This score reflects the combined weight of multiple signals — "
                "no single factor is sufficient to explain it in isolation."
            )

        uncertainty = [
            "Severity scoring is heuristic — factor weights are engineering estimates",
            "Score reflects observed structure, not live runtime behavior unless runtime data was available",
            "Correlation between factors is observed, not causal",
        ]

        logger.info("Severity explanation generated", extra={"level": level, "score": score})

        return Explanation(
            title=f"Why severity is {level.upper()} (score {score:.3f})",
            what_changed=what_changed[:5],
            what_contributed=what_contributed[:6],
            why_it_matters=why,
            uncertainty_notes=uncertainty,
            confidence=severity.get("confidence", 0.5),
        )

    def explain_recommendation(
        self,
        rec: dict[str, Any],
        context_snapshot: dict[str, Any] | None = None,
    ) -> Explanation:
        """Explain why a recommendation was surfaced.

        rec: serialized Recommendation dict
        context_snapshot: optional snapshot for additional context
        """
        title = rec.get("title", "?")
        category = rec.get("category", "?")
        impact = rec.get("impact", "unknown")
        confidence_val = float(rec.get("confidence", 0.0))
        urgency = rec.get("urgency", "monitor")

        what_contributed: list[str] = list(rec.get("evidence", []))[:4]
        what_changed: list[str] = []

        suggested = rec.get("suggested_investigation", "")
        if suggested:
            what_contributed.append(f"Suggested investigation: {suggested[:100]}")

        # Context from snapshot
        if context_snapshot:
            data = context_snapshot.get("data", {})
            wfs = data.get("workflows", [])
            for wf in wfs[:2]:
                wf_type = wf.get("workflow_type", "")
                wf_ev = wf.get("evidence", [])
                if category.lower() in wf_type.lower() or any(category.lower() in e.lower() for e in wf_ev):
                    what_changed.append(f"Related workflow pattern detected: '{wf.get('name', wf_type)}'")

        why = (
            f"This recommendation appears in the '{category}' category with {impact} impact. "
            f"Evidence suggests {_impact_why(impact, confidence_val)} "
            f"Urgency classification: {urgency}."
        )

        uncertainty = [
            "Recommendations are heuristic — they reflect structural patterns, not confirmed runtime behavior",
            f"Confidence {confidence_val:.2f} reflects detection strength, not certainty of risk",
            "Recommendations require human review before any action is taken",
        ]

        return Explanation(
            title=f"Why '{title}' was recommended",
            what_changed=what_changed[:4],
            what_contributed=what_contributed[:6],
            why_it_matters=why,
            uncertainty_notes=uncertainty,
            confidence=confidence_val,
        )

    def explain_pattern(
        self,
        pattern: dict[str, Any],
    ) -> Explanation:
        """Explain why an operational pattern was matched.

        pattern: serialized OperationalPattern dict
        """
        name = pattern.get("name", "?")
        matched = pattern.get("matched", False)
        matching_evidence = pattern.get("matching_evidence", [])
        impact = pattern.get("operational_impact", "")
        mitigation = pattern.get("mitigation_guidance", "")
        severity_hint = pattern.get("severity_hint", "low")
        confidence_notes = pattern.get("confidence_notes", "")

        if not matched:
            return Explanation(
                title=f"Pattern '{name}' — not matched",
                what_changed=[],
                what_contributed=["Pattern signature requirements not satisfied"],
                why_it_matters="This pattern was evaluated but evidence requirements were not met.",
                uncertainty_notes=["Pattern absence does not confirm the concern is resolved"],
                confidence=0.0,
            )

        what_contributed: list[str] = matching_evidence[:5]
        what_changed: list[str] = []
        if confidence_notes:
            what_changed.append(f"Confidence note: {confidence_notes}")

        why = (
            f"Pattern '{name}' matched. This pattern has historically been associated with: "
            f"{impact} "
            f"Mitigation guidance (advisory): {mitigation}"
        )

        uncertainty = [
            confidence_notes or "Structural match — runtime behavior not verified",
            "Pattern matching is evidence-based, not predictive — may not apply to all codebases",
            "Mitigation guidance is advisory only — human review required before any changes",
        ]

        return Explanation(
            title=f"Why pattern '{name}' was flagged",
            what_changed=what_changed,
            what_contributed=what_contributed,
            why_it_matters=why,
            uncertainty_notes=uncertainty,
            confidence=0.65 if severity_hint == "high" else 0.45,
        )

    def explain_comparison(
        self,
        comparison: dict[str, Any],
    ) -> Explanation:
        """Explain what changed between two snapshots and why it matters."""
        summary = comparison.get("overall_summary", "No summary available")
        change_count = comparison.get("change_count", 0)

        what_changed: list[str] = []
        what_contributed: list[str] = []

        topo = comparison.get("topology_delta", {})
        if topo.get("nodes_added"):
            what_changed.append(f"New topology nodes: {', '.join(topo['nodes_added'][:3])}")
        if topo.get("nodes_removed"):
            what_changed.append(f"Removed nodes: {', '.join(topo['nodes_removed'][:3])}")

        wf = comparison.get("workflow_delta", {})
        if wf.get("workflows_added"):
            what_changed.append(f"New workflow patterns: {', '.join(wf['workflows_added'])}")
        if wf.get("workflows_removed"):
            what_changed.append(f"Removed workflows: {', '.join(wf['workflows_removed'])}")

        rt = comparison.get("runtime_delta", {})
        if rt.get("status_changed"):
            what_changed.append(f"Runtime status changed: {rt.get('status_a')} → {rt.get('status_b')}")
        elif rt.get("health_score_delta", 0.0) < -0.05:
            what_changed.append(f"Runtime health degraded: {rt.get('health_score_delta', 0.0):+.3f}")

        rec = comparison.get("recommendation_delta", {})
        if rec.get("new_recommendations"):
            what_contributed.extend(
                [f"New: {t}" for t in rec["new_recommendations"][:3]]
            )
        if rec.get("persisting_recommendations"):
            what_contributed.append(
                f"{len(rec['persisting_recommendations'])} recommendation(s) persisting from previous scan"
            )

        sev = comparison.get("severity_delta", {})
        if sev.get("level_changed"):
            direction = "escalated" if sev.get("escalated") else "improved"
            what_contributed.append(f"Severity {direction}: {sev.get('level_a')} → {sev.get('level_b')}")
        what_contributed.extend(sev.get("contributing_factors", [])[:3])

        why = (
            f"{change_count} operational change(s) detected between snapshots. "
            f"{summary} "
            "Changes may indicate infrastructure evolution, active development, or operational drift."
        )

        return Explanation(
            title=f"What changed: snapshot #{comparison.get('snapshot_a_id')} → #{comparison.get('snapshot_b_id')}",
            what_changed=what_changed[:6],
            what_contributed=what_contributed[:6],
            why_it_matters=why,
            uncertainty_notes=[
                "Comparison covers key structural fields — sub-field changes may not be captured",
                "Changes are observed differences, not confirmed causes of any concern",
            ],
            confidence=min(0.30 + change_count * 0.05, 0.85),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _impact_why(impact: str, confidence: float) -> str:
    if impact == "high":
        return (
            f"the structural evidence appears consistent with high-impact operational risk "
            f"(confidence: {confidence:.2f})."
        )
    if impact == "medium":
        return (
            f"the structural evidence appears consistent with moderate operational risk "
            f"(confidence: {confidence:.2f})."
        )
    return (
        f"the structural evidence appears consistent with low-priority monitoring "
        f"(confidence: {confidence:.2f})."
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
