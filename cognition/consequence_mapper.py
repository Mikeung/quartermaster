"""Consequence mapper — bridge between findings and the graph-based walk.

Maps an open finding to its corresponding graph node (if one exists) and runs
the consequence walk to produce evidence-backed framing for reports and alerts.

Contract:
  - Returns None (not an error) when a finding has no graph node: findings on
    economic targets, unmapped resources, or node types we haven't declared just
    pass through unchanged.
  - Never raises: all exceptions are caught and logged. A mapping failure must
    never break an incident report or a Telegram notification.
  - Deterministic: same graph state + same finding → same framing dict.
  - Never fabricates: if consequence annotations are "unknown" the framing says so.

Finding → node mapping heuristics (conservative):
  target_id == "economic"   → no mapping (cost findings are not service nodes)
  target_id == "vps"        → normalise resource to a service label; search vps nodes
  otherwise                 → search for the repo node whose target path ends with
                              "/" + target_id, or whose builder_node_id = "repo:" + target_id

Resource normalisation for VPS findings:
  "postgresql@16-main.service" → "postgresql"
  "tgbot.service"              → "tgbot"
  "redis-server.service"       → "redis-server"
  "port:8001"                  → "" (ports skipped — no stable node label)
  "node" / "dbus-daemon"       → as-is (may not match any declared node)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.graph_store import GraphStore

logger = logging.getLogger(__name__)

# Finding target_ids that never map to graph nodes
_NON_GRAPH_TARGETS: frozenset[str] = frozenset({"economic"})

# ---------------------------------------------------------------------------
# Consequence-based severity ranking
# ---------------------------------------------------------------------------

_SEV_RANK: dict[str, int] = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}


def _max_severity(a: str, b: str) -> str:
    """Return whichever severity is higher (never lower the floor)."""
    return a if _SEV_RANK.get(a, 0) >= _SEV_RANK.get(b, 0) else b


def _compute_consequence_rank(
    owner_facing_lost: list,
    affected_labels: list,
    base_severity: str,
) -> tuple[str, str, bool]:
    """Derive (tier, consequence_severity, escalated) from walk output.

    Ranking rules — consequence raises the floor, never lowers it:
      owner_facing_loss  → floor = HIGH   (operator output is provably lost)
      structural_cascade → floor = MEDIUM (nodes go dark but impact unknown)
      no_cascade / no_node → unchanged    (leave the existing severity as-is)
    """
    base = (base_severity or "").upper()

    if owner_facing_lost:
        floor = "HIGH"
        tier = "owner_facing_loss"
    elif affected_labels:
        floor = "MEDIUM"
        tier = "structural_cascade"
    else:
        return "no_cascade", base, False

    effective = _max_severity(base, floor)
    escalated = effective != base
    return tier, effective, escalated


# ---------------------------------------------------------------------------
# Resource normalisation
# ---------------------------------------------------------------------------

def _normalize_service_name(resource: str) -> str:
    """Extract core service label from a finding resource string.

    Returns an empty string for resources that should not be searched
    (e.g., port numbers), so callers can skip them with a simple truthiness check.
    """
    if not resource:
        return ""
    # Port findings: "port:8001" — no stable graph node label
    if resource.startswith("port:"):
        return ""
    name = resource.strip()
    # Strip .service suffix
    name = re.sub(r"\.service$", "", name)
    # Strip @instance suffix: "postgresql@16-main" → "postgresql"
    name = re.sub(r"@[^@]*$", "", name)
    return name.strip()


# ---------------------------------------------------------------------------
# Node lookup
# ---------------------------------------------------------------------------

def _find_vps_node(label: str, graph_store: GraphStore) -> str | None:
    """Search for an active VPS-target node matching the label."""
    if not label:
        return None
    matches = graph_store.get_nodes_by_label(label, case_sensitive=False)
    vps_matches = [n for n in matches if n["target_id"] == "vps"]
    if vps_matches:
        return vps_matches[0]["node_id"]
    return None


def _find_repo_node(finding_target_id: str, graph_store: GraphStore) -> str | None:
    """Search for the repo node that corresponds to a project-level finding.

    Repo findings use a short target_id ("quartermaster") while graph
    nodes use the full scan-target path ("/opt/quartermaster"). We try
    three strategies in order:
      1. builder_node_id exact: "repo:" + finding_target_id
      2. target_id path suffix: node.target_id ends with "/" + finding_target_id
      3. label match: graph_store.get_nodes_by_label(finding_target_id)
    """
    all_nodes = graph_store.get_active_nodes()

    # Strategy 1: exact builder_node_id
    builder_id = "repo:" + finding_target_id
    for node in all_nodes:
        if node["builder_node_id"] == builder_id:
            return node["node_id"]

    # Strategy 2: target_id path suffix
    suffix = "/" + finding_target_id
    for node in all_nodes:
        if node["target_id"].endswith(suffix) and node["builder_node_id"].startswith("repo:"):
            return node["node_id"]

    # Strategy 3: label match (least specific — only for repo-type nodes)
    matches = graph_store.get_nodes_by_label(finding_target_id, case_sensitive=False)
    repo_matches = [n for n in matches if n["builder_node_id"].startswith("repo:")]
    if repo_matches:
        return repo_matches[0]["node_id"]

    return None


# ---------------------------------------------------------------------------
# Public mapping API
# ---------------------------------------------------------------------------

def map_finding_to_node_id(
    finding: dict[str, Any],
    graph_store: GraphStore,
) -> str | None:
    """Return the graph node_id that corresponds to this finding, or None.

    Returns None — not an error — when no mapping exists. The finding
    is then left unchanged (event framing only).
    """
    try:
        target_id = finding.get("target_id", "")

        if target_id in _NON_GRAPH_TARGETS:
            return None

        if target_id == "vps":
            resource = finding.get("resource", "")
            label = _normalize_service_name(resource)
            return _find_vps_node(label, graph_store)

        # Repo / project findings
        return _find_repo_node(target_id, graph_store)

    except Exception as exc:
        logger.debug("map_finding_to_node_id error: %s", exc)
        return None


def get_consequence_framing(
    finding: dict[str, Any],
    graph_store: GraphStore | None,
) -> dict[str, Any] | None:
    """Run the consequence walk for a finding and return a framing dict, or None.

    The framing dict is pre-structured for both the incident report renderer
    and the Telegram notification formatter so neither has to call the walk
    directly. Both callers treat None as "no augmentation available."

    Returns None when:
      - graph_store is None (called without graph context)
      - the finding maps to no graph node
      - the walk raises (caught internally)
    """
    if graph_store is None:
        return None

    try:
        node_id = map_finding_to_node_id(finding, graph_store)
        if node_id is None:
            return None

        from cognition.consequence_walk import walk  # late import to avoid cycles
        result = walk([node_id], graph_store)

        # Nothing goes dark and it's already known? Skip augmentation to avoid noise.
        has_impact = bool(result.owner_facing_lost or result.affected)
        if not has_impact and not result.root_causes:
            return None

        # Flatten owner_facing_lost into a simple label → consequence map
        owner_impact_lines: list[str] = []
        for item in result.owner_facing_lost:
            label = item["label"]
            c = item["consequence"]
            conf = item["confidence"]
            if c != "unknown":
                owner_impact_lines.append(
                    f"{label}: {c} (confidence: {conf})"
                )
            else:
                owner_impact_lines.append(
                    f"{label}: consequence unknown (confidence: {conf})"
                )

        mapped_node = _get_node_label(node_id, graph_store)
        affected_labels = [a.label for a in result.affected]
        base_sev = (finding.get("severity") or "").upper()
        tier, consequence_severity, escalated = _compute_consequence_rank(
            result.owner_facing_lost, affected_labels, base_sev
        )
        return {
            "mapped_node_id": node_id,
            "mapped_node_label": mapped_node,
            "root_cause_labels": [rc.label for rc in result.root_causes],
            "affected_labels": affected_labels,
            "owner_facing_lost": result.owner_facing_lost,
            "owner_impact_lines": owner_impact_lines,
            "unknown_consequences": result.unknown_consequences,
            "overall_confidence": result.overall_confidence,
            "evidence_trail": result.evidence_trail,
            "summary": result.summary,
            # Consequence-adjusted severity ranking
            "tier": tier,
            "base_severity": base_sev,
            "consequence_severity": consequence_severity,
            "escalated": escalated,
        }

    except Exception as exc:
        logger.debug("get_consequence_framing error: %s", type(exc).__name__)
        return None


def _get_node_label(node_id: str, graph_store: GraphStore) -> str:
    """Return the label for a node_id, or the id itself as fallback."""
    try:
        nodes = graph_store.get_active_nodes()
        for n in nodes:
            if n["node_id"] == node_id:
                return n["label"]
    except Exception:
        pass
    return node_id
