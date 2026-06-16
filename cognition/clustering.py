"""
Concern clustering — group related operational concerns into named clusters.

Examples:
- OCR cost + retry amplification + memory pressure  → "high-cost OCR processing cluster"
- multi-agent + orchestration sprawl + restart churn → "unstable orchestration cluster"

IMPORTANT:
- Rule-based only. Deterministic scoring.
- Clusters are organizational aids. NOT assertions of causality.
- Every cluster member cites its source signal.
- Cluster membership is scored, not binary — partial clusters are reported.

Advisory only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognition.heuristics import HeuristicRegistry

logger = logging.getLogger(__name__)

_HEURISTICS = HeuristicRegistry()


@dataclass
class ConcernCluster:
    """A named grouping of related operational concerns.

    Not a causal assertion. An organizational aid for operator attention.
    Clusters help operators see related signals together rather than as
    isolated findings.
    """
    name: str
    label: str
    description: str
    member_recommendations: list[str]    # matched recommendation titles
    member_patterns: list[str]           # matched pattern names
    member_workflows: list[str]          # matched workflow types
    member_runtime_signals: list[str]    # matched instability signals
    member_drift_indicators: list[str]   # matched drift change types
    evidence: list[str]
    severity_hint: str
    cluster_score: float                 # 0.0-1.0, how densely populated
    active: bool                         # True if cluster_score >= minimum threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "member_recommendations": self.member_recommendations,
            "member_patterns": self.member_patterns,
            "member_workflows": self.member_workflows,
            "member_runtime_signals": self.member_runtime_signals,
            "member_drift_indicators": self.member_drift_indicators,
            "evidence": self.evidence,
            "severity_hint": self.severity_hint,
            "cluster_score": round(self.cluster_score, 3),
            "active": self.active,
            "note": "Clusters are organizational aids — not causal assertions.",
        }


class ConcernClusteringEngine:
    """Groups related operational concerns into named clusters.

    Uses rule-based scoring against 5 predefined cluster templates.
    Each template has a set of signal sources; the cluster score
    reflects how many of those sources are currently populated.

    Deterministic. Explainable. No ML.
    """

    def cluster(
        self,
        recommendations: list[dict[str, Any]],
        patterns: list[dict[str, Any]] | None = None,
        runtime_health: dict[str, Any] | None = None,
        drift_events: list[dict[str, Any]] | None = None,
        workflows: list[dict[str, Any]] | None = None,
    ) -> list[ConcernCluster]:
        """Compute concern clusters from available signals.

        Returns all clusters, sorted by cluster_score descending.
        Only clusters with active=True have score >= minimum threshold.
        """
        matched_patterns = {p["name"] for p in (patterns or []) if p.get("matched")}
        rec_titles = [r.get("title", "") for r in recommendations]
        rec_categories = {r.get("category", "") for r in recommendations}
        rt = runtime_health or {}
        rt_signals = set(rt.get("instability_signals", []))
        drift_types = {e.get("change_type", "") for e in (drift_events or [])}
        workflow_types = {w.get("workflow_type", "") for w in (workflows or [])}

        clusters = [
            self._high_cost_llm_processing(matched_patterns, rec_titles, rec_categories, rt),
            self._unstable_orchestration(matched_patterns, rec_categories, workflow_types, rt_signals, drift_types),
            self._provider_risk(matched_patterns, rec_categories, workflow_types),
            self._runtime_degradation(rt, rt_signals, drift_types, matched_patterns),
            self._cost_accumulation(rec_titles, rec_categories, matched_patterns, rt),
        ]

        result = sorted(clusters, key=lambda c: -c.cluster_score)

        logger.info(
            "Clustering complete",
            extra={
                "total_clusters": len(result),
                "active_clusters": sum(1 for c in result if c.active),
            },
        )
        return result

    def active_only(self, clusters: list[ConcernCluster]) -> list[ConcernCluster]:
        return [c for c in clusters if c.active]

    # ------------------------------------------------------------------
    # Cluster builders
    # ------------------------------------------------------------------

    def _high_cost_llm_processing(
        self,
        pattern_names: set[str],
        rec_titles: list[str],
        rec_categories: set[str],
        rt: dict,
    ) -> ConcernCluster:
        signals = 0
        max_signals = 5
        members_p: list[str] = []
        members_r: list[str] = []
        members_rt: list[str] = []
        evidence: list[str] = []

        cost_patterns = pattern_names & {"retry_amplification", "ocr_token_amplification", "cost_blind_rag"}
        if cost_patterns:
            signals += len(cost_patterns)
            members_p.extend(sorted(cost_patterns))
            evidence.append(f"Cost-risk patterns: {', '.join(sorted(cost_patterns))}")

        cost_recs = [t for t in rec_titles if any(kw in t.lower() for kw in ("cost", "token", "ocr", "retry"))]
        if cost_recs:
            signals += 1
            members_r.extend(cost_recs[:3])
            evidence.append(f"{len(cost_recs)} cost/token/OCR-related recommendation(s)")

        if "cost" in rec_categories or "llm" in rec_categories:
            signals += 1
            evidence.append("Cost or LLM recommendation category active")

        mem_pressure = any("Memory" in s or "memory" in s for s in rt.get("resource_pressure", []))
        if mem_pressure:
            signals += 1
            members_rt.append("memory_pressure")
            evidence.append("Memory pressure detected in runtime")

        score = _score(signals, max_signals)
        return ConcernCluster(
            name="high_cost_llm_processing",
            label="High-Cost LLM Processing",
            description="Converging signals around elevated or uncontrolled LLM processing costs",
            member_recommendations=members_r,
            member_patterns=members_p,
            member_workflows=[],
            member_runtime_signals=members_rt,
            member_drift_indicators=[],
            evidence=evidence[:5],
            severity_hint="high" if score >= 0.60 else "moderate",
            cluster_score=score,
            active=score >= _HEURISTICS.threshold("cluster_minimum_score"),
        )

    def _unstable_orchestration(
        self,
        pattern_names: set[str],
        rec_categories: set[str],
        workflow_types: set[str],
        rt_signals: set[str],
        drift_types: set[str],
    ) -> ConcernCluster:
        signals = 0
        max_signals = 5
        members_p: list[str] = []
        members_wf: list[str] = []
        members_rt: list[str] = []
        members_d: list[str] = []
        evidence: list[str] = []

        orch_patterns = pattern_names & {
            "framework_stacking", "orchestration_sprawl", "excessive_multi_agent_layering",
            "unstable_worker_pattern"
        }
        if orch_patterns:
            signals += min(len(orch_patterns), 2)
            members_p.extend(sorted(orch_patterns))
            evidence.append(f"Orchestration patterns: {', '.join(sorted(orch_patterns))}")

        ma_workflows = workflow_types & {"multi_agent_orchestration", "agent_pipeline"}
        if ma_workflows:
            signals += 1
            members_wf.extend(sorted(ma_workflows))
            evidence.append(f"Multi-agent workflow(s): {', '.join(sorted(ma_workflows))}")

        restart_signals = {s for s in rt_signals if "restart" in s.lower() or "churn" in s.lower()}
        if restart_signals:
            signals += 1
            members_rt.extend(sorted(restart_signals)[:2])
            evidence.append("Container restart/churn signals detected")

        churn_drifts = {"workflows_changed", "agent_added", "agent_removed"} & drift_types
        if churn_drifts:
            signals += 1
            members_d.extend(sorted(churn_drifts))
            evidence.append(f"Orchestration drift events: {', '.join(sorted(churn_drifts))}")

        score = _score(signals, max_signals)
        return ConcernCluster(
            name="unstable_orchestration",
            label="Unstable Orchestration",
            description="Converging signals around complex, unstable multi-agent orchestration",
            member_recommendations=[],
            member_patterns=members_p,
            member_workflows=members_wf,
            member_runtime_signals=members_rt,
            member_drift_indicators=members_d,
            evidence=evidence[:5],
            severity_hint="high" if score >= 0.60 else "moderate",
            cluster_score=score,
            active=score >= _HEURISTICS.threshold("cluster_minimum_score"),
        )

    def _provider_risk(
        self,
        pattern_names: set[str],
        rec_categories: set[str],
        workflow_types: set[str],
    ) -> ConcernCluster:
        signals = 0
        max_signals = 4
        members_p: list[str] = []
        members_wf: list[str] = []
        evidence: list[str] = []

        prov_patterns = pattern_names & {"single_provider_dependency", "volatile_provider_switching"}
        if prov_patterns:
            signals += len(prov_patterns)
            members_p.extend(sorted(prov_patterns))
            evidence.append(f"Provider risk patterns: {', '.join(sorted(prov_patterns))}")

        prov_cats = {c for c in rec_categories if any(kw in c for kw in ("provider", "routing", "llm"))}
        if prov_cats:
            signals += 1
            evidence.append(f"Provider/routing recommendation categories: {', '.join(sorted(prov_cats))}")

        high_cost_wf = workflow_types & {"rag_pipeline", "multi_agent_orchestration", "agent_pipeline"}
        if high_cost_wf:
            signals += 1
            members_wf.extend(sorted(high_cost_wf)[:2])
            evidence.append(f"High-cost workflow(s) present: {', '.join(sorted(high_cost_wf)[:2])}")

        score = _score(signals, max_signals)
        return ConcernCluster(
            name="provider_risk",
            label="LLM Provider Risk",
            description="Structural dependency or switching risk in LLM provider configuration",
            member_recommendations=[],
            member_patterns=members_p,
            member_workflows=members_wf,
            member_runtime_signals=[],
            member_drift_indicators=[],
            evidence=evidence[:5],
            severity_hint="high" if "single_provider_dependency" in prov_patterns else "moderate",
            cluster_score=score,
            active=score >= _HEURISTICS.threshold("cluster_minimum_score"),
        )

    def _runtime_degradation(
        self,
        rt: dict,
        rt_signals: set[str],
        drift_types: set[str],
        pattern_names: set[str],
    ) -> ConcernCluster:
        signals = 0
        max_signals = 5
        members_rt: list[str] = []
        members_p: list[str] = []
        members_d: list[str] = []
        evidence: list[str] = []

        rt_score = rt.get("health_score", 1.0) if rt else 1.0
        rt_status = rt.get("overall_status", "unknown") if rt else "unknown"
        if rt_status in ("degraded", "critical") or rt_score < 0.60:
            signals += 2
            evidence.append(f"Runtime health: {rt_status} (score {rt_score:.2f})")

        failed_services = rt.get("failed_services", []) if rt else []
        if failed_services:
            signals += 1
            members_rt.extend(failed_services[:3])
            evidence.append(f"{len(failed_services)} failed service(s): {', '.join(failed_services[:2])}")

        if rt_signals:
            signals += 1
            members_rt.extend(list(rt_signals)[:2])
            evidence.append(f"Instability signals: {', '.join(list(rt_signals)[:2])}")

        drift_signals = drift_types & {"service_removed", "service_added", "dependency_changed"}
        if drift_signals:
            signals += 1
            members_d.extend(sorted(drift_signals))
            evidence.append(f"Runtime-related drift: {', '.join(sorted(drift_signals))}")

        rt_pattern = pattern_names & {"unstable_worker_pattern"}
        if rt_pattern:
            members_p.extend(sorted(rt_pattern))
            evidence.append("Unstable worker pattern matched")

        score = _score(signals, max_signals)
        return ConcernCluster(
            name="runtime_degradation",
            label="Runtime Degradation",
            description="Converging signals around degraded or unstable runtime health",
            member_recommendations=[],
            member_patterns=members_p,
            member_workflows=[],
            member_runtime_signals=list(set(members_rt))[:5],
            member_drift_indicators=members_d,
            evidence=evidence[:5],
            severity_hint="high" if rt_score < 0.40 or len(failed_services) >= 3 else "moderate",
            cluster_score=score,
            active=score >= _HEURISTICS.threshold("cluster_minimum_score"),
        )

    def _cost_accumulation(
        self,
        rec_titles: list[str],
        rec_categories: set[str],
        pattern_names: set[str],
        rt: dict,
    ) -> ConcernCluster:
        signals = 0
        max_signals = 4
        members_r: list[str] = []
        members_p: list[str] = []
        evidence: list[str] = []

        cost_recs = [t for t in rec_titles if "cost" in t.lower() or "budget" in t.lower()]
        if cost_recs:
            signals += 1
            members_r.extend(cost_recs[:3])
            evidence.append(f"{len(cost_recs)} cost/budget recommendation(s)")

        if "cost" in rec_categories:
            signals += 1
            evidence.append("Cost category recommendations present")

        cost_patterns = pattern_names & {"cost_blind_rag", "retry_amplification"}
        if cost_patterns:
            signals += 1
            members_p.extend(sorted(cost_patterns))
            evidence.append(f"Cost-risk patterns: {', '.join(sorted(cost_patterns))}")

        resource_pressure = rt.get("resource_pressure", []) if rt else []
        if resource_pressure:
            signals += 1
            evidence.append(f"Resource pressure: {', '.join(resource_pressure[:2])}")

        score = _score(signals, max_signals)
        return ConcernCluster(
            name="cost_accumulation",
            label="Cost Accumulation",
            description="Persistent cost concerns accumulating without resolution",
            member_recommendations=members_r,
            member_patterns=members_p,
            member_workflows=[],
            member_runtime_signals=[],
            member_drift_indicators=[],
            evidence=evidence[:5],
            severity_hint="high" if score >= 0.70 else "moderate",
            cluster_score=score,
            active=score >= _HEURISTICS.threshold("cluster_minimum_score"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score(signals: int, max_signals: int) -> float:
    return round(min(signals / max(max_signals, 1), 1.0), 3)
