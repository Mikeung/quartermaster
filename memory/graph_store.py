"""Persistent, evolving dependency graph store.

Every topology scan produces a set of nodes and edges. This store persists them
with the same lifecycle discipline as findings: upsert on appearance,
resolve on disappearance, append-only event log throughout. The graph never
shrinks — history accumulates so the WHAT-IF consequence brain can observe how
the dependency structure has evolved, not just its current snapshot.

Identity model (mirrors finding_id):
  node_id = SHA-256(target_id + NUL + builder_node_id)
  edge_id = SHA-256(source_node_id + NUL + target_node_id + NUL + relationship
                    + NUL + collector_type)

Confidence is excluded from edge identity for the same reason severity is
excluded from finding identity: it is mutable operational state, not structure.

Collector types (current):
  "repo_scanner"    — inferred from package manifests or filesystem evidence
  "service_scanner" — inferred from active listening-port observations
  "llm_detector"    — inferred from import-pattern detection in source
  "human_declared"  — operator-declared operational meaning (loaded from
                       config/operational_graph.yml by scripts/load_operational_graph.py)

Annotation layer (graph_node_annotations):
  Stores operator-declared meaning per node: liveness signal, consequence if
  the node goes down, and whether it produces output the operator directly
  cares about. Keyed by (node_id, annotation_type); upsert semantics so the
  loader is idempotent. History is preserved via the graph_node_events log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id          TEXT PRIMARY KEY,
    target_id        TEXT NOT NULL,
    builder_node_id  TEXT NOT NULL,
    node_type        TEXT NOT NULL,
    label            TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}',
    collector_type   TEXT NOT NULL DEFAULT '',
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    resolved_at      TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_target
    ON graph_nodes(target_id, last_seen DESC);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_active
    ON graph_nodes(target_id, resolved_at, last_seen DESC);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id          TEXT PRIMARY KEY,
    source_node_id   TEXT NOT NULL,
    target_node_id   TEXT NOT NULL,
    relationship     TEXT NOT NULL,
    collector_type   TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 1.0,
    evidence         TEXT NOT NULL DEFAULT '[]',
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    resolved_at      TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_source
    ON graph_edges(source_node_id, last_seen DESC);

CREATE INDEX IF NOT EXISTS idx_graph_edges_target_node
    ON graph_edges(target_node_id, last_seen DESC);

CREATE INDEX IF NOT EXISTS idx_graph_edges_active
    ON graph_edges(source_node_id, resolved_at);

CREATE TABLE IF NOT EXISTS graph_node_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_ts   TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_graph_node_events_nid
    ON graph_node_events(node_id, event_ts DESC);

CREATE TABLE IF NOT EXISTS graph_edge_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id    TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_ts   TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_graph_edge_events_eid
    ON graph_edge_events(edge_id, event_ts DESC);

CREATE TABLE IF NOT EXISTS graph_node_annotations (
    node_id         TEXT NOT NULL,
    annotation_type TEXT NOT NULL,
    value           TEXT NOT NULL DEFAULT '',
    evidence        TEXT NOT NULL DEFAULT '',
    collector_type  TEXT NOT NULL DEFAULT 'human_declared',
    set_at          TEXT NOT NULL,
    PRIMARY KEY (node_id, annotation_type)
);

CREATE INDEX IF NOT EXISTS idx_graph_node_annotations_nid
    ON graph_node_annotations(node_id);
"""


# ---------------------------------------------------------------------------
# Identity helpers (pure — no I/O, safe to call anywhere)
# ---------------------------------------------------------------------------

