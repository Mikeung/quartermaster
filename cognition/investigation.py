"""
Operational investigation engine.

Supports structured investigation of operational concerns by correlating
evidence already present in snapshots, runtime data, and temporal analysis.

Answers:
- why did severity increase?
- what changed recently?
- what evidence supports this recommendation?
- why is this workflow unstable?
- what contributed most to this concern?
- which components are repeatedly involved?

IMPORTANT:
- Deterministic only — no LLM calls, no ML
- Evidence-backed only — every claim cites observable data
- No root-cause claims — correlation is allowed, certainty is NOT
- Bounded inference — uncertainty always preserved
- Advisory output only — no autonomous action
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_EVIDENCE = 10
_MAX_RECS = 8
_MAX_SNAPS = 5

VALID_KINDS = frozenset({
    "severity_increase",
    "recommendation_evidence",
    "workflow_instability",
    "component_involvement",
    "recent_changes",
    "concern_contribution",
})


@dataclass
class InvestigationResult:
    """Structured investigation output — evidence-guided, uncertainty-preserving."""
    kind: str
    summary: str
    evidence_chain: list[str]
    related_snapshot_ids: list[int]
    related_workflows: list[str]
    related_runtime_events: list[str]
    related_recommendations: list[str]
    confidence: float          # 0.0-1.0 based on data availability
    uncertainty_notes: list[str]
    investigated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "evidence_chain": self.evidence_chain,
            "related_snapshot_ids": self.related_snapshot_ids,
            "related_workflows": self.related_workflows,
            "related_runtime_events": self.related_runtime_events,
            "related_recommendations": self.related_recommendations,
            "confidence": round(self.confidence, 3),
            "uncertainty_notes": self.uncertainty_notes,
            "investigated_at": self.investigated_at,
        }


class InvestigationEngine:
    """Structured investigation support for operational concerns.

    Each investigation kind produces a bounded, evidence-backed result.
    No kind makes causal claims — only evidence correlations.
    """

    def investigate(
        self,
        kind: str,
        snapshots: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> InvestigationResult:
        """Run a structured investigation.

        kind: investigation type (see VALID_KINDS)
        snapshots: list of snapshot dicts (any order — engine will sort)
        context: optional dict with extra parameters (e.g. {'title': 'some rec'})
        """
        ctx = context or {}
        sorted_snaps = sorted(snapshots, key=lambda s: s.get("created_at", ""))

        handlers = {
            "severity_increase": self._severity_increase,
            "recommendation_evidence": self._recommendation_evidence,
            "workflow_instability": self._workflow_instability,
            "component_involvement": self._component_involvement,
            "recent_changes": self._recent_changes,
            "concern_contribution": self._concern_contribution,
        }

        if kind not in handlers:
            return _bad_kind(kind)

        result = handlers[kind](sorted_snaps, ctx)
        logger.info(
            "Investigation complete",
            extra={
                "kind": kind,
                "confidence": result.confidence,
                "evidence_count": len(result.evidence_chain),
            },
        )
        return result

    # ------------------------------------------------------------------
    # Investigation handlers
    # ------------------------------------------------------------------

    def _severity_increase(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        if len(snapshots) < 2:
            return _no_data("severity_increase", "Need at least 2 snapshots to compare severity")

        oldest = snapshots[0]
        newest = snapshots[-1]
        data_a = oldest.get("data", {})
        data_b = newest.get("data", {})

        evidence: list[str] = []
        related_recs: list[str] = []
        related_workflows: list[str] = []
        related_runtime: list[str] = []

        # Recommendation changes
        recs_a = {r.get("title", "") for r in data_a.get("recommendations", [])}
        recs_b = {r.get("title", "") for r in data_b.get("recommendations", [])}
        new_recs = recs_b - recs_a
        if new_recs:
            evidence.append(f"New recommendations appeared ({len(new_recs)}): {', '.join(list(new_recs)[:3])}")
            related_recs.extend(list(new_recs)[:_MAX_RECS])

        resolved_recs = recs_a - recs_b
        if resolved_recs:
            evidence.append(f"Resolved recommendations ({len(resolved_recs)}): {', '.join(list(resolved_recs)[:2])}")

        # Cost observation changes
        costs_a = {o.get("observation", "")[:50] for o in data_a.get("cost_observations", [])}
        costs_b = {o.get("observation", "")[:50] for o in data_b.get("cost_observations", [])}
        new_costs = costs_b - costs_a
        if new_costs:
            evidence.append(f"{len(new_costs)} new cost concern(s) emerged between snapshots")

        # Runtime health delta
        rt_a = data_a.get("runtime_health", {})
        rt_b = data_b.get("runtime_health", {})
        if rt_a and rt_b:
            status_a = rt_a.get("overall_status", "unknown")
            status_b = rt_b.get("overall_status", "unknown")
            if status_a != status_b:
                evidence.append(f"Runtime status changed: {status_a} → {status_b}")
                related_runtime.append(f"Status: {status_a} → {status_b}")
            score_delta = rt_b.get("health_score", 1.0) - rt_a.get("health_score", 1.0)
            if score_delta < -0.10:
                evidence.append(f"Runtime health degraded: {score_delta:+.3f}")
                related_runtime.extend(rt_b.get("instability_signals", [])[:2])

        # Workflow changes
        wfs_a = {w.get("workflow_type", "") for w in data_a.get("workflows", [])}
        wfs_b = {w.get("workflow_type", "") for w in data_b.get("workflows", [])}
        added_wfs = wfs_b - wfs_a
        if added_wfs:
            evidence.append(f"New workflow patterns detected: {', '.join(added_wfs)}")
            related_workflows.extend(list(added_wfs))

        span = _days_between(oldest.get("created_at", ""), newest.get("created_at", ""))
        if span:
            evidence.append(
                f"Analysis window: {span:.1f} days | "
                f"Snapshots #{oldest.get('id')} → #{newest.get('id')}"
            )

        if not evidence:
            evidence.append("No measurable operational changes detected between compared snapshots")
            confidence = 0.20
            uncertainty = ["Insufficient differentiating data between snapshots"]
        else:
            confidence = min(0.30 + len(evidence) * 0.10, 0.85)
            uncertainty = [
                "Correlation only — no causal claims made",
                "Severity is a multi-factor score; listed observations correlate but may not be sole contributors",
            ]

        return InvestigationResult(
            kind="severity_increase",
            summary=(
                f"Comparing snapshot #{oldest.get('id')} and #{newest.get('id')}: "
                f"{len(evidence)} contributing factor(s) identified."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=[oldest.get("id", 0), newest.get("id", 0)],
            related_workflows=related_workflows,
            related_runtime_events=related_runtime,
            related_recommendations=related_recs,
            confidence=confidence,
            uncertainty_notes=uncertainty,
            investigated_at=_now(),
        )

    def _recommendation_evidence(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        target = ctx.get("title", "").lower()
        latest = snapshots[-1] if snapshots else {}
        data = latest.get("data", {})
        recs = data.get("recommendations", [])

        matched = None
        for rec in recs:
            if target and target in rec.get("title", "").lower():
                matched = rec
                break
        if not matched and recs:
            matched = recs[0]

        if not matched:
            return _no_data("recommendation_evidence", "No recommendations in latest snapshot")

        rec_title = matched.get("title", "?")
        evidence: list[str] = list(matched.get("evidence", []))[:4]
        evidence.append(
            f"Category: {matched.get('category', '?')} | "
            f"Impact: {matched.get('impact', '?')} | "
            f"Confidence: {float(matched.get('confidence', 0.0)):.2f}"
        )

        related_workflows: list[str] = []
        category = matched.get("category", "")
        for wf in data.get("workflows", []):
            wf_ev = " ".join(wf.get("evidence", []))
            if category and category.lower() in wf_ev.lower():
                related_workflows.append(wf.get("workflow_type", ""))

        cost_obs = data.get("cost_observations", [])
        cost_ev = [
            o.get("observation", "")[:80]
            for o in cost_obs
            if category and category.lower() in o.get("observation", "").lower()
        ]
        evidence.extend(cost_ev[:2])

        related_runtime: list[str] = []
        rt = data.get("runtime_health", {})
        if rt and rt.get("overall_status") not in ("healthy", "unknown"):
            related_runtime = rt.get("instability_signals", [])[:2]

        confidence_val = float(matched.get("confidence", 0.0))

        return InvestigationResult(
            kind="recommendation_evidence",
            summary=(
                f"Evidence trace for '{rec_title}': "
                f"{len(evidence)} evidence item(s). Confidence: {confidence_val:.2f}."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=[latest.get("id", 0)],
            related_workflows=related_workflows,
            related_runtime_events=related_runtime,
            related_recommendations=[rec_title],
            confidence=min(confidence_val + 0.10, 0.90),
            uncertainty_notes=[
                "Evidence is structural/heuristic — not verified against live runtime behavior",
                "Confidence reflects detection strength, not operational certainty",
            ],
            investigated_at=_now(),
        )

    def _workflow_instability(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        target = ctx.get("workflow_type", "").lower()

        appearances = 0
        absences = 0
        related_snap_ids: list[int] = []
        related_runtime: list[str] = []

        for snap in snapshots:
            data = snap.get("data", {})
            wf_types = {w.get("workflow_type", "").lower() for w in data.get("workflows", [])}

            if target:
                if target in wf_types:
                    appearances += 1
                    related_snap_ids.append(snap.get("id", 0))
                else:
                    absences += 1
            else:
                appearances += len(wf_types)
                related_snap_ids.append(snap.get("id", 0))

            rt = data.get("runtime_health", {})
            if rt and rt.get("has_docker_restarts"):
                related_runtime.extend(rt.get("docker_restart_details", [])[:1])

        evidence: list[str] = []
        if appearances + absences < 2:
            evidence.append("Insufficient snapshot history for workflow stability assessment")
            confidence = 0.20
            uncertainty = ["Need more snapshot history (minimum 2) for stability analysis"]
        else:
            if absences > 0 and appearances > 0:
                total = appearances + absences
                evidence.append(
                    f"Workflow appeared in {appearances}/{total} snapshots — "
                    "intermittent detection may indicate instability"
                )
                confidence = 0.55
            elif appearances > 0:
                evidence.append(f"Workflow consistently detected across {appearances} snapshot(s)")
                confidence = 0.70
            else:
                evidence.append("Workflow not detected in any analyzed snapshot")
                confidence = 0.35

            if related_runtime:
                evidence.append("Container restart instability detected in overlapping snapshots")
                evidence.extend(related_runtime[:2])

            uncertainty = [
                "Workflow inference is structural — intermittent detection may reflect scanner timing, not true instability",
                "Container restarts correlate but are not confirmed to be related",
            ]

        label = f"'{target}'" if target else "all workflows"
        return InvestigationResult(
            kind="workflow_instability",
            summary=(
                f"Workflow instability investigation for {label}: "
                f"{len(evidence)} observation(s) across {len(related_snap_ids)} snapshot(s)."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=related_snap_ids[:_MAX_SNAPS],
            related_workflows=[target] if target else [],
            related_runtime_events=related_runtime,
            related_recommendations=[],
            confidence=confidence,
            uncertainty_notes=uncertainty,
            investigated_at=_now(),
        )

    def _component_involvement(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        from cognition.recurrence import RecurrenceEngine

        issues = RecurrenceEngine().detect(snapshots)
        evidence: list[str] = []

        # Sort by occurrence count descending
        top = sorted(issues, key=lambda i: -i.occurrences)[:8]
        for issue in top:
            evidence.append(
                f"[{issue.kind}] '{issue.pattern}' — "
                f"{issue.occurrences} occurrence(s) across snapshots {issue.snapshot_ids}"
            )

        if not evidence:
            evidence.append("No recurring component patterns detected across analyzed snapshots")
            confidence = 0.20
            uncertainty = ["Insufficient snapshot history or no repeating patterns found"]
        else:
            confidence = min(0.40 + len(issues) * 0.05, 0.80)
            uncertainty = [
                "Recurrence is a correlation — does not confirm operational causation",
                "Pattern grouping uses prefix matching; similar-but-distinct issues may appear merged",
            ]

        return InvestigationResult(
            kind="component_involvement",
            summary=(
                f"{len(issues)} recurring pattern(s) detected across "
                f"{len(snapshots)} snapshot(s)."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=[s.get("id", 0) for s in snapshots[:_MAX_SNAPS]],
            related_workflows=[],
            related_runtime_events=[],
            related_recommendations=[],
            confidence=confidence,
            uncertainty_notes=uncertainty,
            investigated_at=_now(),
        )

    def _recent_changes(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        from cognition.temporal_analysis import TemporalAnalysisEngine

        if len(snapshots) < 2:
            return _no_data("recent_changes", "Need at least 2 snapshots")

        temporal = TemporalAnalysisEngine().analyze(snapshots)
        evidence: list[str] = []
        related_snap_ids: list[int] = []
        related_runtime: list[str] = []

        for ev in temporal.change_events[:8]:
            evidence.append(f"[Snap #{ev.snapshot_id}] {ev.change_type}: {ev.value}")
            related_snap_ids.append(ev.snapshot_id)

        for churn in temporal.churning_components[:3]:
            evidence.append(
                f"Churning: '{churn.component}' changed {churn.change_count} time(s) "
                f"({', '.join(churn.change_types)})"
            )

        evidence.append(
            f"Volatility: {temporal.volatility_score:.2f} | "
            f"Stability: {temporal.stability_score:.2f} | "
            f"Total changes: {temporal.total_changes}"
        )
        evidence.extend(temporal.trend_observations[:2])

        if snapshots:
            rt = snapshots[-1].get("data", {}).get("runtime_health", {})
            if rt:
                related_runtime.extend(rt.get("instability_signals", [])[:2])

        confidence = min(0.40 + len(temporal.change_events) * 0.05, 0.85)

        return InvestigationResult(
            kind="recent_changes",
            summary=(
                f"{temporal.total_changes} change(s) across {len(snapshots)} snapshots "
                f"(volatility: {temporal.volatility_score:.2f})."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=list(dict.fromkeys(related_snap_ids))[:_MAX_SNAPS],
            related_workflows=[],
            related_runtime_events=related_runtime,
            related_recommendations=[],
            confidence=confidence,
            uncertainty_notes=[
                "Change detection compares key fields only (LLM providers, frameworks, docker, CI, language, workflows)",
                "Sub-field changes within packages or configuration files are not captured",
            ],
            investigated_at=_now(),
        )

    def _concern_contribution(
        self, snapshots: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> InvestigationResult:
        from cognition.severity import SeverityEngine

        latest = snapshots[-1] if snapshots else {}
        data = latest.get("data", {})

        rt = data.get("runtime_health", {})
        health_score: float | None = rt.get("health_score") if rt else None
        recommendations = data.get("recommendations", [])
        cost_observations = data.get("cost_observations", [])

        assessment = SeverityEngine().assess(
            runtime_health_score=health_score,
            recommendations=recommendations,
            cost_observations=cost_observations,
        )

        evidence: list[str] = []
        for factor in sorted(assessment.factors, key=lambda f: -f.contribution):
            if factor.contribution > 0.005:
                evidence.append(
                    f"[{factor.name}] score contribution: {factor.contribution:.3f} "
                    f"(weight {factor.weight:.2f}) — {factor.description}"
                )
        evidence.extend(assessment.evidence[:3])

        related_recs = [
            r.get("title", "?")
            for r in recommendations
            if r.get("impact") == "high"
        ][:5]

        related_runtime = rt.get("instability_signals", [])[:3] if rt else []

        return InvestigationResult(
            kind="concern_contribution",
            summary=(
                f"Severity {assessment.level.value} (score {assessment.score:.3f}): "
                f"{len(assessment.factors)} scoring factor(s) decomposed."
            ),
            evidence_chain=evidence[:_MAX_EVIDENCE],
            related_snapshot_ids=[latest.get("id", 0)],
            related_workflows=[],
            related_runtime_events=related_runtime,
            related_recommendations=related_recs,
            confidence=assessment.confidence,
            uncertainty_notes=[
                "Severity score is a heuristic model — factor weights are engineering estimates, not empirically calibrated",
                "Factor contributions are correlations, not confirmed causal relationships",
            ],
            investigated_at=_now(),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _bad_kind(kind: str) -> InvestigationResult:
    return InvestigationResult(
        kind=kind,
        summary=f"Unknown investigation kind: '{kind}'",
        evidence_chain=[f"Valid kinds: {', '.join(sorted(VALID_KINDS))}"],
        related_snapshot_ids=[],
        related_workflows=[],
        related_runtime_events=[],
        related_recommendations=[],
        confidence=0.0,
        uncertainty_notes=["Unknown investigation kind — no investigation performed"],
        investigated_at=_now(),
    )


def _no_data(kind: str, reason: str) -> InvestigationResult:
    return InvestigationResult(
        kind=kind,
        summary=f"Insufficient data for '{kind}': {reason}",
        evidence_chain=[reason],
        related_snapshot_ids=[],
        related_workflows=[],
        related_runtime_events=[],
        related_recommendations=[],
        confidence=0.0,
        uncertainty_notes=["Insufficient snapshot data — investigation could not proceed"],
        investigated_at=_now(),
    )


def _days_between(dt_a: str, dt_b: str) -> float | None:
    try:
        from datetime import datetime as DT
        a = DT.fromisoformat(dt_a.replace("Z", "+00:00"))
        b = DT.fromisoformat(dt_b.replace("Z", "+00:00"))
        return abs((b - a).total_seconds()) / 86400
    except Exception:
        return None
