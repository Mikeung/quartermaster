"""
Runtime + topology fusion intelligence.

Correlates runtime instability signals with topology structure
and workflow patterns to surface compound operational concerns.

Examples of compound signals:
- retry-heavy LLM workflow + memory pressure → amplified cost risk
- multi-agent orchestration + container restart churn → continuity risk
- high infrastructure volatility + failing runtime services → system instability
- failed services + LLM workflow dependency → workflow disruption risk

Deterministic. Evidence-backed. Advisory-only.
No speculation about causes. No autonomous action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognition.runtime_health import RuntimeHealthReport

logger = logging.getLogger(__name__)

_RETRY_WORKFLOW_TYPES = frozenset({"llm_retry_loop", "api_rate_limit_handler"})
_MULTI_AGENT_WORKFLOW_TYPES = frozenset({"multi_agent_orchestration", "agent_pipeline"})
_HIGH_COST_WORKFLOW_TYPES = frozenset({
    "multi_agent_orchestration", "rag_pipeline", "llm_retry_loop",
    "agent_pipeline", "streaming_inference",
})

_MEM_PRESSURE_THRESHOLD = 75.0
_VOLATILITY_HIGH_THRESHOLD = 0.55


@dataclass
class FusedInsight:
    """A compound operational concern derived from cross-domain correlation."""
    kind: str                    # e.g. "retry_memory_pressure", "restart_multi_agent"
    title: str
    description: str
    evidence: list[str]
    severity: str                # "low", "moderate", "high", "critical"
    affected_components: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "severity": self.severity,
            "affected_components": self.affected_components,
        }


class RuntimeTopologyFusion:
    """Fuses runtime health signals with topology and workflow intelligence.

    Accepts serialized dicts for topology and workflows so it can work
    with both in-memory objects and stored snapshot payloads.
    Each correlation check is independent and deterministic.
    """

    def fuse(
        self,
        topology_dict: dict[str, Any],
        workflows: list[dict[str, Any]],
        runtime_health: RuntimeHealthReport,
        temporal_volatility: float | None = None,
        cost_observations: list[dict[str, Any]] | None = None,
    ) -> list[FusedInsight]:
        """Produce fused insights by correlating runtime state with topology.

        topology_dict: serialized TopologyGraph dict.
        workflows: list of serialized WorkflowPattern dicts.
        runtime_health: live or recent RuntimeHealthReport.
        temporal_volatility: optional volatility score (0-1) from TemporalAnalysis.
        cost_observations: optional list of CostObservation dicts.
        """
        insights: list[FusedInsight] = []

        workflow_types = {w.get("workflow_type", "") for w in workflows}
        cost_obs = cost_observations or []

        insights.extend(self._retry_memory_pressure(runtime_health, workflow_types, cost_obs))
        insights.extend(self._restart_churn_multi_agent(runtime_health, workflow_types))
        insights.extend(self._volatile_infra_unstable_runtime(runtime_health, temporal_volatility))
        insights.extend(self._failed_service_workflow_risk(runtime_health, workflow_types, workflows))
        insights.extend(self._docker_restarts_llm_workflow(runtime_health, workflow_types))

        insights.sort(key=lambda i: _severity_rank(i.severity), reverse=True)

        logger.info(
            "Runtime topology fusion complete",
            extra={
                "fused_insights": len(insights),
                "runtime_status": runtime_health.overall_status,
                "workflow_count": len(workflows),
            },
        )
        return insights

    # ------------------------------------------------------------------
    # Correlation detectors
    # ------------------------------------------------------------------

    def _retry_memory_pressure(
        self,
        health: RuntimeHealthReport,
        workflow_types: set[str],
        cost_obs: list[dict[str, Any]],
    ) -> list[FusedInsight]:
        if not _RETRY_WORKFLOW_TYPES & workflow_types:
            return []

        mem_ind = _find_indicator(health, "Memory")
        if not mem_ind or mem_ind.status == "ok":
            return []

        has_retry_cost = any(
            "retry" in obs.get("observation", "").lower()
            or "retry" in obs.get("component", "").lower()
            for obs in cost_obs
        )

        evidence = [
            f"Retry-heavy workflow detected: {_RETRY_WORKFLOW_TYPES & workflow_types}",
            f"Memory status: {mem_ind.status} ({mem_ind.value})",
        ]
        if has_retry_cost:
            evidence.append("Cost observation: retry amplification detected in cost intelligence")

        severity = "high" if mem_ind.status in ("stressed", "critical") else "moderate"

        return [FusedInsight(
            kind="retry_memory_pressure",
            title="Retry-heavy LLM workflow under memory pressure",
            description=(
                "A retry or rate-limit workflow is active while memory is under pressure. "
                "Retry loops may amplify LLM call volume and memory consumption concurrently, "
                "increasing both cost and stability risk."
            ),
            evidence=evidence,
            severity=severity,
            affected_components=list(_RETRY_WORKFLOW_TYPES & workflow_types),
        )]

    def _restart_churn_multi_agent(
        self,
        health: RuntimeHealthReport,
        workflow_types: set[str],
    ) -> list[FusedInsight]:
        if not _MULTI_AGENT_WORKFLOW_TYPES & workflow_types:
            return []
        if not health.has_docker_restarts:
            return []

        evidence = [
            f"Multi-agent workflow active: {_MULTI_AGENT_WORKFLOW_TYPES & workflow_types}",
            *health.docker_restart_details[:3],
        ]

        return [FusedInsight(
            kind="restart_churn_multi_agent",
            title="Multi-agent orchestration with container restart churn",
            description=(
                "A multi-agent or pipeline orchestration workflow is running while containers "
                "are experiencing repeated restarts. Restart churn can disrupt agent coordination, "
                "lose in-flight context, and create inconsistent state across pipeline stages."
            ),
            evidence=evidence,
            severity="high",
            affected_components=list(_MULTI_AGENT_WORKFLOW_TYPES & workflow_types),
        )]

    def _volatile_infra_unstable_runtime(
        self,
        health: RuntimeHealthReport,
        temporal_volatility: float | None,
    ) -> list[FusedInsight]:
        if temporal_volatility is None or temporal_volatility < _VOLATILITY_HIGH_THRESHOLD:
            return []
        if health.overall_status not in ("degraded", "stressed", "critical"):
            return []

        evidence = [
            f"Infrastructure volatility score: {temporal_volatility:.2f} "
            f"(threshold: {_VOLATILITY_HIGH_THRESHOLD})",
            f"Runtime status: {health.overall_status} (health score: {health.health_score:.2f})",
            *health.instability_signals[:2],
        ]

        severity = "high" if temporal_volatility >= 0.7 or health.overall_status == "critical" else "moderate"

        return [FusedInsight(
            kind="volatile_infra_unstable_runtime",
            title="Volatile infrastructure with concurrent runtime instability",
            description=(
                "Infrastructure composition is churning (frequent additions/removals of providers, "
                "frameworks, or workflows) while runtime services are simultaneously degraded. "
                "Combined volatility increases operational risk and complicates incident diagnosis."
            ),
            evidence=evidence,
            severity=severity,
            affected_components=["infrastructure", "runtime"],
        )]

    def _failed_service_workflow_risk(
        self,
        health: RuntimeHealthReport,
        workflow_types: set[str],
        workflows: list[dict[str, Any]],
    ) -> list[FusedInsight]:
        if not health.failed_services:
            return []
        if not (_HIGH_COST_WORKFLOW_TYPES & workflow_types):
            return []

        active_workflows = list(_HIGH_COST_WORKFLOW_TYPES & workflow_types)
        evidence = [
            f"Failed services: {', '.join(health.failed_services[:5])}",
            f"Active high-cost workflows: {', '.join(active_workflows)}",
            "Service failures may disrupt LLM workflow dependencies",
        ]

        return [FusedInsight(
            kind="failed_service_workflow_risk",
            title="Failed services risk LLM workflow continuity",
            description=(
                "One or more system services are in a failed state while LLM-driven workflows "
                "are detected in the codebase. Depending on dependencies, service failures may "
                "interrupt workflow execution, cause silent errors, or degrade output quality."
            ),
            evidence=evidence,
            severity="high",
            affected_components=health.failed_services[:5] + active_workflows,
        )]

    def _docker_restarts_llm_workflow(
        self,
        health: RuntimeHealthReport,
        workflow_types: set[str],
    ) -> list[FusedInsight]:
        if not health.has_docker_restarts:
            return []
        if _MULTI_AGENT_WORKFLOW_TYPES & workflow_types:
            return []  # Already covered by restart_churn_multi_agent
        if not workflow_types:
            return []

        evidence = [
            *health.docker_restart_details[:3],
            f"LLM workflow patterns active: {', '.join(list(workflow_types)[:3])}",
        ]

        return [FusedInsight(
            kind="docker_restart_llm_risk",
            title="Container restart instability alongside LLM workflows",
            description=(
                "Docker containers are experiencing repeated restarts while LLM workflow patterns "
                "are present. Container restarts may indicate resource exhaustion or misconfiguration "
                "that could affect LLM service availability."
            ),
            evidence=evidence,
            severity="moderate",
            affected_components=health.docker_restart_details[:3],
        )]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_indicator(health: RuntimeHealthReport, name: str):  # type: ignore[return]
    for ind in health.indicators:
        if ind.name == name:
            return ind
    return None


_SEVERITY_ORDER = {"critical": 3, "high": 2, "moderate": 1, "low": 0}


def _severity_rank(severity: str) -> int:
    return _SEVERITY_ORDER.get(severity, 0)
