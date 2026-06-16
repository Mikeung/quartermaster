"""
Operator query workflows — structured investigation pipelines for operational inquiries.

Purpose:
Provide deterministic, evidence-linked answers to common operator questions.

Example queries:
- "Why is ecosystem health degrading?"
- "What changed in the last 7 days?"
- "What concerns remain unresolved?"
- "Which workflows dominate operational cost?"
- "What instability signals are recurring?"
- "What changed since the previous stable period?"

IMPORTANT:
- This is NOT a chatbot.
- This is structured operational inquiry with explicit steps and evidence chains.
- Every finding cites its source signal.
- Uncertainty is stated explicitly — no claims without evidence.
- No autonomous actions. Read-only analysis only.

Advisory only. Deterministic. Evidence-backed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """One step in an operator investigation workflow."""
    step_number: int
    name: str
    finding: str          # what was found at this step
    evidence: list[str]   # evidence items supporting the finding
    signal_count: int     # how many signals were observed

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step_number,
            "name": self.name,
            "finding": self.finding,
            "evidence": self.evidence,
            "signal_count": self.signal_count,
        }


@dataclass
class WorkflowResult:
    """Complete result of an operator query workflow."""
    query: str
    steps: list[WorkflowStep]
    findings: list[str]           # top-level summary findings
    evidence: list[str]           # all evidence items aggregated
    recommendations: list[str]    # suggested next investigation steps
    confidence: float             # 0.0-1.0 evidence strength
    snapshot_count: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "steps": [s.to_dict() for s in self.steps],
            "findings": self.findings,
            "evidence": self.evidence,
            "recommendations": self.recommendations,
            "confidence": round(self.confidence, 3),
            "snapshot_count": self.snapshot_count,
            "generated_at": self.generated_at,
            "advisory": (
                "This workflow result is for operational guidance only. "
                "Findings describe observed signals — not confirmed diagnoses."
            ),
        }

    def markdown(self) -> str:
        """Render workflow result as markdown."""
        lines = [
            "# Operator Query Workflow",
            f"**Query:** {self.query}",
            f"**Generated:** {self.generated_at}",
            f"**Snapshots analyzed:** {self.snapshot_count}",
            f"**Workflow confidence:** {self.confidence:.2f}",
            "",
        ]
        if self.findings:
            lines.append("## Summary Findings")
            for f in self.findings:
                lines.append(f"- {f}")
            lines.append("")

        if self.steps:
            lines.append("## Investigation Steps")
            for step in self.steps:
                lines.append(f"### Step {step.step_number}: {step.name}")
                lines.append(f"**Finding:** {step.finding}")
                if step.evidence:
                    lines.append("**Evidence:**")
                    for e in step.evidence:
                        lines.append(f"  - {e}")
                lines.append("")

        if self.recommendations:
            lines.append("## Suggested Next Steps")
            for r in self.recommendations:
                lines.append(f"- {r}")
            lines.append("")

        lines += [
            "---",
            "*Advisory only — findings describe observed signals, not confirmed diagnoses.*",
        ]
        return "\n".join(lines)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_confidence(evidence_count: int, snap_count: int) -> float:
    """Simple evidence-density confidence without importing confidence.py."""
    density = min(evidence_count / max(snap_count, 1), 1.0)
    snap_factor = min(snap_count / 5.0, 1.0) * 0.3
    return min(density * 0.7 + snap_factor, 1.0)


class OperatorQueryWorkflow:
    """
    Structured operator investigation workflows.

    Each method answers one operational question using available data.
    All methods are deterministic and evidence-linked.
    """

    # ------------------------------------------------------------------
    # 1. Why is ecosystem health degrading?
    # ------------------------------------------------------------------

    def why_is_health_degrading(
        self,
        summary: dict[str, Any],
        *,
        drift: dict[str, Any] | None = None,
        clusters: list[dict[str, Any]] | None = None,
    ) -> WorkflowResult:
        """
        Investigate why ecosystem health appears degraded.

        Steps:
        1. Check overall health and dominant theme
        2. Enumerate active operational themes and their severity
        3. Check for systemic concerns
        4. Cross-reference drift trends if available
        5. Check active clusters if available
        """
        query = "Why is ecosystem health degrading?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        overall = summary.get("overall_health", "unknown")
        dominant = summary.get("dominant_theme")
        themes = summary.get("themes", [])
        concerns = summary.get("systemic_concerns", [])
        snap_count = summary.get("snapshot_count", 0)

        # Step 1 — overall health
        step_ev: list[str] = [f"Overall health: {overall}"]
        if dominant:
            step_ev.append(f"Dominant theme: {dominant}")
        steps.append(WorkflowStep(
            step_number=1,
            name="Overall health assessment",
            finding=f"Ecosystem health reported as '{overall}'" + (
                f" with dominant theme '{dominant}'" if dominant else ""
            ),
            evidence=step_ev,
            signal_count=len(step_ev),
        ))
        all_evidence.extend(step_ev)

        # Step 2 — themes
        if themes:
            theme_ev = [
                f"{t.get('label', t.get('name', '?'))} [{t.get('severity_hint', '?').upper()}] "
                f"— prevalence {t.get('prevalence', 0):.2f}"
                for t in themes
            ]
            steps.append(WorkflowStep(
                step_number=2,
                name="Active operational themes",
                finding=f"{len(themes)} operational theme(s) appear to be contributing",
                evidence=theme_ev,
                signal_count=len(themes),
            ))
            all_evidence.extend(theme_ev)
            findings.append(
                f"{len(themes)} operational theme(s) detected — "
                f"highest severity: {themes[0].get('severity_hint', '?')}"
            )
        else:
            steps.append(WorkflowStep(
                step_number=2,
                name="Active operational themes",
                finding="No distinct operational themes detected. Health classification may be driven by runtime data.",
                evidence=[],
                signal_count=0,
            ))

        # Step 3 — systemic concerns
        if concerns:
            concern_ev = [
                f"{c.get('title', '?')} [{c.get('severity', '?')}]"
                for c in concerns
            ]
            steps.append(WorkflowStep(
                step_number=3,
                name="Systemic cross-theme concerns",
                finding=f"{len(concerns)} systemic concern(s) identified across themes",
                evidence=concern_ev,
                signal_count=len(concerns),
            ))
            all_evidence.extend(concern_ev)
            findings.append(
                f"{len(concerns)} systemic concern(s) observed — "
                "these span multiple operational themes"
            )
            recs.append(
                "Review systemic concerns first — they represent cross-cutting operational risk"
            )
        else:
            steps.append(WorkflowStep(
                step_number=3,
                name="Systemic cross-theme concerns",
                finding="No systemic concerns detected.",
                evidence=[],
                signal_count=0,
            ))

        # Step 4 — drift
        if drift:
            sig_count = drift.get("significant_drift_count", 0)
            drift_score = drift.get("overall_drift_score", 0.0)
            drift_ev = [f"Overall drift score: {drift_score:.2f}", f"Significant drift dimensions: {sig_count}"]
            for trend in drift.get("drift_trends", []):
                if trend.get("significant"):
                    drift_ev.append(
                        f"{trend.get('dimension', '?')}: {trend.get('direction', '?')} "
                        f"(early={trend.get('early_score', 0):.2f}, recent={trend.get('recent_score', 0):.2f})"
                    )
            steps.append(WorkflowStep(
                step_number=4,
                name="Drift analysis cross-reference",
                finding=f"Drift score {drift_score:.2f} with {sig_count} significant dimension(s)",
                evidence=drift_ev,
                signal_count=sig_count,
            ))
            all_evidence.extend(drift_ev)
            if sig_count > 0:
                findings.append(f"Drift analysis shows {sig_count} significant changing dimension(s)")
                recs.append("Investigate significant drift dimensions — these indicate direction of change")
        else:
            steps.append(WorkflowStep(
                step_number=4,
                name="Drift analysis cross-reference",
                finding="No drift data available — cannot assess trend direction.",
                evidence=[],
                signal_count=0,
            ))

        # Step 5 — active clusters
        if clusters:
            active = [c for c in clusters if c.get("active")]
            if active:
                cluster_ev = [f"{c.get('label', c.get('name', '?'))} (score {c.get('cluster_score', 0):.2f})" for c in active]
                steps.append(WorkflowStep(
                    step_number=5,
                    name="Active concern clusters",
                    finding=f"{len(active)} concern cluster(s) are active",
                    evidence=cluster_ev,
                    signal_count=len(active),
                ))
                all_evidence.extend(cluster_ev)
            else:
                steps.append(WorkflowStep(
                    step_number=5,
                    name="Active concern clusters",
                    finding="No concern clusters are active.",
                    evidence=[],
                    signal_count=0,
                ))

        if not findings:
            findings.append(
                f"Health is '{overall}' — insufficient theme/drift data to determine primary cause"
            )
            recs.append("Collect more snapshots over time to improve diagnostic confidence")

        recs.append("Review operational themes and their contributing evidence for root cause investigation")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), snap_count),
            snapshot_count=snap_count,
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # 2. What changed in the last N days?
    # ------------------------------------------------------------------

    def what_changed_last_n_days(
        self,
        snapshots: list[dict[str, Any]],
        days: int = 7,
    ) -> WorkflowResult:
        """
        Summarize what changed across snapshots in the last N days.

        Steps:
        1. Identify snapshot window
        2. Compare package sets (first vs last)
        3. Compare provider sets
        4. Compare recommendation titles
        5. Compare runtime health trend
        """
        query = f"What changed in the last {days} days?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        if len(snapshots) < 2:
            return WorkflowResult(
                query=query,
                steps=[WorkflowStep(1, "Snapshot availability", "Insufficient snapshots for change analysis (need ≥ 2).", [], 0)],
                findings=["Cannot determine changes — insufficient snapshot history"],
                evidence=[],
                recommendations=["Collect more snapshots to enable change analysis"],
                confidence=0.0,
                snapshot_count=len(snapshots),
                generated_at=_now(),
            )

        snap_count = len(snapshots)
        first = snapshots[0]
        last = snapshots[-1]
        first_at = first.get("created_at", "?")
        last_at = last.get("created_at", "?")

        steps.append(WorkflowStep(
            step_number=1,
            name="Snapshot window",
            finding=f"Analyzing {snap_count} snapshots from {first_at} to {last_at}",
            evidence=[f"First: {first_at}", f"Last: {last_at}", f"Count: {snap_count}"],
            signal_count=snap_count,
        ))

        def _packages(snap: dict) -> set[str]:
            try:
                return set(snap["data"]["scanner_results"]["results"]["repo_scanner"]["packages"])
            except (KeyError, TypeError):
                return set()

        def _providers(snap: dict) -> set[str]:
            try:
                return {d.get("provider", "") for d in snap["data"].get("llm_detections", [])}
            except (KeyError, TypeError):
                return set()

        def _rec_titles(snap: dict) -> set[str]:
            try:
                return {r.get("title", "") for r in snap["data"].get("recommendations", [])}
            except (KeyError, TypeError):
                return set()

        # Step 2 — packages
        pkgs_first = _packages(first)
        pkgs_last = _packages(last)
        added_pkgs = pkgs_last - pkgs_first
        removed_pkgs = pkgs_first - pkgs_last
        pkg_ev: list[str] = []
        if added_pkgs:
            pkg_ev.append(f"New packages: {', '.join(sorted(added_pkgs))}")
        if removed_pkgs:
            pkg_ev.append(f"Removed packages: {', '.join(sorted(removed_pkgs))}")
        if not pkg_ev:
            pkg_ev.append("No package changes detected")
        steps.append(WorkflowStep(
            step_number=2,
            name="Package changes",
            finding=f"{len(added_pkgs)} package(s) added, {len(removed_pkgs)} removed",
            evidence=pkg_ev,
            signal_count=len(added_pkgs) + len(removed_pkgs),
        ))
        all_evidence.extend(pkg_ev)
        if added_pkgs or removed_pkgs:
            findings.append(f"Package changes detected: +{len(added_pkgs)} / -{len(removed_pkgs)}")

        # Step 3 — providers
        prov_first = _providers(first)
        prov_last = _providers(last)
        added_prov = prov_last - prov_first
        removed_prov = prov_first - prov_last
        prov_ev: list[str] = []
        if added_prov:
            prov_ev.append(f"New LLM providers: {', '.join(sorted(added_prov))}")
        if removed_prov:
            prov_ev.append(f"Removed LLM providers: {', '.join(sorted(removed_prov))}")
        if not prov_ev:
            prov_ev.append("No provider changes detected")
        steps.append(WorkflowStep(
            step_number=3,
            name="LLM provider changes",
            finding=f"{len(added_prov)} provider(s) added, {len(removed_prov)} removed",
            evidence=prov_ev,
            signal_count=len(added_prov) + len(removed_prov),
        ))
        all_evidence.extend(prov_ev)
        if added_prov or removed_prov:
            findings.append(f"LLM provider changes detected: +{len(added_prov)} / -{len(removed_prov)}")

        # Step 4 — recommendations
        recs_first = _rec_titles(first)
        recs_last = _rec_titles(last)
        new_recs = recs_last - recs_first
        resolved_recs = recs_first - recs_last
        rec_ev: list[str] = []
        if new_recs:
            rec_ev.extend([f"New recommendation: {r}" for r in sorted(new_recs)[:5]])
        if resolved_recs:
            rec_ev.extend([f"No longer surfaced: {r}" for r in sorted(resolved_recs)[:5]])
        if not rec_ev:
            rec_ev.append("No recommendation changes detected")
        steps.append(WorkflowStep(
            step_number=4,
            name="Recommendation changes",
            finding=f"{len(new_recs)} new recommendation(s), {len(resolved_recs)} no longer surfaced",
            evidence=rec_ev,
            signal_count=len(new_recs) + len(resolved_recs),
        ))
        all_evidence.extend(rec_ev)
        if new_recs:
            findings.append(f"{len(new_recs)} new recommendation(s) appeared")
        if resolved_recs:
            findings.append(f"{len(resolved_recs)} recommendation(s) no longer surfacing")

        # Step 5 — runtime health trend
        try:
            rt_first = first["data"].get("runtime_health", {})
            rt_last = last["data"].get("runtime_health", {})
            score_first = rt_first.get("health_score", None)
            score_last = rt_last.get("health_score", None)
            if score_first is not None and score_last is not None:
                delta = score_last - score_first
                direction = "improved" if delta > 0.05 else ("degraded" if delta < -0.05 else "stable")
                rt_ev = [
                    f"Runtime health: {score_first:.2f} → {score_last:.2f} ({direction})",
                ]
                steps.append(WorkflowStep(
                    step_number=5,
                    name="Runtime health trend",
                    finding=f"Runtime health {direction} by {abs(delta):.2f}",
                    evidence=rt_ev,
                    signal_count=1,
                ))
                all_evidence.extend(rt_ev)
                if direction != "stable":
                    findings.append(f"Runtime health has {direction}")
                    if direction == "degraded":
                        recs.append("Investigate runtime health degradation — check instability signals")
        except (KeyError, TypeError):
            steps.append(WorkflowStep(
                step_number=5,
                name="Runtime health trend",
                finding="Runtime health data not available.",
                evidence=[],
                signal_count=0,
            ))

        if not findings:
            findings.append(f"No significant changes detected across {snap_count} snapshots")

        recs.append("Compare snapshots directly using investigation comparison tools for detail")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), snap_count),
            snapshot_count=snap_count,
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # 3. What concerns remain unresolved?
    # ------------------------------------------------------------------

    def what_concerns_unresolved(
        self,
        lifespans: list[dict[str, Any]],
    ) -> WorkflowResult:
        """
        Identify which recommendations have persisted across multiple snapshots.

        lifespans: output of ContinuityEngine — list of RecommendationLifespan dicts.
        """
        query = "What concerns remain unresolved?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        persistent = [l for l in lifespans if l.get("status") in ("persistent", "recurring")]
        new_items = [l for l in lifespans if l.get("status") == "new"]
        resolved = [l for l in lifespans if l.get("status") == "resolved"]

        steps.append(WorkflowStep(
            step_number=1,
            name="Continuity overview",
            finding=(
                f"{len(persistent)} persistent/recurring, "
                f"{len(new_items)} new, {len(resolved)} resolved"
            ),
            evidence=[
                f"Total tracked: {len(lifespans)}",
                f"Persistent/recurring: {len(persistent)}",
                f"New this period: {len(new_items)}",
                f"Resolved: {len(resolved)}",
            ],
            signal_count=len(lifespans),
        ))

        if persistent:
            persist_ev = [
                f"{l.get('title', '?')} [{l.get('impact', '?').upper()}] — "
                f"seen {l.get('occurrence_count', 1)}x"
                for l in persistent[:10]
            ]
            steps.append(WorkflowStep(
                step_number=2,
                name="Persistent concerns",
                finding=f"{len(persistent)} concern(s) have persisted across multiple snapshots",
                evidence=persist_ev,
                signal_count=len(persistent),
            ))
            all_evidence.extend(persist_ev)
            findings.append(f"{len(persistent)} concern(s) have not resolved — persistent across snapshots")
            recs.append("Prioritize persistent/recurring items — they indicate systemic issues, not transient noise")
        else:
            steps.append(WorkflowStep(
                step_number=2,
                name="Persistent concerns",
                finding="No persistent concerns detected.",
                evidence=[],
                signal_count=0,
            ))

        if new_items:
            new_ev = [f"{l.get('title', '?')} [{l.get('impact', '?').upper()}]" for l in new_items[:5]]
            steps.append(WorkflowStep(
                step_number=3,
                name="New concerns this period",
                finding=f"{len(new_items)} concern(s) appeared for the first time",
                evidence=new_ev,
                signal_count=len(new_items),
            ))
            all_evidence.extend(new_ev)
            findings.append(f"{len(new_items)} new concern(s) appeared this period")

        if resolved:
            findings.append(f"{len(resolved)} concern(s) resolved (no longer surfacing)")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), len(lifespans)),
            snapshot_count=len(lifespans),
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # 4. Which workflows dominate operational cost?
    # ------------------------------------------------------------------

    def which_workflows_dominate_cost(
        self,
        workflows: list[dict[str, Any]],
        cost_observations: list[dict[str, Any]],
    ) -> WorkflowResult:
        """
        Identify which workflows are associated with the highest operational cost signals.
        """
        query = "Which workflows dominate operational cost?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        # Step 1: workflow inventory
        wf_types = {}
        for wf in workflows:
            wt = wf.get("workflow_type", "unknown")
            wf_types[wt] = wf_types.get(wt, 0) + 1
        wf_ev = [f"{t}: {c} instance(s)" for t, c in sorted(wf_types.items(), key=lambda x: -x[1])]
        if not wf_ev:
            wf_ev = ["No workflows detected"]
        steps.append(WorkflowStep(
            step_number=1,
            name="Workflow inventory",
            finding=f"{len(workflows)} workflow(s) across {len(wf_types)} type(s)",
            evidence=wf_ev,
            signal_count=len(workflows),
        ))
        all_evidence.extend(wf_ev)

        # Step 2: cost observations
        high_cost = [o for o in cost_observations if o.get("severity") in ("high", "critical")]
        cost_ev: list[str] = []
        for obs in high_cost[:10]:
            cost_ev.append(
                f"{obs.get('observation_type', '?')} [{obs.get('severity', '?').upper()}]: "
                f"{obs.get('description', '')[:80]}"
            )
        if not cost_ev:
            cost_ev = ["No high-cost observations detected"]
        steps.append(WorkflowStep(
            step_number=2,
            name="High-cost observations",
            finding=f"{len(high_cost)} high/critical cost observation(s)",
            evidence=cost_ev,
            signal_count=len(high_cost),
        ))
        all_evidence.extend(cost_ev)
        if high_cost:
            findings.append(f"{len(high_cost)} high/critical cost observation(s) detected")

        # Step 3: cross-reference cost with workflow types
        cost_wf_map: dict[str, list[str]] = {}
        for obs in cost_observations:
            obs_type = obs.get("observation_type", "")
            # Map known observation types to likely workflow types
            for wt in wf_types:
                if (
                    ("rag" in obs_type and "rag" in wt)
                    or ("ocr" in obs_type and "ocr" in wt)
                    or ("agent" in obs_type and "agent" in wt)
                    or ("retry" in obs_type)
                ):
                    cost_wf_map.setdefault(wt, []).append(obs_type)

        if cost_wf_map:
            cross_ev = [f"{wt}: associated with {', '.join(set(obs)[:3])}" for wt, obs in cost_wf_map.items()]
            steps.append(WorkflowStep(
                step_number=3,
                name="Cost-workflow association",
                finding=f"{len(cost_wf_map)} workflow type(s) appear associated with cost observations",
                evidence=cross_ev,
                signal_count=len(cost_wf_map),
            ))
            all_evidence.extend(cross_ev)
            findings.append(
                f"Workflow types that appear cost-associated: {', '.join(sorted(cost_wf_map.keys()))}"
            )
            recs.append("Review cost observations for these workflow types and consider cost controls")
        else:
            steps.append(WorkflowStep(
                step_number=3,
                name="Cost-workflow association",
                finding="Could not directly associate cost observations with specific workflow types.",
                evidence=["Insufficient cross-reference data"],
                signal_count=0,
            ))

        # Known high-cost workflow types
        known_expensive = {"ocr_pipeline", "multi_agent_orchestration", "rag_pipeline"}
        found_expensive = known_expensive & set(wf_types.keys())
        if found_expensive:
            findings.append(
                f"Inherently expensive workflow type(s) present: {', '.join(sorted(found_expensive))}"
            )
            recs.append(
                "OCR pipelines, multi-agent orchestration, and RAG pipelines "
                "historically correlate with elevated token costs — review budgeting"
            )

        if not findings:
            findings.append("No dominant cost-associated workflows identified from available data")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), len(cost_observations) + 1),
            snapshot_count=len(workflows),
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # 5. What instability signals are recurring?
    # ------------------------------------------------------------------

    def what_instability_recurring(
        self,
        recurrence_data: list[dict[str, Any]],
        *,
        runtime_health: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """
        Identify recurring instability signals from recurrence and runtime health data.
        """
        query = "What instability signals are recurring?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        # Step 1: runtime health signals
        rt_signals: list[str] = []
        rt_status = "unknown"
        if runtime_health:
            rt_status = runtime_health.get("overall_status", "unknown")
            rt_score = runtime_health.get("health_score", 1.0)
            rt_signals = runtime_health.get("instability_signals", [])
            rt_ev = [f"Runtime status: {rt_status} (score {rt_score:.2f})"]
            if rt_signals:
                rt_ev.extend([f"Signal: {s}" for s in rt_signals[:5]])
            steps.append(WorkflowStep(
                step_number=1,
                name="Current runtime health",
                finding=f"Runtime is '{rt_status}' with {len(rt_signals)} active instability signal(s)",
                evidence=rt_ev,
                signal_count=len(rt_signals),
            ))
            all_evidence.extend(rt_ev)
            if rt_signals:
                findings.append(f"{len(rt_signals)} active runtime instability signal(s) observed")
        else:
            steps.append(WorkflowStep(
                step_number=1,
                name="Current runtime health",
                finding="No runtime health data available.",
                evidence=[],
                signal_count=0,
            ))

        # Step 2: recurring items from recurrence engine
        recurring = [r for r in recurrence_data if r.get("status") in ("persistent", "recurring")]
        runtime_recurring = [
            r for r in recurring
            if r.get("kind") == "runtime_failure"
            or "runtime" in r.get("category", "").lower()
            or "instability" in r.get("title", "").lower()
        ]

        if runtime_recurring:
            recur_ev = [
                f"{r.get('title', '?')} — {r.get('occurrence_count', 1)}x occurrence(s)"
                for r in runtime_recurring[:5]
            ]
            steps.append(WorkflowStep(
                step_number=2,
                name="Recurring runtime failures",
                finding=f"{len(runtime_recurring)} runtime-related item(s) are recurring",
                evidence=recur_ev,
                signal_count=len(runtime_recurring),
            ))
            all_evidence.extend(recur_ev)
            findings.append(f"{len(runtime_recurring)} runtime concern(s) are recurring — not transient")
            recs.append("Recurring runtime failures indicate structural issues — investigate root cause")
        else:
            steps.append(WorkflowStep(
                step_number=2,
                name="Recurring runtime failures",
                finding="No recurring runtime failures detected.",
                evidence=[],
                signal_count=0,
            ))

        # Step 3: all recurring items summary
        all_recurring = [r for r in recurrence_data if r.get("status") == "persistent"]
        if all_recurring:
            persist_ev = [
                f"{r.get('title', '?')} [{r.get('impact', '?').upper()}]"
                for r in all_recurring[:8]
            ]
            steps.append(WorkflowStep(
                step_number=3,
                name="All persistent concerns",
                finding=f"{len(all_recurring)} concern(s) have been persistent across snapshots",
                evidence=persist_ev,
                signal_count=len(all_recurring),
            ))
            all_evidence.extend(persist_ev)

        if not findings:
            findings.append("No significant recurring instability signals detected")
            if rt_status in ("degraded", "critical"):
                findings.append(f"Runtime is currently '{rt_status}' — monitor for recurrence")

        recs.append("Track recurring signals across future snapshots to confirm persistence pattern")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), len(recurrence_data) + 1),
            snapshot_count=len(recurrence_data),
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # 6. What changed since the previous stable period?
    # ------------------------------------------------------------------

    def what_changed_since_stable(
        self,
        snapshots: list[dict[str, Any]],
        *,
        drift: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """
        Identify changes that occurred since the last period of relative stability.

        Uses drift analysis if available; otherwise compares first and last snapshots.
        """
        query = "What changed since the previous stable period?"
        steps: list[WorkflowStep] = []
        findings: list[str] = []
        all_evidence: list[str] = []
        recs: list[str] = []

        if len(snapshots) < 2:
            return WorkflowResult(
                query=query,
                steps=[WorkflowStep(1, "Snapshot availability", "Insufficient snapshots (need ≥ 2).", [], 0)],
                findings=["Cannot identify changes — insufficient snapshot history"],
                evidence=[],
                recommendations=["Collect more snapshots over time to enable change analysis"],
                confidence=0.0,
                snapshot_count=len(snapshots),
                generated_at=_now(),
            )

        snap_count = len(snapshots)

        # Step 1: use drift data to find last stable period
        if drift:
            drift_score = drift.get("overall_drift_score", 0.0)
            sig_dims = [t for t in drift.get("drift_trends", []) if t.get("significant")]
            stable_note = (
                "drift analysis indicates significant change" if sig_dims
                else "no significant drift detected — system appears relatively stable"
            )
            drift_ev = [
                f"Overall drift score: {drift_score:.2f}",
                stable_note,
            ]
            for dim in sig_dims[:3]:
                drift_ev.append(
                    f"{dim.get('dimension', '?')}: "
                    f"{dim.get('early_score', 0):.2f} → {dim.get('recent_score', 0):.2f} "
                    f"({dim.get('direction', '?')})"
                )
            steps.append(WorkflowStep(
                step_number=1,
                name="Stability baseline from drift",
                finding=f"Drift score {drift_score:.2f}; {len(sig_dims)} dimension(s) changed significantly",
                evidence=drift_ev,
                signal_count=len(sig_dims),
            ))
            all_evidence.extend(drift_ev)
            if sig_dims:
                findings.append(f"{len(sig_dims)} dimension(s) have drifted significantly from early baseline")
                for dim in sig_dims:
                    findings.append(
                        f"  — {dim.get('dimension', '?')}: {dim.get('direction', '?')} "
                        f"({dim.get('early_score', 0):.2f} → {dim.get('recent_score', 0):.2f})"
                    )
        else:
            steps.append(WorkflowStep(
                step_number=1,
                name="Stability baseline",
                finding="No drift data available — using first vs. last snapshot comparison.",
                evidence=["Drift analysis not provided"],
                signal_count=0,
            ))

        # Step 2: first vs last runtime health
        first = snapshots[0]
        last = snapshots[-1]
        try:
            rt_first = first.get("data", {}).get("runtime_health", {})
            rt_last = last.get("data", {}).get("runtime_health", {})
            s1 = rt_first.get("health_score")
            s2 = rt_last.get("health_score")
            if s1 is not None and s2 is not None:
                delta = s2 - s1
                direction = "improved" if delta > 0.05 else ("degraded" if delta < -0.05 else "stable")
                rt_ev = [f"Runtime: {s1:.2f} → {s2:.2f} ({direction}, Δ{delta:+.2f})"]
                steps.append(WorkflowStep(
                    step_number=2,
                    name="Runtime health change",
                    finding=f"Runtime health {direction} since first snapshot",
                    evidence=rt_ev,
                    signal_count=1 if direction != "stable" else 0,
                ))
                all_evidence.extend(rt_ev)
                if direction != "stable":
                    findings.append(f"Runtime health {direction} ({s1:.2f} → {s2:.2f})")
        except (AttributeError, TypeError):
            pass

        # Step 3: package count change
        def _pkg_count(snap: dict) -> int:
            try:
                return len(snap["data"]["scanner_results"]["results"]["repo_scanner"]["packages"])
            except (KeyError, TypeError):
                return 0

        pkg_first = _pkg_count(first)
        pkg_last = _pkg_count(last)
        pkg_delta = pkg_last - pkg_first
        pkg_ev = [f"Package count: {pkg_first} → {pkg_last} ({pkg_delta:+d})"]
        steps.append(WorkflowStep(
            step_number=3,
            name="Dependency footprint change",
            finding=f"Package count changed by {pkg_delta:+d}",
            evidence=pkg_ev,
            signal_count=abs(pkg_delta),
        ))
        all_evidence.extend(pkg_ev)
        if abs(pkg_delta) >= 2:
            findings.append(f"Dependency footprint changed significantly ({pkg_delta:+d} packages)")

        if not findings:
            findings.append(f"No significant changes identified across {snap_count} snapshots")

        recs.append("Use drift analysis for richer early-vs-recent comparison across multiple dimensions")
        recs.append("Cross-reference changes with recommendation continuity to identify unresolved issues")

        return WorkflowResult(
            query=query,
            steps=steps,
            findings=findings,
            evidence=all_evidence,
            recommendations=recs,
            confidence=_safe_confidence(len(all_evidence), snap_count),
            snapshot_count=snap_count,
            generated_at=_now(),
        )
