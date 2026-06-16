#!/usr/bin/env python3
"""Load operator key→agent labels into the graph as human_declared bindings.

Mirrors scripts/load_operational_graph.py. For each label in config/cost_advisor.yml
it ensures a key node (builder_node_id "key:<provider>:<key_id>", target "external")
and an ATTRIBUTED_TO edge key→agent, both collector_type="human_declared".

human_declared is STICKY: a later scan/reconcile can never overwrite these — the
graph_store invariant guarantees it. Labelling a key is a one-time tag, NOT a new
key, and no secret value is ever read or written.

Usage:
    python scripts/load_cost_keys.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from economics.key_registry import key_node_id, load_key_labels  # noqa: E402
from memory.graph_store import GraphStore, compute_node_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("load_cost_keys")

CONFIG_PATH = PROJECT_ROOT / "config" / "cost_advisor.yml"
_DB_PATH = str(PROJECT_ROOT / "data" / "operational_memory.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load key→agent labels into the graph")
    parser.add_argument("--dry-run", action="store_true", help="show what would change")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    args = parser.parse_args()

    labels, errors = load_key_labels(args.config)
    for err in errors:
        log.warning("SKIP %s", err)
    if not labels:
        log.info("No key→agent labels declared in %s — nothing to load.", args.config)
        return

    now = datetime.now(UTC)
    store = GraphStore(_DB_PATH)
    store.connect()
    try:
        n_nodes = n_edges = 0
        for lbl in labels:
            kid = key_node_id(lbl.provider, lbl.key_id)
            agent_target = lbl.agent_target or "vps"
            label_text = f"{lbl.provider}:{lbl.key_hint or lbl.key_id}"
            shared = " (shared)" if lbl.shared else ""
            log.info("key %s%s → %s", label_text, shared, lbl.agent)
            if args.dry_run:
                continue

            store.upsert_node(
                target_id="external",
                builder_node_id=kid,
                node_type="api_key",
                label=label_text,
                metadata={"source": "human_declared", "provider": lbl.provider,
                          "shared": lbl.shared, "agent": lbl.agent},
                collector_type="human_declared",
                now=now,
            )
            n_nodes += 1
            # Ensure the agent node exists (stub) so the edge has both ends.
            store.upsert_node(
                target_id=agent_target,
                builder_node_id=lbl.agent,
                node_type="declared",
                label=lbl.agent.split(":")[-1],
                metadata={"source": "human_declared"},
                collector_type="human_declared",
                now=now,
            )
            store.upsert_edge(
                source_node_id=compute_node_id("external", kid),
                target_node_id=compute_node_id(agent_target, lbl.agent),
                relationship="ATTRIBUTED_TO",
                collector_type="human_declared",
                confidence=1.0,
                evidence=[{"source": "human_declared", "detail": lbl.evidence}],
                now=now,
            )
            n_edges += 1
        if args.dry_run:
            log.info("[DRY-RUN] would bind %d key label(s).", len(labels))
        else:
            log.info("Bound %d key node(s), %d ATTRIBUTED_TO edge(s) (human_declared).",
                     n_nodes, n_edges)
    finally:
        store.disconnect()


if __name__ == "__main__":
    main()
