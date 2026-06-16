"""Topology persistence adapter.

Translates a TopologyGraph's dict form into GraphStore operations: upsert
every node and edge that appeared in this scan, then reconcile — marking as
resolved anything that previously existed for this target but is now absent.

This is the only bridge between topology/builder.py (ephemeral, per-scan) and
memory/graph_store.py (persistent, evolving). Neither side imports the other.

Collector type is derived from the primary evidence source recorded by the
builder, mapped to the canonical vocabulary used throughout the finding layer:

  Evidence source        → collector_type
  "package_manifest"     → "repo_scanner"
  "filesystem"           → "repo_scanner"
  "service_scanner"      → "service_scanner"
  "import_pattern"       → "llm_detector"
  "import_detected"      → "llm_detector"
  (anything else)        → "repo_scanner"   # conservative default

"human_declared" is reserved for the future operator-meaning layer and will
never be produced here. Its presence in graph_edges.collector_type will signal
to the brain that an edge was explicitly declared by an operator, not inferred.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.graph_store import GraphStore

logger = logging.getLogger(__name__)

_SOURCE_TO_COLLECTOR: dict[str, str] = {
    "package_manifest": "repo_scanner",
    "filesystem": "repo_scanner",
    "service_scanner": "service_scanner",
    "import_pattern": "llm_detector",
    "import_detected": "llm_detector",
}
_COLLECTOR_DEFAULT = "repo_scanner"


def _derive_collector_type(evidence: list[dict[str, str]]) -> str:
    """Return collector_type from the first recognised evidence source."""
    for ev in evidence:
        src = ev.get("source", "")
        if src in _SOURCE_TO_COLLECTOR:
            return _SOURCE_TO_COLLECTOR[src]
    return _COLLECTOR_DEFAULT


def persist_topology(
    topology_dict: dict[str, Any],
    target_id: str,
    graph_store: GraphStore,
    now: datetime | None = None,
) -> dict[str, int]:
    """Persist one topology snapshot and reconcile disappearances.

    Args:
        topology_dict: Output of TopologyGraph.to_dict() — keys "nodes", "edges".
        target_id: The scan target path; scopes node identity so the same
            builder_node_id from two different targets remains distinct.
        graph_store: A connected GraphStore instance.
        now: UTC datetime stamped on all events. Defaults to datetime.now(UTC).
            Pass an explicit value in tests to keep output deterministic.

    Returns:
        {"nodes_upserted", "edges_upserted", "nodes_resolved", "edges_resolved"}

    Determinism guarantee: the same topology_dict + same target_id always
    produces the same set of upserts (same node_ids, same edge_ids). Running it
    twice for the same scan input increments occurrence_count twice but creates
    no duplicate rows and fires no spurious events.
    """
    from memory.graph_store import compute_node_id

    ts = now or datetime.now(UTC)
    nodes = topology_dict.get("nodes", [])
    edges = topology_dict.get("edges", [])

    active_node_ids: set[str] = set()
    active_edge_ids: set[str] = set()

    # --- Upsert nodes first (edges reference node_ids) ---
    for node in nodes:
        result = graph_store.upsert_node(
            target_id=target_id,
            builder_node_id=node["id"],
            node_type=node["node_type"],
            label=node["label"],
            metadata=node.get("metadata") or {},
            collector_type="topology_builder",
            now=ts,
        )
        active_node_ids.add(result["node_id"])

    # --- Upsert edges ---
    for edge in edges:
        source_nid = compute_node_id(target_id, edge["source"])
        target_nid = compute_node_id(target_id, edge["target"])
        evidence = edge.get("evidence", [])
        collector_type = _derive_collector_type(evidence)
        result = graph_store.upsert_edge(
            source_node_id=source_nid,
            target_node_id=target_nid,
            relationship=edge["relationship"],
            collector_type=collector_type,
            confidence=float(edge.get("confidence", 1.0)),
            evidence=evidence,
            now=ts,
        )
        active_edge_ids.add(result["edge_id"])

    # --- Reconcile: resolve anything for this target that didn't appear ---
    nodes_resolved = graph_store.mark_nodes_resolved(active_node_ids, target_id, ts)
    edges_resolved = graph_store.mark_edges_resolved(active_edge_ids, target_id, ts)

    summary = {
        "nodes_upserted": len(nodes),
        "edges_upserted": len(edges),
        "nodes_resolved": nodes_resolved,
        "edges_resolved": edges_resolved,
    }
    logger.info(
        "topology persisted: target=%s nodes=%d edges=%d "
        "resolved_nodes=%d resolved_edges=%d",
        target_id,
        len(nodes),
        len(edges),
        nodes_resolved,
        edges_resolved,
    )
    return summary
