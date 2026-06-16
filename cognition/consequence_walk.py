"""Consequence walk — the WHAT-IF brain.

Given a set of "down" nodes, traverses the persistent dependency graph to answer:

  1. Which downstream nodes go dark?
  2. Which owner-facing outputs are lost?
  3. When multiple nodes are down simultaneously, which is the root cause and
     which are collateral (explained by the root cause's failure)?

This is the synthesis layer the eyes (scanners), memory (graph_store), and voice
(incident reports) were built to support. It reads from GraphStore — both inferred
and human_declared edges — and returns a structured ConsequenceWalk object.
No writes, no side effects. Deterministic: same graph state + same down_nodes →
same ConsequenceWalk.

Answer + Confidence + Evidence discipline:
  - Every affected node carries the evidence chain from root cause to it.
  - Where consequence annotation is "unknown", the structural truth (which nodes
    go dark) is reported and the human-facing consequence is stated as unknown.
    Nothing is fabricated.
  - Confidence degrades with each hop and with edge confidence.

Edge direction contract:
  ALL edges run  dependent (source) → dependency (target).
  DEPENDS_ON:  humint → postgres     (humint depends on postgres)
  READS_FROM:  quartermaster → lesia        (quartermaster's spend tracking depends on lesia's data)
  USES_VENV:   tgbot  → mempalace    (tgbot's process needs the mempalace venv)
  This is enforced in config/operational_graph.yml; inference from topology/builder
  follows the same convention.

Edge classification:
  HARD dependencies  (DEPENDS_ON, USES_VENV)
    → full confidence propagation; source almost certainly fails if target is down.

  SOFT dependencies  (READS_FROM)
    → 0.7× confidence multiplier; source is degraded but continues running.

  Non-propagating   (FEEDS_SPEND_TO, SCANS, EXPOSES_PORT, framework/SDK edges)
    → not traversed. FEEDS_SPEND_TO has producer→consumer direction (opposite
    convention) so it is excluded to avoid incorrect reverse traversal.
    Use READS_FROM (dependent→dependency) for data-feed relationships instead.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.graph_store import GraphStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Edge classification constants
# ---------------------------------------------------------------------------

_HARD_DEP_RELS: frozenset[str] = frozenset({
    "DEPENDS_ON",
    "USES_VENV",
})

_SOFT_DEP_RELS: frozenset[str] = frozenset({
    "READS_FROM",
    # FEEDS_SPEND_TO intentionally excluded: it uses producer→consumer direction
    # (opposite the dependent→dependency convention) and would traverse backwards.
    # Declare data feeds as READS_FROM on the consumer side instead.
})

_ALL_PROPAGATING = _HARD_DEP_RELS | _SOFT_DEP_RELS

_SOFT_CONFIDENCE_MULTIPLIER = 0.7


def _dep_type(relationship: str) -> str:
    return "hard" if relationship in _HARD_DEP_RELS else "soft"


def _propagates(relationship: str) -> bool:
    return relationship in _ALL_PROPAGATING


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

@dataclass
class _MergedEdge:
    """A logical dependency: one or more raw edges between the same (src, tgt) pair,
    merged by taking the maximum confidence and unioning their evidence."""
    source_node_id: str
    target_node_id: str
    relationships: list[str]
    confidence: float
    dependency_type: str          # "hard" | "soft"
    evidence_details: list[str]   # human-readable evidence strings
    collector_types: list[str]


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AffectedNode:
    """A node that goes dark because of the initial failure, reachable via the graph."""
    node_id: str
    builder_node_id: str
    target_id: str
    label: str
    node_type: str
    depth: int                  # minimum hops from any initial down node
    path_confidence: float      # product of edge confidences along the path
    dependency_type: str        # type of the triggering edge: "hard" | "soft"
    consequence: str            # from liveness annotation, or "unknown"
    owner_facing: str           # "true" | "false" | "unknown"
    evidence: list[str]         # key evidence strings along the traversal path

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "builder_node_id": self.builder_node_id,
            "target_id": self.target_id,
            "label": self.label,
            "node_type": self.node_type,
            "depth": self.depth,
            "path_confidence": self.path_confidence,
            "dependency_type": self.dependency_type,
            "consequence": self.consequence,
            "owner_facing": self.owner_facing,
            "evidence": self.evidence,
        }


@dataclass
class RootCause:
    """A node in the initial down set whose own hard dependencies are all still up.
    It failed independently; other down nodes are collateral of this failure."""
    node_id: str
    builder_node_id: str
    target_id: str
    label: str
    consequence: str            # from annotation
    owner_facing: str
    reason: str                 # plain-language explanation
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "builder_node_id": self.builder_node_id,
            "target_id": self.target_id,
            "label": self.label,
            "consequence": self.consequence,
            "owner_facing": self.owner_facing,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class ConsequenceWalk:
    """The structured WHAT-IF result.

    Contains:
      root_causes       — nodes that failed independently (the real cause)
      collateral        — initial down nodes explained by root causes
      affected          — downstream nodes that go dark as a result
      owner_facing_lost — human-facing outputs that are lost
      unknown_consequences — affected nodes whose consequence is not yet declared
    """
    # Input
    hypothetical: list[str]         # down node_ids (input)
    hypothetical_labels: list[str]  # human-readable labels for the input

    # Root cause analysis
    root_causes: list[RootCause]
    collateral: list[str]           # labels of down nodes explained by root causes

    # Cascade
    affected: list[AffectedNode]

    # Operator-facing impact
    owner_facing_lost: list[dict[str, Any]]  # [{label, consequence, confidence, depth}]
    unknown_consequences: list[str]          # labels of affected nodes with unknown consequence

    # Confidence and evidence
    overall_confidence: str         # "High" | "Medium" | "Low"
    evidence_trail: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothetical": self.hypothetical,
            "hypothetical_labels": self.hypothetical_labels,
            "root_causes": [r.to_dict() for r in self.root_causes],
            "collateral": self.collateral,
            "affected": [a.to_dict() for a in self.affected],
            "owner_facing_lost": self.owner_facing_lost,
            "unknown_consequences": self.unknown_consequences,
            "overall_confidence": self.overall_confidence,
            "evidence_trail": self.evidence_trail,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Graph index builders
# ---------------------------------------------------------------------------

def _build_dep_of(raw_edges: list[dict]) -> dict[str, list[_MergedEdge]]:
    """Build reverse adjacency: dep_of[X] = edges where X is the target (dependency).

    dep_of[X] tells us which nodes depend on X. When X goes down, all nodes
    in dep_of[X] are potentially affected.
    """
    # Group raw edges by (src, tgt) and merge
    pairs: dict[tuple[str, str], list[dict]] = {}
    for edge in raw_edges:
        if not _propagates(edge.get("relationship", "")):
            continue
        key = (edge["source_node_id"], edge["target_node_id"])
        pairs.setdefault(key, []).append(edge)

    dep_of: dict[str, list[_MergedEdge]] = {}
    for (src, tgt), group in pairs.items():
        merged = _merge_edges(src, tgt, group)
        dep_of.setdefault(tgt, []).append(merged)
    return dep_of


def _build_hard_deps_of(raw_edges: list[dict]) -> dict[str, list[str]]:
    """Build forward adjacency for HARD deps only.

    hard_deps_of[X] = list of node_ids that X hard-depends on.
    Used for root cause identification: a root cause is a down node
    none of whose hard dependencies are also down.
    """
    result: dict[str, list[str]] = {}
    for edge in raw_edges:
        if edge.get("relationship", "") in _HARD_DEP_RELS:
            src = edge["source_node_id"]
            tgt = edge["target_node_id"]
            result.setdefault(src, []).append(tgt)
    return result


def _merge_edges(
    src: str, tgt: str, group: list[dict]
) -> _MergedEdge:
    """Merge multiple raw edges between the same (src, tgt) into one logical dependency.

    Multiple edges can exist because the same pair may appear in both inferred
    (service_scanner) and human_declared contexts. Union the evidence, take the
    maximum confidence, classify as hard if any edge is hard.
    """
    relationships = sorted({e["relationship"] for e in group})
    confidence = max(float(e.get("confidence", 1.0)) for e in group)
    is_hard = any(e["relationship"] in _HARD_DEP_RELS for e in group)
    dep_type = "hard" if is_hard else "soft"
    collector_types = sorted({e.get("collector_type", "") for e in group})

    evidence_details: list[str] = []
    seen: set[str] = set()
    for e in group:
        for ev in e.get("evidence", []):
            detail = ev.get("detail", "") if isinstance(ev, dict) else str(ev)
            if detail and detail not in seen:
                seen.add(detail)
                evidence_details.append(detail)

    return _MergedEdge(
        source_node_id=src,
        target_node_id=tgt,
        relationships=relationships,
        confidence=confidence,
        dependency_type=dep_type,
        evidence_details=evidence_details,
        collector_types=collector_types,
    )


# ---------------------------------------------------------------------------
# Root cause identification
# ---------------------------------------------------------------------------

def _find_root_causes(
    initial_down: set[str],
    hard_deps_of: dict[str, list[str]],
    nodes_by_id: dict[str, dict],
    all_annotations: dict[str, dict],
) -> tuple[list[RootCause], list[str]]:
    """Partition the initial down set into root causes and collateral.

    A root cause is a node in initial_down none of whose HARD dependencies are
    also in initial_down. Collateral nodes are explained by the root causes.

    Returns (root_causes, collateral_labels).
    """
    root_causes: list[RootCause] = []
    collateral_labels: list[str] = []

    for node_id in sorted(initial_down):
        node = nodes_by_id.get(node_id, {})
        label = node.get("label", node_id)
        ann = all_annotations.get(node_id, {})
        consequence = ann.get("consequence", {}).get("value", "unknown")
        owner_facing = ann.get("owner_facing", {}).get("value", "unknown")

        down_hard_deps = [
            tgt for tgt in hard_deps_of.get(node_id, [])
            if tgt in initial_down
        ]

        if not down_hard_deps:
            root_causes.append(RootCause(
                node_id=node_id,
                builder_node_id=node.get("builder_node_id", ""),
                target_id=node.get("target_id", ""),
                label=label,
                consequence=consequence,
                owner_facing=owner_facing,
                reason=(
                    "None of this node's hard dependencies are in the down set — "
                    "it failed independently."
                ),
                evidence=[
                    f"node {label!r} has no hard-dependency predecessors in the down set"
                ],
            ))
        else:
            dep_labels = [
                nodes_by_id.get(d, {}).get("label", d)
                for d in down_hard_deps
            ]
            collateral_labels.append(
                f"{label} (explained by: {', '.join(dep_labels)})"
            )

    return root_causes, collateral_labels


# ---------------------------------------------------------------------------
# Downstream traversal (BFS)
# ---------------------------------------------------------------------------

def _traverse_downstream(
    initial_down: set[str],
    dep_of: dict[str, list[_MergedEdge]],
    nodes_by_id: dict[str, dict],
    all_annotations: dict[str, dict],
    max_depth: int,
) -> list[AffectedNode]:
    """BFS from all initial down nodes simultaneously.

    Finds all nodes reachable via propagating edges. Tracks the highest-confidence
    path to each reachable node; updates if a better path is found (a node that
    is reachable via two paths keeps the most confident one).

    Cycles are handled by the visited set and max_depth guard.
    """
    # best_conf[node_id] = highest path_confidence seen so far
    best_conf: dict[str, float] = {}
    affected: dict[str, AffectedNode] = {}

    # queue: (node_id, depth, path_confidence, evidence_so_far, dep_type)
    queue: deque[tuple[str, int, float, list[str], str]] = deque()
    for nid in sorted(initial_down):
        queue.append((nid, 0, 1.0, [], "hard"))

    while queue:
        curr_id, depth, path_conf, path_ev, parent_dep_type = queue.popleft()

        if depth >= max_depth:
            continue

        for merged_edge in dep_of.get(curr_id, []):
            dep_id = merged_edge.source_node_id  # the node that depends on curr_id

            if dep_id in initial_down:
                # It's already in the down set — handled as collateral, not new cascade
                continue

            # Propagate confidence: degrade for soft deps
            mult = 1.0 if merged_edge.dependency_type == "hard" else _SOFT_CONFIDENCE_MULTIPLIER
            new_conf = round(path_conf * merged_edge.confidence * mult, 4)

            if new_conf <= best_conf.get(dep_id, 0.0):
                # We already have a better or equal path to this node
                continue

            best_conf[dep_id] = new_conf

            node = nodes_by_id.get(dep_id, {})
            label = node.get("label", dep_id)
            ann = all_annotations.get(dep_id, {})
            consequence = ann.get("consequence", {}).get("value", "unknown")
            owner_facing = ann.get("owner_facing", {}).get("value", "unknown")

            new_ev = path_ev + [
                ev for ev in merged_edge.evidence_details if ev
            ]

            affected[dep_id] = AffectedNode(
                node_id=dep_id,
                builder_node_id=node.get("builder_node_id", ""),
                target_id=node.get("target_id", ""),
                label=label,
                node_type=node.get("node_type", ""),
                depth=depth + 1,
                path_confidence=new_conf,
                dependency_type=merged_edge.dependency_type,
                consequence=consequence,
                owner_facing=owner_facing,
                evidence=new_ev[:10],  # cap evidence list to keep output readable
            )

            queue.append((
                dep_id,
                depth + 1,
                new_conf,
                new_ev,
                merged_edge.dependency_type,
            ))

    return sorted(affected.values(), key=lambda n: (n.depth, n.label))


# ---------------------------------------------------------------------------
# Consequence classification
# ---------------------------------------------------------------------------

def _confidence_level(confidence: float) -> str:
    if confidence >= 0.8:
        return "High"
    if confidence >= 0.5:
        return "Medium"
    return "Low"


def _overall_confidence(
    root_causes: list[RootCause],
    affected: list[AffectedNode],
) -> str:
    if not root_causes:
        return "Low"
    # The most conservative confidence across all root-caused affected paths
    confs: list[float] = [a.path_confidence for a in affected]
    if not confs:
        return "High" if root_causes else "Low"
    return _confidence_level(min(confs))


def _build_owner_facing_lost(
    initial_down: set[str],
    affected: list[AffectedNode],
    nodes_by_id: dict[str, dict],
    all_annotations: dict[str, dict],
) -> list[dict[str, Any]]:
    """Collect all owner_facing=true nodes that are down or affected."""
    lost: list[dict[str, Any]] = []

    # Initial down nodes that are owner-facing
    for node_id in sorted(initial_down):
        node = nodes_by_id.get(node_id, {})
        ann = all_annotations.get(node_id, {})
        if ann.get("owner_facing", {}).get("value") == "true":
            lost.append({
                "label": node.get("label", node_id),
                "consequence": ann.get("consequence", {}).get("value", "unknown"),
                "confidence": "High",
                "depth": 0,
                "node_id": node_id,
            })

    # Downstream affected nodes that are owner-facing
    for node in affected:
        if node.owner_facing == "true":
            lost.append({
                "label": node.label,
                "consequence": node.consequence,
                "confidence": _confidence_level(node.path_confidence),
                "depth": node.depth,
                "node_id": node.node_id,
            })

    return lost


def _build_evidence_trail(
    root_causes: list[RootCause],
    affected: list[AffectedNode],
) -> list[str]:
    """Collect the key evidence strings from the walk, deduped."""
    seen: set[str] = set()
    trail: list[str] = []

    for rc in root_causes:
        for e in rc.evidence:
            if e and e not in seen:
                seen.add(e)
                trail.append(e)

    for node in affected:
        for e in node.evidence:
            if e and e not in seen:
                seen.add(e)
                trail.append(e)

    return trail[:20]  # cap at 20 for readability


def _build_summary(
    initial_down: set[str],
    root_causes: list[RootCause],
    collateral: list[str],
    affected: list[AffectedNode],
    owner_facing_lost: list[dict],
    nodes_by_id: dict[str, dict],
) -> str:
    """Plain-language summary of the consequence walk."""
    down_labels = [
        nodes_by_id.get(nid, {}).get("label", nid)
        for nid in sorted(initial_down)
    ]

    parts: list[str] = []

    if root_causes:
        rc_labels = [rc.label for rc in root_causes]
        parts.append(
            f"Root cause{'s' if len(rc_labels) > 1 else ''}: "
            f"{', '.join(rc_labels)}."
        )
    else:
        parts.append(f"Down: {', '.join(down_labels)}.")

    if collateral:
        parts.append(f"Collateral: {'; '.join(collateral)}.")

    if affected:
        hard_affected = [n.label for n in affected if n.dependency_type == "hard"]
        soft_affected = [n.label for n in affected if n.dependency_type == "soft"]
        if hard_affected:
            parts.append(
                f"Hard cascade: {', '.join(hard_affected)} "
                f"{'goes' if len(hard_affected) == 1 else 'go'} dark."
            )
        if soft_affected:
            parts.append(
                f"Degraded output: {', '.join(soft_affected)}."
            )
    else:
        parts.append("No downstream cascade detected in the graph.")

    if owner_facing_lost:
        items = [f"{x['label']} ({x['consequence']})" for x in owner_facing_lost]
        parts.append(f"Owner-facing impact: {'; '.join(items)}.")

    if not affected and not owner_facing_lost:
        parts.append(
            "Consequence depends on undeclared annotations — "
            "extend config/operational_graph.yml to fill in the gaps."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def walk(
    down_node_ids: list[str],
    graph_store: GraphStore,
    max_depth: int = 10,
) -> ConsequenceWalk:
    """Perform a consequence walk from the given down nodes.

    Args:
        down_node_ids: Node IDs (SHA-256 strings from graph_store) that are
            hypothetically or actually down. Can come from findings, from a
            hypothetical question, or from the current VPS state.
        graph_store: A connected GraphStore instance.
        max_depth: Maximum traversal depth. Default of 10 is sufficient for
            any realistic VPS dependency chain.

    Returns:
        ConsequenceWalk with root causes, cascade, and owner-facing impact.
        Same graph state + same down_node_ids → same result (deterministic).
    """
    if not down_node_ids:
        return ConsequenceWalk(
            hypothetical=[],
            hypothetical_labels=[],
            root_causes=[],
            collateral=[],
            affected=[],
            owner_facing_lost=[],
            unknown_consequences=[],
            overall_confidence="High",
            evidence_trail=[],
            summary="No nodes are down — nothing to walk.",
        )

    # Load the full graph in three queries
    all_nodes_raw = graph_store.get_active_nodes()
    all_edges_raw = graph_store.get_active_edges()
    all_annotations = graph_store.get_all_annotations()

    nodes_by_id: dict[str, dict] = {n["node_id"]: n for n in all_nodes_raw}

    initial_down = set(down_node_ids)
    hypothetical_labels = [
        nodes_by_id.get(nid, {}).get("label", nid)
        for nid in sorted(initial_down)
    ]

    # Build graph indices
    dep_of = _build_dep_of(all_edges_raw)
    hard_deps_of = _build_hard_deps_of(all_edges_raw)

    # Root cause identification
    root_causes, collateral = _find_root_causes(
        initial_down, hard_deps_of, nodes_by_id, all_annotations
    )

    # Downstream cascade
    affected = _traverse_downstream(
        initial_down, dep_of, nodes_by_id, all_annotations, max_depth
    )

    # Operator-facing impact
    owner_facing_lost = _build_owner_facing_lost(
        initial_down, affected, nodes_by_id, all_annotations
    )
    unknown_consequences = [
        n.label for n in affected if n.consequence == "unknown"
    ]

    # Confidence and narrative
    overall_conf = _overall_confidence(root_causes, affected)
    evidence_trail = _build_evidence_trail(root_causes, affected)
    summary = _build_summary(
        initial_down, root_causes, collateral, affected,
        owner_facing_lost, nodes_by_id,
    )

    logger.info(
        "consequence walk: down=%d root_causes=%d affected=%d "
        "owner_facing_lost=%d confidence=%s",
        len(initial_down),
        len(root_causes),
        len(affected),
        len(owner_facing_lost),
        overall_conf,
    )

    return ConsequenceWalk(
        hypothetical=sorted(initial_down),
        hypothetical_labels=hypothetical_labels,
        root_causes=root_causes,
        collateral=collateral,
        affected=affected,
        owner_facing_lost=owner_facing_lost,
        unknown_consequences=unknown_consequences,
        overall_confidence=overall_conf,
        evidence_trail=evidence_trail,
        summary=summary,
    )


def walk_by_label(
    down_labels: list[str],
    graph_store: GraphStore,
    max_depth: int = 10,
) -> ConsequenceWalk:
    """Convenience wrapper: look up node_ids by label, then call walk().

    If a label matches multiple nodes (same name in different targets), all
    matching nodes are included. Unresolved labels are logged as warnings.
    """
    node_ids: list[str] = []
    for label in down_labels:
        matches = graph_store.get_nodes_by_label(label, case_sensitive=False)
        if not matches:
            logger.warning("walk_by_label: no active node found for label %r", label)
        else:
            if len(matches) > 1:
                logger.warning(
                    "walk_by_label: label %r matches %d nodes — including all",
                    label, len(matches),
                )
            node_ids.extend(n["node_id"] for n in matches)

    return walk(node_ids, graph_store, max_depth=max_depth)
