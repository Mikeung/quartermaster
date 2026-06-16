#!/usr/bin/env python3
"""Load operator-declared operational graph declarations into graph_store.

Reads config/operational_graph.yml and upserts:
  - Node stubs    — ensures every declared node exists in graph_store, creating
                    a human_declared stub when the target has not been scanned yet
  - Annotations   — liveness signal, consequence, owner_facing (per node)
  - Edges         — operational dependencies that inference cannot see,
                    loaded with collector_type="human_declared"

This is the only write path for human_declared data. The scanner (topology/builder
and scheduled_scan) is never modified — it continues producing inferred edges
independently.

Idempotent: safe to re-run after editing the YAML. Unchanged annotations and edges
produce no new event-log rows. Changed values update in-place and fire one event.

Usage:
  python scripts/load_operational_graph.py            # load into live DB
  python scripts/load_operational_graph.py --dry-run  # preview, no writes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import yaml  # noqa: E402

from memory.graph_store import GraphStore, compute_node_id  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("load_operational_graph")

_YAML_PATH = PROJECT_ROOT / "config" / "operational_graph.yml"
_DB_PATH = str(PROJECT_ROOT / "data" / "operational_memory.db")

# Annotation types the loader populates.
_ANN_LIVENESS = "liveness"
_ANN_CONSEQUENCE = "consequence"
_ANN_OWNER_FACING = "owner_facing"

# Relationship for quartermaster scan-coverage edges.
_REL_SCANS = "SCANS"

# ---------------------------------------------------------------------------
# Direction guard
# ---------------------------------------------------------------------------
# The consequence walk traverses edges in the dependent→dependency direction:
#   source = the node that NEEDS the other  (dependent)
#   target = the node that PROVIDES to the other (dependency)
#
# These relationship types encode data-flow direction (provider→consumer),
# which is the OPPOSITE convention. Using them stores edges backwards, so
# the walk finds dep_of[target] instead of dep_of[source] — silently missing
# the cascade. The loader hard-rejects them with a fix suggestion.
_WRONG_DIRECTION_RELS: dict[str, str] = {
    "FEEDS_SPEND_TO": "READS_FROM",
    # Add further provider→consumer relationships here as discovered.
    # Format: wrong_relationship → correct_inverse_relationship
}


def _load_yaml() -> dict[str, Any]:
    text = _YAML_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _coerce_str(value: Any) -> str:
    """Normalise a YAML value to a plain string, stripping whitespace.

    YAML parses bare  true/false  as Python bools; convert to lowercase
    strings so the consequence brain sees consistent values regardless of
    whether the operator wrote  true  or  "true"  in the YAML.
    """
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    s = str(value).strip()
    # YAML block scalars introduce newlines; collapse them for storage
    return " ".join(s.split()) if "\n" in s else s


def _field_value_and_evidence(raw: Any, default: str = "unknown") -> tuple[str, str]:
    """Resolve a node field (consequence / owner_facing) to (value, evidence).

    Two forms are accepted, so the confirmation flow can preserve provenance
    without breaking hand-authored entries:
      - legacy scalar       → value as-is, evidence "operator-declared"
      - confirmed block dict → {value, status, source, provenance, confirmed_at,
        evidence}; the value is read and the provenance folded into the annotation
        evidence so graph_store always shows where a confirmed value came from.
    """
    if isinstance(raw, dict):
        value = _coerce_str(raw.get("value", default))
        bits = []
        for k in ("status", "source", "provenance", "confirmed_at"):
            v = _coerce_str(raw.get(k, "")) if raw.get(k) is not None else ""
            if v and v != "unknown":
                bits.append(f"{k}={v}")
        ev = _coerce_str(raw.get("evidence", ""))
        if ev and ev != "unknown":
            bits.append(ev)
        return value, ("; ".join(bits) if bits else "operator-declared")
    return _coerce_str(raw if raw is not None else default), "operator-declared"


def _ensure_node(
    store: GraphStore,
    *,
    target_id: str,
    builder_node_id: str,
    label: str,
    node_type: str = "declared",
    now: datetime,
    dry_run: bool,
) -> str:
    """Return node_id, creating a human_declared stub if the node doesn't exist yet."""
    nid = compute_node_id(target_id, builder_node_id)
    if dry_run:
        return nid
    store.upsert_node(
        target_id=target_id,
        builder_node_id=builder_node_id,
        node_type=node_type,
        label=label,
        metadata={"source": "human_declared"},
        collector_type="human_declared",
        now=now,
    )
    return nid


