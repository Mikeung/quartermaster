"""
Evidence trace — trace operational conclusions back to their source observations.

Enables tracing:
  recommendation → evidence → workflows → scan observations → snapshots

Produces evidence trees that make it possible to understand WHY a
recommendation or severity assessment was produced.

CRITICAL: Trust depends on traceability.

All trace output is:
- bounded (finite depth, bounded node count)
- evidence-backed (every node cites sources)
- advisory only (no operational actions)
- uncertainty-preserving (confidence notes included)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_DEPTH = 3
_MAX_CHILDREN = 5


@dataclass
class EvidenceNode:
    """A single node in an evidence tree."""
    kind: str      # "recommendation", "workflow", "observation", "cost", "snapshot", "runtime", "factor"
    label: str
    evidence: list[str]
    snapshot_id: int | None
    children: list[EvidenceNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "evidence": self.evidence,
            "snapshot_id": self.snapshot_id,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class EvidenceTree:
    """Root of an evidence trace — full traceability from conclusion to observations."""
    root: EvidenceNode
    depth: int
    node_count: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root.to_dict(),
            "depth": self.depth,
            "node_count": self.node_count,
            "generated_at": self.generated_at,
        }


class EvidenceTracer:
    """Trace operational conclusions back to their source evidence.

    All traces are constructed from existing snapshot data — no new
    inferences are made during tracing.
    """

    def trace_recommendation(
        self,
        rec_dict: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> EvidenceTree:
        """Trace a recommendation back through workflows and observations.

        rec_dict: serialized Recommendation dict
        snapshot: snapshot dict containing the recommendation
        """
        snap_id = snapshot.get("id")
        data = snapshot.get("data", {})
        rec_title = rec_dict.get("title", "?")
        category = rec_dict.get("category", "")

        root = EvidenceNode(
            kind="recommendation",
            label=rec_title,
            evidence=[
                f"Category: {category}",
                f"Impact: {rec_dict.get('impact', '?')}",
                f"Confidence: {float(rec_dict.get('confidence', 0.0)):.2f}",
                f"Urgency: {rec_dict.get('urgency', '?')}",
            ],
            snapshot_id=snap_id,
        )

        # Direct evidence from recommendation
        rec_evidence = rec_dict.get("evidence", [])
        if rec_evidence:
            root.children.append(EvidenceNode(
                kind="observation",
                label="Direct recommendation evidence",
                evidence=rec_evidence[:4],
                snapshot_id=snap_id,
            ))

        # Related workflows
        workflows = data.get("workflows", [])
        for wf in workflows[:_MAX_CHILDREN]:
            wf_type = wf.get("workflow_type", "")
            wf_evidence = wf.get("evidence", [])
            if category and (
                category.lower() in wf_type.lower()
                or any(category.lower() in e.lower() for e in wf_evidence)
            ):
                wf_node = EvidenceNode(
                    kind="workflow",
                    label=wf.get("name", wf_type),
                    evidence=[
                        f"Type: {wf_type}",
                        f"Confidence: {float(wf.get('confidence', 0.0)):.2f}",
                        *wf_evidence[:2],
                    ],
                    snapshot_id=snap_id,
                )
                root.children.append(wf_node)

        # Related cost observations
        cost_obs = data.get("cost_observations", [])
        cost_node_evidence: list[str] = []
        for obs in cost_obs:
            if category and category.lower() in obs.get("observation", "").lower():
                cost_node_evidence.append(
                    f"[{obs.get('severity', '?')}] {obs.get('observation', '')[:80]}"
                )
        if cost_node_evidence:
            root.children.append(EvidenceNode(
                kind="cost",
                label="Related cost observations",
                evidence=cost_node_evidence[:3],
                snapshot_id=snap_id,
            ))

        # Runtime signals
        runtime = data.get("runtime_health", {})
        if runtime and runtime.get("overall_status") not in ("healthy", "unknown", None):
            root.children.append(EvidenceNode(
                kind="runtime",
                label=f"Runtime: {runtime.get('overall_status')} (score {runtime.get('health_score', 0.0):.2f})",
                evidence=runtime.get("instability_signals", [])[:3] + runtime.get("resource_pressure", [])[:2],
                snapshot_id=snap_id,
            ))

        # Snapshot anchor
        root.children.append(EvidenceNode(
            kind="snapshot",
            label=f"Snapshot #{snap_id} ({snapshot.get('created_at', '')[:16]} UTC)",
            evidence=[f"Snapshot captured at: {snapshot.get('created_at', '?')}"],
            snapshot_id=snap_id,
        ))

        node_count = 1 + sum(1 + len(c.children) for c in root.children)
        logger.info(
            "Evidence trace complete",
            extra={"kind": "recommendation", "title": rec_title, "node_count": node_count},
        )

        return EvidenceTree(
            root=root,
            depth=2,
            node_count=node_count,
            generated_at=_now(),
        )

    def trace_severity(
        self,
        severity_dict: dict[str, Any],
        snapshot: dict[str, Any],
        temporal: dict[str, Any] | None = None,
    ) -> EvidenceTree:
        """Trace a severity assessment back to its contributing factors.

        severity_dict: serialized SeverityAssessment dict
        snapshot: snapshot dict
        temporal: optional serialized TemporalAnalysis dict
        """
        snap_id = snapshot.get("id")
        data = snapshot.get("data", {})
        level = severity_dict.get("level", "?")
        score = severity_dict.get("score", 0.0)

        root = EvidenceNode(
            kind="observation",
            label=f"Severity assessment: {level.upper()} (score {score:.3f})",
            evidence=severity_dict.get("evidence", ["No severity evidence"])[:4],
            snapshot_id=snap_id,
        )

        # Factor nodes
        for factor in severity_dict.get("factors", [])[:_MAX_CHILDREN]:
            if factor.get("contribution", 0.0) > 0.005:
                factor_node = EvidenceNode(
                    kind="factor",
                    label=f"Factor: {factor.get('name', '?')} (contribution: {factor.get('contribution', 0.0):.3f})",
                    evidence=[
                        factor.get("description", ""),
                        f"Weight: {factor.get('weight', 0.0):.2f}",
                        f"Raw value: {factor.get('raw_value', 0.0):.3f}",
                    ],
                    snapshot_id=snap_id,
                )

                # Attach sub-evidence per factor
                if factor.get("name") == "runtime_instability":
                    rt = data.get("runtime_health", {})
                    if rt:
                        factor_node.children.append(EvidenceNode(
                            kind="runtime",
                            label=f"Runtime: {rt.get('overall_status', '?')}",
                            evidence=rt.get("instability_signals", [])[:3] + rt.get("resource_pressure", [])[:2],
                            snapshot_id=snap_id,
                        ))

                elif factor.get("name") == "recommendation_signal":
                    recs = data.get("recommendations", [])
                    high = [r for r in recs if r.get("impact") == "high"][:3]
                    if high:
                        factor_node.children.append(EvidenceNode(
                            kind="recommendation",
                            label=f"{len(high)} high-impact recommendation(s)",
                            evidence=[r.get("title", "?") for r in high],
                            snapshot_id=snap_id,
                        ))

                elif factor.get("name") == "temporal_volatility" and temporal:
                    factor_node.children.append(EvidenceNode(
                        kind="observation",
                        label=f"Volatility: {temporal.get('volatility_score', 0.0):.2f}",
                        evidence=temporal.get("churn_indicators", [])[:3],
                        snapshot_id=snap_id,
                    ))

                elif factor.get("name") == "cost_amplification":
                    cost_obs = data.get("cost_observations", [])
                    high_cost = [o for o in cost_obs if o.get("severity") == "high"][:3]
                    if high_cost:
                        factor_node.children.append(EvidenceNode(
                            kind="cost",
                            label=f"{len(high_cost)} high-severity cost observation(s)",
                            evidence=[o.get("observation", "?")[:60] for o in high_cost],
                            snapshot_id=snap_id,
                        ))

                root.children.append(factor_node)

        # Snapshot anchor
        root.children.append(EvidenceNode(
            kind="snapshot",
            label=f"Snapshot #{snap_id}",
            evidence=[f"Captured: {snapshot.get('created_at', '?')}"],
            snapshot_id=snap_id,
        ))

        node_count = 1 + sum(1 + len(c.children) for c in root.children)

        logger.info(
            "Evidence trace complete",
            extra={"kind": "severity", "level": level, "node_count": node_count},
        )

        return EvidenceTree(
            root=root,
            depth=_MAX_DEPTH,
            node_count=node_count,
            generated_at=_now(),
        )

    def to_markdown(self, tree: EvidenceTree) -> str:
        """Render an evidence tree as readable markdown."""
        lines: list[str] = [
            "# Evidence Trace",
            f"**Generated:** {tree.generated_at[:16]} UTC",
            f"**Tree depth:** {tree.depth} | **Nodes:** {tree.node_count}",
            "",
        ]
        _render_node(tree.root, lines, depth=0)
        lines += [
            "",
            "---",
            "*Advisory only — all operational decisions require human review.*",
            "*Generated by Quartermaster — Observe automatically. Decide manually.*",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_node(node: EvidenceNode, lines: list[str], depth: int) -> None:
    indent = "  " * depth
    prefix = "#" * min(depth + 2, 6)
    lines.append(f"{prefix} [{node.kind.upper()}] {node.label}")
    for ev in node.evidence:
        if ev:
            lines.append(f"{indent}- {ev}")
    if node.children:
        lines.append("")
    for child in node.children:
        _render_node(child, lines, depth + 1)


def _now() -> str:
    return datetime.now(UTC).isoformat()
