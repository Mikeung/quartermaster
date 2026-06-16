"""
Historical comparison engine — compare operational states between two snapshots.

Compares across:
- topology (nodes added/removed, edge changes)
- workflows (patterns added/removed, confidence shifts)
- runtime health (status, score delta, instability signals)
- recommendations (new, resolved, persisting)
- cost observations (new concerns, resolved, escalations)
- severity (level change, score delta, contributing factors)

All output is deterministic, bounded, and evidence-backed.
No causal claims. No speculation.
Advisory output only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_CONFIDENCE_CHANGE_THRESHOLD = 0.10
_HEALTH_DEGRADED_THRESHOLD = -0.05
_SEVERITY_ORDER = {"informational": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}


@dataclass
class TopologyDelta:
    nodes_added: list[str]
    nodes_removed: list[str]
    edges_added: list[str]
    edges_removed: list[str]
    node_count_delta: int
    edge_count_delta: int

    @property
    def has_changes(self) -> bool:
        return bool(self.nodes_added or self.nodes_removed
                    or self.edges_added or self.edges_removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "edges_added": self.edges_added,
            "edges_removed": self.edges_removed,
            "node_count_delta": self.node_count_delta,
            "edge_count_delta": self.edge_count_delta,
        }


@dataclass
class WorkflowDelta:
    workflows_added: list[str]
    workflows_removed: list[str]
    confidence_changes: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.workflows_added or self.workflows_removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflows_added": self.workflows_added,
            "workflows_removed": self.workflows_removed,
            "confidence_changes": self.confidence_changes,
        }


@dataclass
class RuntimeDelta:
    status_a: str
    status_b: str
    status_changed: bool
    health_score_a: float
    health_score_b: float
    health_score_delta: float
    new_instability_signals: list[str]
    resolved_instability_signals: list[str]
    new_resource_pressure: list[str]
    resolved_resource_pressure: list[str]

    @property
    def degraded(self) -> bool:
        return self.health_score_delta < _HEALTH_DEGRADED_THRESHOLD

    @property
    def improved(self) -> bool:
        return self.health_score_delta > abs(_HEALTH_DEGRADED_THRESHOLD)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_a": self.status_a,
            "status_b": self.status_b,
            "status_changed": self.status_changed,
            "health_score_a": round(self.health_score_a, 3),
            "health_score_b": round(self.health_score_b, 3),
            "health_score_delta": round(self.health_score_delta, 3),
            "new_instability_signals": self.new_instability_signals,
            "resolved_instability_signals": self.resolved_instability_signals,
            "new_resource_pressure": self.new_resource_pressure,
            "resolved_resource_pressure": self.resolved_resource_pressure,
        }


@dataclass
class RecommendationDelta:
    new_recommendations: list[str]
    resolved_recommendations: list[str]
    persisting_recommendations: list[str]
    high_impact_new: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_recommendations": self.new_recommendations,
            "resolved_recommendations": self.resolved_recommendations,
            "persisting_recommendations": self.persisting_recommendations,
            "high_impact_new": self.high_impact_new,
        }


@dataclass
class CostDelta:
    new_cost_concerns: list[str]
    resolved_cost_concerns: list[str]
    severity_escalations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_cost_concerns": self.new_cost_concerns,
            "resolved_cost_concerns": self.resolved_cost_concerns,
            "severity_escalations": self.severity_escalations,
        }


@dataclass
class SeverityDelta:
    level_a: str
    level_b: str
    score_a: float
    score_b: float
    score_delta: float
    level_changed: bool
    escalated: bool
    contributing_factors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level_a": self.level_a,
            "level_b": self.level_b,
            "score_a": round(self.score_a, 3),
            "score_b": round(self.score_b, 3),
            "score_delta": round(self.score_delta, 3),
            "level_changed": self.level_changed,
            "escalated": self.escalated,
            "contributing_factors": self.contributing_factors,
        }


@dataclass
class SnapshotComparison:
    """Full operational state comparison between two snapshots."""
    snapshot_a_id: int
    snapshot_b_id: int
    created_at_a: str
    created_at_b: str
    topology_delta: TopologyDelta
    workflow_delta: WorkflowDelta
    runtime_delta: RuntimeDelta
    recommendation_delta: RecommendationDelta
    cost_delta: CostDelta
    severity_delta: SeverityDelta
    overall_summary: str
    change_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_a_id": self.snapshot_a_id,
            "snapshot_b_id": self.snapshot_b_id,
            "created_at_a": self.created_at_a,
            "created_at_b": self.created_at_b,
            "topology_delta": self.topology_delta.to_dict(),
            "workflow_delta": self.workflow_delta.to_dict(),
            "runtime_delta": self.runtime_delta.to_dict(),
            "recommendation_delta": self.recommendation_delta.to_dict(),
            "cost_delta": self.cost_delta.to_dict(),
            "severity_delta": self.severity_delta.to_dict(),
            "overall_summary": self.overall_summary,
            "change_count": self.change_count,
        }


class ComparisonEngine:
    """Compare two snapshots across all operational dimensions.

    snapshot_a is treated as the baseline (earlier / reference).
    snapshot_b is treated as the current state (later / comparison target).
    """

    def compare(
        self,
        snapshot_a: dict[str, Any],
        snapshot_b: dict[str, Any],
    ) -> SnapshotComparison:
        data_a = snapshot_a.get("data", {})
        data_b = snapshot_b.get("data", {})

        topo = self._topology(data_a, data_b)
        wf = self._workflows(data_a, data_b)
        rt = self._runtime(data_a, data_b)
        rec = self._recommendations(data_a, data_b)
        cost = self._costs(data_a, data_b)
        sev = self._severity(data_a, data_b)

        change_count = (
            len(topo.nodes_added) + len(topo.nodes_removed)
            + len(wf.workflows_added) + len(wf.workflows_removed)
            + len(rt.new_instability_signals)
            + len(rec.new_recommendations)
            + len(cost.new_cost_concerns)
        )

        summary = _build_summary(snapshot_a, snapshot_b, topo, wf, rt, rec, cost, sev)

        logger.info(
            "Snapshot comparison complete",
            extra={
                "snapshot_a": snapshot_a.get("id"),
                "snapshot_b": snapshot_b.get("id"),
                "change_count": change_count,
                "severity_escalated": sev.escalated,
            },
        )

        return SnapshotComparison(
            snapshot_a_id=snapshot_a.get("id", 0),
            snapshot_b_id=snapshot_b.get("id", 0),
            created_at_a=snapshot_a.get("created_at", ""),
            created_at_b=snapshot_b.get("created_at", ""),
            topology_delta=topo,
            workflow_delta=wf,
            runtime_delta=rt,
            recommendation_delta=rec,
            cost_delta=cost,
            severity_delta=sev,
            overall_summary=summary,
            change_count=change_count,
        )

    # ------------------------------------------------------------------
    # Delta computation helpers
    # ------------------------------------------------------------------

    def _topology(self, data_a: dict, data_b: dict) -> TopologyDelta:
        topo_a = data_a.get("topology", {})
        topo_b = data_b.get("topology", {})

        node_labels_a = {n.get("id", ""): n.get("label", n.get("id", "")) for n in topo_a.get("nodes", [])}
        node_labels_b = {n.get("id", ""): n.get("label", n.get("id", "")) for n in topo_b.get("nodes", [])}

        ids_a = set(node_labels_a.keys())
        ids_b = set(node_labels_b.keys())

        def edge_key(e: dict) -> str:
            return f"{e.get('source', '')}→{e.get('target', '')}"

        edges_a = {edge_key(e) for e in topo_a.get("edges", [])}
        edges_b = {edge_key(e) for e in topo_b.get("edges", [])}

        return TopologyDelta(
            nodes_added=[node_labels_b.get(i, i) for i in (ids_b - ids_a)][:10],
            nodes_removed=[node_labels_a.get(i, i) for i in (ids_a - ids_b)][:10],
            edges_added=list(edges_b - edges_a)[:10],
            edges_removed=list(edges_a - edges_b)[:10],
            node_count_delta=topo_b.get("node_count", 0) - topo_a.get("node_count", 0),
            edge_count_delta=topo_b.get("edge_count", 0) - topo_a.get("edge_count", 0),
        )

    def _workflows(self, data_a: dict, data_b: dict) -> WorkflowDelta:
        def wf_map(data: dict) -> dict[str, float]:
            return {
                w.get("workflow_type", ""): float(w.get("confidence", 0.0))
                for w in data.get("workflows", [])
            }

        map_a = wf_map(data_a)
        map_b = wf_map(data_b)
        types_a = set(map_a.keys())
        types_b = set(map_b.keys())

        confidence_changes: list[str] = []
        for wf_type in types_a & types_b:
            delta = map_b[wf_type] - map_a[wf_type]
            if abs(delta) >= _CONFIDENCE_CHANGE_THRESHOLD:
                direction = "increased" if delta > 0 else "decreased"
                confidence_changes.append(
                    f"'{wf_type}' confidence {direction}: "
                    f"{map_a[wf_type]:.2f} → {map_b[wf_type]:.2f}"
                )

        return WorkflowDelta(
            workflows_added=list(types_b - types_a),
            workflows_removed=list(types_a - types_b),
            confidence_changes=confidence_changes[:5],
        )

    def _runtime(self, data_a: dict, data_b: dict) -> RuntimeDelta:
        rt_a = data_a.get("runtime_health", {})
        rt_b = data_b.get("runtime_health", {})

        sigs_a = set(rt_a.get("instability_signals", []))
        sigs_b = set(rt_b.get("instability_signals", []))
        pressure_a = set(rt_a.get("resource_pressure", []))
        pressure_b = set(rt_b.get("resource_pressure", []))

        status_a = rt_a.get("overall_status", "unknown")
        status_b = rt_b.get("overall_status", "unknown")
        score_a = rt_a.get("health_score", 1.0)
        score_b = rt_b.get("health_score", 1.0)

        return RuntimeDelta(
            status_a=status_a,
            status_b=status_b,
            status_changed=status_a != status_b,
            health_score_a=score_a,
            health_score_b=score_b,
            health_score_delta=round(score_b - score_a, 3),
            new_instability_signals=list(sigs_b - sigs_a)[:5],
            resolved_instability_signals=list(sigs_a - sigs_b)[:5],
            new_resource_pressure=list(pressure_b - pressure_a)[:5],
            resolved_resource_pressure=list(pressure_a - pressure_b)[:5],
        )

    def _recommendations(self, data_a: dict, data_b: dict) -> RecommendationDelta:
        recs_a = {r.get("title", ""): r for r in data_a.get("recommendations", [])}
        recs_b = {r.get("title", ""): r for r in data_b.get("recommendations", [])}
        titles_a = set(recs_a)
        titles_b = set(recs_b)

        new = list(titles_b - titles_a)
        high_impact_new = [t for t in new if recs_b.get(t, {}).get("impact") == "high"]

        return RecommendationDelta(
            new_recommendations=new[:10],
            resolved_recommendations=list(titles_a - titles_b)[:10],
            persisting_recommendations=list(titles_a & titles_b)[:10],
            high_impact_new=high_impact_new[:5],
        )

    def _costs(self, data_a: dict, data_b: dict) -> CostDelta:
        _sev = {"info": 0, "warning": 1, "high": 2}

        def key(o: dict) -> str:
            return o.get("observation", "")[:60].strip()

        obs_a = {key(o): o for o in data_a.get("cost_observations", []) if key(o)}
        obs_b = {key(o): o for o in data_b.get("cost_observations", []) if key(o)}
        keys_a = set(obs_a)
        keys_b = set(obs_b)

        escalations: list[str] = []
        for k in keys_a & keys_b:
            sev_a = _sev.get(obs_a[k].get("severity", "info"), 0)
            sev_b = _sev.get(obs_b[k].get("severity", "info"), 0)
            if sev_b > sev_a:
                escalations.append(f"'{k[:50]}' escalated: {obs_a[k].get('severity')} → {obs_b[k].get('severity')}")

        return CostDelta(
            new_cost_concerns=list(keys_b - keys_a)[:8],
            resolved_cost_concerns=list(keys_a - keys_b)[:8],
            severity_escalations=escalations[:5],
        )

    def _severity(self, data_a: dict, data_b: dict) -> SeverityDelta:
        from cognition.severity import SeverityEngine

        def assess(data: dict):
            rt = data.get("runtime_health", {})
            hs = rt.get("health_score") if rt else None
            return SeverityEngine().assess(
                runtime_health_score=hs,
                recommendations=data.get("recommendations", []),
                cost_observations=data.get("cost_observations", []),
            )

        sev_a = assess(data_a)
        sev_b = assess(data_b)

        score_delta = round(sev_b.score - sev_a.score, 3)
        level_changed = sev_a.level != sev_b.level
        escalated = _SEVERITY_ORDER.get(sev_b.level.value, 0) > _SEVERITY_ORDER.get(sev_a.level.value, 0)

        factors: list[str] = []
        if level_changed:
            factors.append(f"Level changed: {sev_a.level.value} → {sev_b.level.value}")
        if abs(score_delta) > 0.02:
            direction = "increased" if score_delta > 0 else "decreased"
            factors.append(f"Score {direction} by {abs(score_delta):.3f}")

        fa = {f.name: f.contribution for f in sev_a.factors}
        fb = {f.name: f.contribution for f in sev_b.factors}
        for name in fa:
            delta = fb.get(name, 0.0) - fa.get(name, 0.0)
            if abs(delta) > 0.02:
                d = "increased" if delta > 0 else "decreased"
                factors.append(f"Factor '{name}' {d}: {delta:+.3f}")

        return SeverityDelta(
            level_a=sev_a.level.value,
            level_b=sev_b.level.value,
            score_a=sev_a.score,
            score_b=sev_b.score,
            score_delta=score_delta,
            level_changed=level_changed,
            escalated=escalated,
            contributing_factors=factors[:6],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_summary(
    snap_a: dict, snap_b: dict,
    topo: TopologyDelta, wf: WorkflowDelta,
    rt: RuntimeDelta, rec: RecommendationDelta,
    cost: CostDelta, sev: SeverityDelta,
) -> str:
    parts: list[str] = []

    if topo.has_changes:
        parts.append(f"Topology: +{len(topo.nodes_added)}/-{len(topo.nodes_removed)} nodes")

    if wf.has_changes:
        parts.append(f"Workflows: +{len(wf.workflows_added)}/-{len(wf.workflows_removed)}")

    if rt.status_changed:
        parts.append(f"Runtime: {rt.status_a} → {rt.status_b}")
    elif rt.degraded:
        parts.append(f"Runtime: degraded ({rt.health_score_delta:+.3f})")

    if rec.new_recommendations:
        parts.append(f"{len(rec.new_recommendations)} new recommendation(s)")
    if rec.resolved_recommendations:
        parts.append(f"{len(rec.resolved_recommendations)} resolved recommendation(s)")

    if cost.new_cost_concerns:
        parts.append(f"{len(cost.new_cost_concerns)} new cost concern(s)")

    if sev.level_changed:
        direction = "escalated" if sev.escalated else "improved"
        parts.append(f"Severity {direction}: {sev.level_a} → {sev.level_b}")

    if not parts:
        return (
            f"Snapshot #{snap_a.get('id')} → #{snap_b.get('id')}: "
            "No significant operational changes detected."
        )

    return f"Snapshot #{snap_a.get('id')} → #{snap_b.get('id')}: " + "; ".join(parts) + "."