def compute_node_id(target_id: str, builder_node_id: str) -> str:
    """Deterministic SHA-256 node identity.

    NUL byte separator prevents collisions between, e.g.,
    target_id="a", builder_node_id="bc" and target_id="ab", builder_node_id="c".
    """
    raw = f"{target_id}\x00{builder_node_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_edge_id(
    source_node_id: str,
    target_node_id: str,
    relationship: str,
    collector_type: str,
) -> str:
    """Deterministic SHA-256 edge identity.

    Confidence is excluded: an edge whose inferred confidence changes is still
    the same structural relationship. The update path records the new value in
    the row; the edge_id stays stable.
    """
    raw = (
        f"{source_node_id}\x00{target_node_id}\x00"
        f"{relationship}\x00{collector_type}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------

class GraphStore:
    """Persistent, evolving dependency graph — the substrate for the WHAT-IF brain.

    Shares the same SQLite file as OperationalStore and FindingStore.
    Migration is additive (CREATE TABLE IF NOT EXISTS) so connecting to an
    existing database is always safe.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Additive migration: add collector_type to graph_nodes for existing DBs.
        # New DBs get it from CREATE TABLE; existing DBs need ALTER TABLE.
        try:
            self._conn.execute(
                "ALTER TABLE graph_nodes ADD COLUMN collector_type TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
            logger.debug("graph_nodes: collector_type column added via migration")
        except Exception:
            pass  # Column already exists
        logger.info("GraphStore connected: %s", self._db_path)

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("GraphStore disconnected")

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        *,
        target_id: str,
        builder_node_id: str,
        node_type: str,
        label: str,
        metadata: dict[str, Any] | None = None,
        collector_type: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Insert or update a node. Clears resolved_at if the node reappears.

        collector_type is sticky for "human_declared": once an operator has
        explicitly declared a node, a scanner pass can never silently overwrite
        that provenance. The scanner and loader share the same node identity; the
        invariant preserves operator truth regardless of scan order.

        Returns a dict containing node_id so the caller can collect active IDs
        for the reconciliation pass without a second query.
        """
        assert self._conn is not None
        ts = (now or datetime.now(UTC)).isoformat()
        node_id = compute_node_id(target_id, builder_node_id)
        meta_json = json.dumps(metadata or {})

        existing = self._conn.execute(
            "SELECT resolved_at, collector_type FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """INSERT INTO graph_nodes
                   (node_id, target_id, builder_node_id, node_type, label, metadata,
                    collector_type, first_seen, last_seen, resolved_at, occurrence_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)""",
                (node_id, target_id, builder_node_id, node_type, label,
                 meta_json, collector_type, ts, ts),
            )
            self._node_event(node_id, "appeared", ts,
                             f"type={node_type} label={label} collector={collector_type}")
            logger.debug("graph_node appeared: %s [%s] target=%s",
                         label, node_type, target_id)
        else:
            was_resolved = existing["resolved_at"] is not None
            # Sticky human_declared: a scanner can enrich an operator-declared node
            # but never silently rewrite its provenance.
            effective_collector = (
                "human_declared"
                if existing["collector_type"] == "human_declared"
                   and collector_type != "human_declared"
                else collector_type
            )
            self._conn.execute(
                """UPDATE graph_nodes
                   SET last_seen = ?,
                       label = ?,
                       metadata = ?,
                       collector_type = ?,
                       resolved_at = NULL,
                       occurrence_count = occurrence_count + 1
                   WHERE node_id = ?""",
                (ts, label, meta_json, effective_collector, node_id),
            )
            if was_resolved:
                self._node_event(node_id, "reactivated", ts,
                                 "was resolved; reappeared in scan")
                logger.debug("graph_node reactivated: %s target=%s", label, target_id)

        self._conn.commit()
        return {"node_id": node_id, "target_id": target_id, "label": label}

    def upsert_edge(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        relationship: str,
        collector_type: str,
        confidence: float,
        evidence: list[dict[str, str]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Insert or update an edge. Clears resolved_at if the edge reappears.

        Returns a dict containing edge_id for reconciliation collection.
        """
        assert self._conn is not None
        ts = (now or datetime.now(UTC)).isoformat()
        edge_id = compute_edge_id(
            source_node_id, target_node_id, relationship, collector_type
        )
        ev_json = json.dumps(evidence)

        existing = self._conn.execute(
            "SELECT resolved_at FROM graph_edges WHERE edge_id = ?", (edge_id,)
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """INSERT INTO graph_edges
                   (edge_id, source_node_id, target_node_id, relationship,
                    collector_type, confidence, evidence,
                    first_seen, last_seen, resolved_at, occurrence_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)""",
                (edge_id, source_node_id, target_node_id, relationship,
                 collector_type, confidence, ev_json, ts, ts),
            )
            self._edge_event(edge_id, "appeared", ts,
                             f"rel={relationship} conf={confidence:.2f}")
            logger.debug("graph_edge appeared: [%s] conf=%.2f", relationship, confidence)
        else:
            was_resolved = existing["resolved_at"] is not None
            self._conn.execute(
                """UPDATE graph_edges
                   SET last_seen = ?,
                       confidence = ?,
                       evidence = ?,
                       resolved_at = NULL,
                       occurrence_count = occurrence_count + 1
                   WHERE edge_id = ?""",
                (ts, confidence, ev_json, edge_id),
            )
            if was_resolved:
                self._edge_event(edge_id, "reactivated", ts,
                                 "was resolved; reappeared in scan")
                logger.debug("graph_edge reactivated: [%s]", relationship)

        self._conn.commit()
        return {"edge_id": edge_id}

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def mark_nodes_resolved(
        self,
        active_node_ids: set[str],
        target_id: str,
        now: datetime | None = None,
    ) -> int:
        """Mark nodes for this target that are absent from the current scan.

        Nodes are never deleted. resolved_at records when they disappeared.
        Returns the count of newly resolved nodes.
        """
        assert self._conn is not None
        ts = (now or datetime.now(UTC)).isoformat()

        # Exclude human_declared nodes: they are maintained by the operator via
        # load_operational_graph.py and must persist until the operator removes
        # them, regardless of whether the scanner produces them.
        currently_active = self._conn.execute(
            "SELECT node_id FROM graph_nodes "
            "WHERE target_id = ? AND resolved_at IS NULL "
            "AND collector_type != 'human_declared'",
            (target_id,),
        ).fetchall()

        to_resolve = [
            row["node_id"] for row in currently_active
            if row["node_id"] not in active_node_ids
        ]

        for node_id in to_resolve:
            self._conn.execute(
                "UPDATE graph_nodes SET resolved_at = ? WHERE node_id = ?",
                (ts, node_id),
            )
            self._node_event(node_id, "resolved", ts, "absent from scan output")

        if to_resolve:
            self._conn.commit()
            logger.debug(
                "graph_nodes resolved: %d for target=%s", len(to_resolve), target_id
            )

        return len(to_resolve)

    def mark_edges_resolved(
        self,
        active_edge_ids: set[str],
        target_id: str,
        now: datetime | None = None,
    ) -> int:
        """Mark edges whose source node belongs to target_id and are now absent.

        Scoping through source_node_id → graph_nodes.target_id ensures we only
        resolve edges from the scanned target, not edges from other targets that
        happen to point at the same shared node type.
        """
        assert self._conn is not None
        ts = (now or datetime.now(UTC)).isoformat()

        # Exclude human_declared edges: they are maintained by the operator via
        # load_operational_graph.py, not by the scanner. A scan that produces no
        # inferred equivalent of a declared dependency must never silently delete it.
        currently_active = self._conn.execute(
            """SELECT ge.edge_id
               FROM graph_edges ge
               JOIN graph_nodes gn ON gn.node_id = ge.source_node_id
               WHERE gn.target_id = ? AND ge.resolved_at IS NULL
                 AND ge.collector_type != 'human_declared'""",
            (target_id,),
        ).fetchall()

        to_resolve = [
            row["edge_id"] for row in currently_active
            if row["edge_id"] not in active_edge_ids
        ]

        for edge_id in to_resolve:
            self._conn.execute(
                "UPDATE graph_edges SET resolved_at = ? WHERE edge_id = ?",
                (ts, edge_id),
            )
            self._edge_event(edge_id, "resolved", ts, "absent from scan output")

        if to_resolve:
            self._conn.commit()
            logger.debug(
                "graph_edges resolved: %d for target=%s", len(to_resolve), target_id
            )

        return len(to_resolve)

    # ------------------------------------------------------------------
    # Query interface (read API for the consequence brain)
    # ------------------------------------------------------------------

    def get_active_nodes(self, target_id: str | None = None) -> list[dict[str, Any]]:
        """Return all currently active nodes, optionally scoped to a target."""
        assert self._conn is not None
        if target_id:
            rows = self._conn.execute(
                "SELECT * FROM graph_nodes "
                "WHERE target_id = ? AND resolved_at IS NULL "
                "ORDER BY last_seen DESC",
                (target_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM graph_nodes WHERE resolved_at IS NULL "
                "ORDER BY last_seen DESC"
            ).fetchall()
        return [_deserialize_node(dict(r)) for r in rows]

    def get_active_edges(self, target_id: str | None = None) -> list[dict[str, Any]]:
        """Return all currently active edges, optionally scoped to a target.

        When target_id is given, returns edges whose source node belongs to that
        target — the same scope contract as mark_edges_resolved.
        """
        assert self._conn is not None
        if target_id:
            rows = self._conn.execute(
                """SELECT ge.*
                   FROM graph_edges ge
                   JOIN graph_nodes gn ON gn.node_id = ge.source_node_id
                   WHERE gn.target_id = ? AND ge.resolved_at IS NULL
                   ORDER BY ge.last_seen DESC""",
                (target_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM graph_edges WHERE resolved_at IS NULL "
                "ORDER BY last_seen DESC"
            ).fetchall()
        return [_deserialize_edge(dict(r)) for r in rows]

    def get_graph_for_target(self, target_id: str) -> dict[str, Any]:
        """Return the complete active graph for a target.

        This is the primary read API the consequence brain will call. The
        returned structure matches TopologyGraph.to_dict() in shape so the brain
        can work with either the live object (during a scan) or the persisted
        form (between scans).
        """
        nodes = self.get_active_nodes(target_id)
        edges = self.get_active_edges(target_id)
        return {
            "target_id": target_id,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    def get_all_graphs(self) -> dict[str, Any]:
        """Return the active graph across all targets for VPS-wide queries."""
        nodes = self.get_active_nodes()
        edges = self.get_active_edges()
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
        }

    def get_node_history(self, node_id: str) -> list[dict[str, Any]]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM graph_node_events WHERE node_id = ? ORDER BY event_ts ASC",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_edge_history(self, edge_id: str) -> list[dict[str, Any]]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM graph_edge_events WHERE edge_id = ? ORDER BY event_ts ASC",
            (edge_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_nodes(
        self, target_id: str | None = None, active_only: bool = True
    ) -> int:
        assert self._conn is not None
        conds: list[str] = []
        params: list[Any] = []
        if active_only:
            conds.append("resolved_at IS NULL")
        if target_id:
            conds.append("target_id = ?")
            params.append(target_id)
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM graph_nodes {where}", params
        ).fetchone()
        return int(row[0]) if row else 0

    def count_edges(
        self, target_id: str | None = None, active_only: bool = True
    ) -> int:
        assert self._conn is not None
        if target_id:
            join = "JOIN graph_nodes gn ON gn.node_id = ge.source_node_id"
            conds = ["gn.target_id = ?"]
            params: list[Any] = [target_id]
        else:
            join = ""
            conds = []
            params = []
        if active_only:
            conds.append("ge.resolved_at IS NULL")
        where = f"WHERE {' AND '.join(conds)}" if conds else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM graph_edges ge {join} {where}", params
        ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Node annotations (operator-declared meaning layer)
    # ------------------------------------------------------------------

    def set_node_annotation(
        self,
        *,
        node_id: str,
        annotation_type: str,
        value: str,
        evidence: str = "",
        collector_type: str = "human_declared",
        now: datetime | None = None,
    ) -> bool:
        """Upsert a node annotation. Returns True if value changed (or new).

        Annotation types: "liveness" | "consequence" | "owner_facing"
        Value is always stored as a string (JSON-encode dicts before calling).
        A history event is fired only when the value actually changes, so
        repeated loads with unchanged data leave no trace in the event log.
        """
        assert self._conn is not None
        ts = (now or datetime.now(UTC)).isoformat()

        existing = self._conn.execute(
            "SELECT value FROM graph_node_annotations "
            "WHERE node_id = ? AND annotation_type = ?",
            (node_id, annotation_type),
        ).fetchone()

        changed = existing is None or existing["value"] != value

        if existing is None:
            self._conn.execute(
                """INSERT INTO graph_node_annotations
                   (node_id, annotation_type, value, evidence, collector_type, set_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (node_id, annotation_type, value, evidence, collector_type, ts),
            )
        else:
            self._conn.execute(
                """UPDATE graph_node_annotations
                   SET value = ?, evidence = ?, collector_type = ?, set_at = ?
                   WHERE node_id = ? AND annotation_type = ?""",
                (value, evidence, collector_type, ts, node_id, annotation_type),
            )

        if changed:
            detail = f"{annotation_type}={'<new>' if existing is None else '<updated>'}"
            self._node_event(node_id, "annotation_set", ts, detail)

        self._conn.commit()
        return changed

    def get_node_annotations(self, node_id: str) -> dict[str, Any]:
        """Return all annotations for a node as {annotation_type: {value, evidence, ...}}.

        Returns an empty dict if the node has no annotations.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM graph_node_annotations WHERE node_id = ?",
            (node_id,),
        ).fetchall()
        return {
            row["annotation_type"]: {
                "value": row["value"],
                "evidence": row["evidence"],
                "collector_type": row["collector_type"],
                "set_at": row["set_at"],
            }
            for row in rows
        }

    def get_annotations_for_target(
        self, target_id: str
    ) -> dict[str, dict[str, Any]]:
        """Return all annotations keyed by node_id for nodes in this target.

        This is the primary read API for the consequence brain: one call
        retrieves the full meaning layer for a target's graph.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT a.*
               FROM graph_node_annotations a
               JOIN graph_nodes n ON n.node_id = a.node_id
               WHERE n.target_id = ?""",
            (target_id,),
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            nid = row["node_id"]
            if nid not in result:
                result[nid] = {}
            result[nid][row["annotation_type"]] = {
                "value": row["value"],
                "evidence": row["evidence"],
                "collector_type": row["collector_type"],
                "set_at": row["set_at"],
            }
        return result

    def get_all_annotations(self) -> dict[str, dict[str, Any]]:
        """Return all annotations across all nodes and targets.

        Keyed by node_id → {annotation_type → {value, evidence, ...}}.
        The consequence brain uses this to load the full meaning layer in one
        query instead of N per-node calls.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM graph_node_annotations"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            nid = row["node_id"]
            if nid not in result:
                result[nid] = {}
            result[nid][row["annotation_type"]] = {
                "value": row["value"],
                "evidence": row["evidence"],
                "collector_type": row["collector_type"],
                "set_at": row["set_at"],
            }
        return result

    def get_nodes_by_label(
        self, label: str, case_sensitive: bool = False
    ) -> list[dict[str, Any]]:
        """Return active nodes matching the given label.

        Used by the consequence brain's walk_by_label() convenience wrapper
        to resolve human-readable names to node_ids.
        """
        assert self._conn is not None
        if case_sensitive:
            rows = self._conn.execute(
                "SELECT * FROM graph_nodes WHERE label = ? AND resolved_at IS NULL",
                (label,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM graph_nodes "
                "WHERE lower(label) = lower(?) AND resolved_at IS NULL",
                (label,),
            ).fetchall()
        return [_deserialize_node(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Append-only event log helpers (private)
    # ------------------------------------------------------------------

    def _node_event(
        self, node_id: str, event_type: str, ts: str, detail: str
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO graph_node_events (node_id, event_type, event_ts, detail) "
            "VALUES (?, ?, ?, ?)",
            (node_id, event_type, ts, detail),
        )

    def _edge_event(
        self, edge_id: str, event_type: str, ts: str, detail: str
    ) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO graph_edge_events (edge_id, event_type, event_ts, detail) "
            "VALUES (?, ?, ?, ?)",
            (edge_id, event_type, ts, detail),
        )


# ---------------------------------------------------------------------------
# Deserialization helpers
# ---------------------------------------------------------------------------

def _deserialize_node(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("metadata"), str):
        try:
            row["metadata"] = json.loads(row["metadata"])
        except (json.JSONDecodeError, ValueError):
            row["metadata"] = {}
    return row


def _deserialize_edge(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("evidence"), str):
        try:
            row["evidence"] = json.loads(row["evidence"])
        except (json.JSONDecodeError, ValueError):
            row["evidence"] = []
    return row