def _check_edge_direction(edge_decl: dict[str, Any]) -> None:
    """Raise ValueError if the relationship uses the wrong (data-flow) direction.

    The consequence walk expects dependent→dependency. Relationships that
    encode the reverse (provider→consumer) produce edges the walk traverses
    backwards — silently missing the cascade without any error at query time.
    Catching this at load time makes the mistake impossible to overlook.
    """
    rel = _coerce_str(edge_decl.get("relationship", ""))
    if rel not in _WRONG_DIRECTION_RELS:
        return
    inverse = _WRONG_DIRECTION_RELS[rel]
    from_id = edge_decl.get("from", {}).get("id", "?")
    to_id = edge_decl.get("to", {}).get("id", "?")
    raise ValueError(
        f"\nEdge '{from_id} -[{rel}]-> {to_id}' uses a data-flow direction "
        f"(provider→consumer), which the consequence walk traverses BACKWARDS.\n"
        f"Fix: swap source/target and change the relationship:\n"
        f"  from: {{id: {to_id}, ...}}\n"
        f"  to:   {{id: {from_id}, ...}}\n"
        f"  relationship: {inverse}\n"
        f"The walk requires: source = dependent, target = dependency."
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def _process_node(
    store: GraphStore,
    node_decl: dict[str, Any],
    now: datetime,
    dry_run: bool,
) -> dict[str, int]:
    """Process one node declaration. Returns annotation counts."""
    builder_id = node_decl.get("id", "")
    target_id = node_decl.get("target", "vps")
    label = builder_id.split(":")[-1] if ":" in builder_id else builder_id

    if not builder_id:
        log.warning("Node declaration missing 'id' — skipping")
        return {"set": 0, "unchanged": 0}

    node_id = _ensure_node(
        store,
        target_id=target_id,
        builder_node_id=builder_id,
        label=label,
        now=now,
        dry_run=dry_run,
    )

    changed = 0
    unchanged = 0

    # Liveness annotation (stored as JSON string)
    liveness_raw = node_decl.get("liveness")
    if liveness_raw is not None:
        liveness_data = {
            "signal": _coerce_str(liveness_raw.get("signal", "unknown")),
            "detail": _coerce_str(liveness_raw.get("detail", "unknown")),
            "max_age_hours": _coerce_str(liveness_raw.get("max_age_hours", "unknown")),
        }
        evidence = _coerce_str(liveness_raw.get("evidence", ""))
        value = json.dumps(liveness_data)
        if dry_run:
            log.info("  [DRY-RUN] annotation liveness: %s @ %s", builder_id, target_id)
            changed += 1
        else:
            did_change = store.set_node_annotation(
                node_id=node_id,
                annotation_type=_ANN_LIVENESS,
                value=value,
                evidence=evidence,
                now=now,
            )
            if did_change:
                changed += 1
            else:
                unchanged += 1

    # Consequence annotation (scalar or confirmed block with provenance)
    consequence, consequence_ev = _field_value_and_evidence(node_decl.get("consequence"))
    if dry_run:
        log.info("  [DRY-RUN] annotation consequence: %s @ %s", builder_id, target_id)
        changed += 1
    else:
        did_change = store.set_node_annotation(
            node_id=node_id,
            annotation_type=_ANN_CONSEQUENCE,
            value=consequence,
            evidence=consequence_ev,
            now=now,
        )
        if did_change:
            changed += 1
        else:
            unchanged += 1

    # Owner-facing annotation (scalar or confirmed block with provenance)
    owner_facing, owner_facing_ev = _field_value_and_evidence(node_decl.get("owner_facing"))
    if dry_run:
        log.info(
            "  [DRY-RUN] annotation owner_facing=%s: %s @ %s",
            owner_facing, builder_id, target_id,
        )
        changed += 1
    else:
        did_change = store.set_node_annotation(
            node_id=node_id,
            annotation_type=_ANN_OWNER_FACING,
            value=owner_facing,
            evidence=owner_facing_ev,
            now=now,
        )
        if did_change:
            changed += 1
        else:
            unchanged += 1

    # Decommissioned status (optional) — operator-declared lifecycle state.
    # When a node is decommissioned, persist a 'status' annotation so the
    # meaning layer can explain that the node's down/absent state is INTENTIONAL
    # and EXPECTED, not a fault. Purely additive: absence of the field leaves
    # status untouched, and a 'false' value is a no-op (nodes are live by default).
    decommissioned_raw = node_decl.get("decommissioned")
    if decommissioned_raw is not None:
        dvalue, devidence = _field_value_and_evidence(decommissioned_raw, default="false")
        if dvalue.lower() == "true":
            if dry_run:
                log.info(
                    "  [DRY-RUN] annotation status=decommissioned: %s @ %s",
                    builder_id, target_id,
                )
                changed += 1
            else:
                did_change = store.set_node_annotation(
                    node_id=node_id,
                    annotation_type="status",
                    value="decommissioned",
                    evidence=devidence,
                    now=now,
                )
                if did_change:
                    changed += 1
                else:
                    unchanged += 1

    log.info(
        "node %s @ %s: %d annotations %s",
        builder_id, target_id, changed + unchanged,
        "(dry-run)" if dry_run else f"(changed={changed} unchanged={unchanged})",
    )
    return {"set": changed, "unchanged": unchanged}


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

def _process_edge(
    store: GraphStore,
    edge_decl: dict[str, Any],
    now: datetime,
    dry_run: bool,
) -> dict[str, int]:
    """Process one edge declaration. Returns {new, updated, unchanged}."""
    from_decl = edge_decl.get("from", {})
    to_decl = edge_decl.get("to", {})

    from_builder_id = from_decl.get("id", "")
    from_target = from_decl.get("target", "vps")
    to_builder_id = to_decl.get("id", "")
    to_target = to_decl.get("target", "vps")
    relationship = _coerce_str(edge_decl.get("relationship", "DEPENDS_ON"))
    description = _coerce_str(edge_decl.get("description", ""))
    evidence_str = _coerce_str(edge_decl.get("evidence", ""))
    confidence = float(edge_decl.get("confidence", 1.0))

    if not from_builder_id or not to_builder_id:
        log.warning("Edge missing from.id or to.id — skipping: %s", edge_decl)
        return {"new": 0, "updated": 0, "unchanged": 0}

    # Fail fast on wrong-direction relationships so the bug is caught at load
    # time rather than silently producing an un-traversable edge.
    _check_edge_direction(edge_decl)

    from_label = from_builder_id.split(":")[-1] if ":" in from_builder_id else from_builder_id
    to_label = to_builder_id.split(":")[-1] if ":" in to_builder_id else to_builder_id

    evidence_list = [{"source": "human_declared", "detail": evidence_str}]
    if description:
        evidence_list.append({"source": "human_declared_description", "detail": description})

    if dry_run:
        log.info(
            "  [DRY-RUN] edge %s@%s -[%s]-> %s@%s conf=%.2f",
            from_builder_id, from_target, relationship, to_builder_id, to_target, confidence,
        )
        return {"new": 1, "updated": 0, "unchanged": 0}

    src_id = _ensure_node(
        store, target_id=from_target, builder_node_id=from_builder_id,
        label=from_label, now=now, dry_run=False,
    )
    tgt_id = _ensure_node(
        store, target_id=to_target, builder_node_id=to_builder_id,
        label=to_label, now=now, dry_run=False,
    )

    store.upsert_edge(
        source_node_id=src_id,
        target_node_id=tgt_id,
        relationship=relationship,
        collector_type="human_declared",
        confidence=confidence,
        evidence=evidence_list,
        now=now,
    )

    log.info(
        "edge %s -[%s]-> %s conf=%.2f",
        from_builder_id, relationship, to_builder_id, confidence,
    )
    return {"new": 1, "updated": 0, "unchanged": 0}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load(dry_run: bool = False) -> dict[str, Any]:
    """Load the operational graph YAML into graph_store. Returns a summary dict."""
    if not _YAML_PATH.exists():
        raise FileNotFoundError(f"Operational graph not found: {_YAML_PATH}")

    config = _load_yaml()
    version = config.get("version", "unknown")
    log.info(
        "Loading operational_graph.yml v=%s%s",
        version,
        " [DRY-RUN]" if dry_run else "",
    )

    now = datetime.now(UTC)
    store = GraphStore(_DB_PATH)

    if not dry_run:
        store.connect()

    node_decls = config.get("nodes", []) or []
    edge_decls = config.get("edges", []) or []

    total_ann_set = 0
    total_ann_unchanged = 0
    total_edges = 0
    nodes_with_unknown_consequence = 0
    nodes_with_known_consequence = 0

    try:
        for node_decl in node_decls:
            result = _process_node(store, node_decl, now, dry_run)
            total_ann_set += result["set"]
            total_ann_unchanged += result["unchanged"]

            c, _ = _field_value_and_evidence(node_decl.get("consequence"))
            if c == "unknown":
                nodes_with_unknown_consequence += 1
            else:
                nodes_with_known_consequence += 1

        for edge_decl in edge_decls:
            result = _process_edge(store, edge_decl, now, dry_run)
            total_edges += result.get("new", 0) + result.get("updated", 0)

    finally:
        if not dry_run:
            store.disconnect()

    summary = {
        "dry_run": dry_run,
        "yaml_version": version,
        "nodes_declared": len(node_decls),
        "edges_declared": len(edge_decls),
        "annotations_set": total_ann_set,
        "annotations_unchanged": total_ann_unchanged,
        "edges_loaded": total_edges,
        "nodes_consequence_known": nodes_with_known_consequence,
        "nodes_consequence_unknown": nodes_with_unknown_consequence,
    }

    log.info(
        "Summary: nodes=%d edges=%d annotations_set=%d annotations_unchanged=%d "
        "consequence_known=%d consequence_unknown=%d%s",
        len(node_decls),
        len(edge_decls),
        total_ann_set,
        total_ann_unchanged,
        nodes_with_known_consequence,
        nodes_with_unknown_consequence,
        " [DRY-RUN]" if dry_run else "",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load config/operational_graph.yml into graph_store"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be loaded without writing to the database",
    )
    args = parser.parse_args()
    load(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
