"""Tests for the 'operator truth is not scanner truth' invariant.

Validates three guarantees:
  1. Human-declared nodes survive a scan reconciliation that doesn't see them.
  2. Human-declared edges survive a scan reconciliation that doesn't see them.
  3. The loader rejects wrong-direction (data-flow) relationships at load time.

These tests prove the invariant holds at the boundary level — no test should
pass by trusting code comments; each directly exercises the reconciliation path.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime

import pytest

from memory.graph_store import GraphStore

_NOW1 = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
_NOW2 = datetime(2026, 6, 4, 18, 0, 0, tzinfo=UTC)  # "scan runs 6h later"

_TARGET_REPO = "/root/humint"
_TARGET_VPS  = "vps"


@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


# ---------------------------------------------------------------------------
# 1. Human-declared NODES survive scan reconciliation
# ---------------------------------------------------------------------------

class TestHumanDeclaredNodeSurvivesScan:
    def test_human_declared_node_not_resolved_when_scan_omits_it(self, store):
        """A node created with collector_type='human_declared' must NOT be
        resolved when mark_nodes_resolved runs without it in active_node_ids."""
        r = store.upsert_node(
            target_id=_TARGET_VPS,
            builder_node_id="service:postgresql",
            node_type="service",
            label="postgresql",
            collector_type="human_declared",
            now=_NOW1,
        )
        node_id = r["node_id"]

        # Simulate a scan that produces NO nodes for vps target
        resolved = store.mark_nodes_resolved(set(), _TARGET_VPS, now=_NOW2)

        assert resolved == 0, "human_declared node should not be resolved"
        nodes = store.get_active_nodes(_TARGET_VPS)
        assert any(n["node_id"] == node_id for n in nodes)

    def test_topology_builder_node_is_resolved_when_scan_omits_it(self, store):
        """A node created with collector_type='topology_builder' IS resolved
        when the scanner no longer produces it — normal reconciliation."""
        r = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="framework:fastapi",
            node_type="framework",
            label="fastapi",
            collector_type="topology_builder",
            now=_NOW1,
        )
        node_id = r["node_id"]

        # Scan produces no frameworks this time (e.g., dep was removed)
        resolved = store.mark_nodes_resolved(set(), _TARGET_REPO, now=_NOW2)

        assert resolved == 1
        active = store.get_active_nodes(_TARGET_REPO)
        assert not any(n["node_id"] == node_id for n in active)

    def test_human_declared_takes_precedence_over_scanner_when_loader_runs_first(self, store):
        """If the loader runs first (human_declared), then the scanner updates
        the same node (topology_builder), the collector_type stays human_declared.
        Operator truth is sticky."""
        # Loader runs first
        r = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="human_declared",
            now=_NOW1,
        )
        node_id = r["node_id"]

        # Scanner updates the same node (same identity)
        store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="topology_builder",
            now=_NOW2,
        )

        # collector_type must still be human_declared
        rows = store._conn.execute(
            "SELECT collector_type FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchall()
        assert rows[0]["collector_type"] == "human_declared"

        # And the node survives scan reconciliation
        resolved = store.mark_nodes_resolved(set(), _TARGET_REPO, now=_NOW2)
        assert resolved == 0

    def test_scanner_first_then_loader_upgrades_to_human_declared(self, store):
        """If the scanner creates a node first, the loader can upgrade it to
        human_declared — explicit operator declaration always takes precedence."""
        # Scanner first
        store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="topology_builder",
            now=_NOW1,
        )

        # Loader upgrades it
        r = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="human_declared",
            now=_NOW2,
        )
        node_id = r["node_id"]

        rows = store._conn.execute(
            "SELECT collector_type FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchall()
        assert rows[0]["collector_type"] == "human_declared"

        # Now survives scan reconciliation
        resolved = store.mark_nodes_resolved(set(), _TARGET_REPO, now=_NOW2)
        assert resolved == 0


# ---------------------------------------------------------------------------
# 2. Human-declared EDGES survive scan reconciliation
# ---------------------------------------------------------------------------

class TestHumanDeclaredEdgeSurvivesScan:
    def _seed_nodes(self, store):
        r1 = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="human_declared",
            now=_NOW1,
        )
        r2 = store.upsert_node(
            target_id=_TARGET_VPS,
            builder_node_id="service:postgresql",
            node_type="service",
            label="postgresql",
            collector_type="human_declared",
            now=_NOW1,
        )
        return r1["node_id"], r2["node_id"]

    def test_human_declared_edge_survives_scan_reconciliation(self, store):
        src, tgt = self._seed_nodes(store)
        store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="DEPENDS_ON",
            collector_type="human_declared",
            confidence=1.0,
            evidence=[{"source": "human_declared", "detail": "unit file"}],
            now=_NOW1,
        )

        # Scan produces no edges for this target
        resolved = store.mark_edges_resolved(set(), _TARGET_REPO, now=_NOW2)

        assert resolved == 0, "human_declared edge must not be resolved by scanner"
        edges = store.get_active_edges(_TARGET_REPO)
        assert len(edges) == 1
        assert edges[0]["relationship"] == "DEPENDS_ON"

    def test_inferred_edge_is_resolved_when_scan_omits_it(self, store):
        """A topology_builder edge that disappears from scan output is correctly
        resolved — this is the intended scanner-reconciliation behavior."""
        src, tgt = self._seed_nodes(store)
        r = store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="USES_FRAMEWORK",
            collector_type="repo_scanner",
            confidence=0.9,
            evidence=[],
            now=_NOW1,
        )
        edge_id = r["edge_id"]

        resolved = store.mark_edges_resolved(set(), _TARGET_REPO, now=_NOW2)

        assert resolved == 1
        edges = store.get_active_edges(_TARGET_REPO)
        assert not any(e["edge_id"] == edge_id for e in edges)

    def test_mixed_edges_only_inferred_resolved(self, store):
        """When both a human_declared and an inferred edge exist for the same
        target, only the inferred edge is resolved by a scan."""
        src, tgt = self._seed_nodes(store)
        store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="DEPENDS_ON",
            collector_type="human_declared",
            confidence=1.0,
            evidence=[],
            now=_NOW1,
        )
        store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="USES_LLM_PROVIDER",
            collector_type="repo_scanner",
            confidence=0.92,
            evidence=[],
            now=_NOW1,
        )

        resolved = store.mark_edges_resolved(set(), _TARGET_REPO, now=_NOW2)

        assert resolved == 1  # only the inferred one
        edges = store.get_active_edges(_TARGET_REPO)
        assert len(edges) == 1
        assert edges[0]["collector_type"] == "human_declared"

    def test_reactivated_edge_survives_subsequent_scans(self, store):
        """After an edge is reactivated (e.g., by re-running the loader),
        the next scan cannot resolve it again."""
        src, tgt = self._seed_nodes(store)
        edge_r = store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="DEPENDS_ON",
            collector_type="human_declared",
            confidence=1.0,
            evidence=[],
            now=_NOW1,
        )
        edge_id = edge_r["edge_id"]

        # Simulate the bug: manually force-resolve the edge (as if old bug ran)
        store._conn.execute(
            "UPDATE graph_edges SET resolved_at = ? WHERE edge_id = ?",
            (_NOW2.isoformat(), edge_id),
        )
        store._conn.commit()

        # Re-run the loader (upsert_edge reactivates)
        store.upsert_edge(
            source_node_id=src,
            target_node_id=tgt,
            relationship="DEPENDS_ON",
            collector_type="human_declared",
            confidence=1.0,
            evidence=[],
            now=_NOW2,
        )

        # Verify reactivation and event log
        history = store.get_edge_history(edge_id)
        assert any(e["event_type"] == "reactivated" for e in history)

        # Next scan still cannot resolve it
        resolved = store.mark_edges_resolved(set(), _TARGET_REPO, now=_NOW2)
        assert resolved == 0


# ---------------------------------------------------------------------------
# 3. Direction guard rejects wrong-direction relationships at load time
# ---------------------------------------------------------------------------

class TestDirectionGuard:
    def _make_loader(self, tmp_path, yaml_content: str):
        """Helper: set up loader module to use a test YAML and DB."""
        import scripts.load_operational_graph as loader_mod
        yaml_path = tmp_path / "operational_graph.yml"
        yaml_path.write_text(yaml_content)
        db_path = str(tmp_path / "test.db")
        orig_yaml, orig_db = loader_mod._YAML_PATH, loader_mod._DB_PATH
        loader_mod._YAML_PATH = yaml_path
        loader_mod._DB_PATH = db_path
        yield loader_mod.load
        loader_mod._YAML_PATH = orig_yaml
        loader_mod._DB_PATH = orig_db

    def test_feeds_spend_to_rejected_with_helpful_message(self, tmp_path):
        """FEEDS_SPEND_TO is a provider→consumer direction and must be rejected."""
        bad_yaml = textwrap.dedent("""
            version: "1"
            nodes: []
            edges:
              - from: {id: repo:lesia, target: /root/lesia}
                to:   {id: repo:quartermaster, target: /root/quartermaster}
                relationship: FEEDS_SPEND_TO
                description: "lesia provides spend data to quartermaster"
                evidence: "manual"
                confidence: 0.7
        """)
        gen = self._make_loader(tmp_path, bad_yaml)
        load_fn = next(gen)
        with pytest.raises(ValueError) as exc_info:
            load_fn()
        msg = str(exc_info.value)
        assert "FEEDS_SPEND_TO" in msg
        assert "READS_FROM" in msg
        assert "dependent" in msg.lower() or "direction" in msg.lower()
        try:
            next(gen)
        except StopIteration:
            pass

    def test_reads_from_accepted(self, tmp_path):
        """READS_FROM (correct dependent→dependency direction) must load cleanly."""
        good_yaml = textwrap.dedent("""
            version: "1"
            nodes:
              - id: repo:quartermaster
                target: /root/quartermaster
                consequence: "if down → no reports"
                owner_facing: true
              - id: repo:lesia
                target: /root/lesia
                consequence: unknown
                owner_facing: true
            edges:
              - from: {id: repo:quartermaster, target: /root/quartermaster}
                to:   {id: repo:lesia,  target: /root/lesia}
                relationship: READS_FROM
                description: "quartermaster reads spend records from lesia"
                evidence: "data/spend/lesia_p7_audit.jsonl"
                confidence: 0.7
        """)
        gen = self._make_loader(tmp_path, good_yaml)
        load_fn = next(gen)
        summary = load_fn()  # must not raise
        assert summary["edges_declared"] == 1
        try:
            next(gen)
        except StopIteration:
            pass

    def test_depends_on_accepted(self, tmp_path):
        """DEPENDS_ON is the primary hard-dependency relationship; must load."""
        good_yaml = textwrap.dedent("""
            version: "1"
            nodes:
              - id: repo:humint
                target: /root/humint
                consequence: "if down → no HUMINT reports"
                owner_facing: true
              - id: service:postgresql
                target: vps
                consequence: "if down → HUMINT fails"
                owner_facing: false
            edges:
              - from: {id: repo:humint,         target: /root/humint}
                to:   {id: service:postgresql,  target: vps}
                relationship: DEPENDS_ON
                description: "HUMINT requires postgres"
                evidence: "unit file"
                confidence: 1.0
        """)
        gen = self._make_loader(tmp_path, good_yaml)
        load_fn = next(gen)
        summary = load_fn()
        assert summary["edges_declared"] == 1
        try:
            next(gen)
        except StopIteration:
            pass

    def test_direction_check_function_directly(self):
        from scripts.load_operational_graph import _check_edge_direction
        # Wrong direction raises
        with pytest.raises(ValueError):
            _check_edge_direction({
                "from": {"id": "repo:a"}, "to": {"id": "repo:b"},
                "relationship": "FEEDS_SPEND_TO",
            })
        # Correct direction passes silently
        _check_edge_direction({
            "from": {"id": "repo:a"}, "to": {"id": "repo:b"},
            "relationship": "READS_FROM",
        })
        _check_edge_direction({
            "from": {"id": "repo:a"}, "to": {"id": "service:db"},
            "relationship": "DEPENDS_ON",
        })

    def test_dry_run_with_wrong_direction_still_raises(self, tmp_path):
        """Even in dry-run mode, wrong-direction edges must be caught.
        The error is in the YAML, not the DB write — dry-run doesn't excuse it."""
        bad_yaml = textwrap.dedent("""
            version: "1"
            nodes: []
            edges:
              - from: {id: repo:a, target: /root/a}
                to:   {id: repo:b, target: /root/b}
                relationship: FEEDS_SPEND_TO
                description: "wrong direction"
                evidence: "none"
                confidence: 0.5
        """)
        gen = self._make_loader(tmp_path, bad_yaml)
        load_fn = next(gen)
        with pytest.raises(ValueError):
            load_fn(dry_run=True)
        try:
            next(gen)
        except StopIteration:
            pass


# ---------------------------------------------------------------------------
# 4. collector_type field itself
# ---------------------------------------------------------------------------

class TestCollectorTypeField:
    def test_new_node_stores_collector_type(self, store):
        r = store.upsert_node(
            target_id=_TARGET_VPS,
            builder_node_id="service:nginx",
            node_type="service",
            label="nginx",
            collector_type="human_declared",
            now=_NOW1,
        )
        rows = store._conn.execute(
            "SELECT collector_type FROM graph_nodes WHERE node_id = ?",
            (r["node_id"],),
        ).fetchall()
        assert rows[0]["collector_type"] == "human_declared"

    def test_default_collector_type_is_empty_string(self, store):
        r = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:legacy",
            node_type="repository",
            label="legacy",
            now=_NOW1,
        )
        rows = store._conn.execute(
            "SELECT collector_type FROM graph_nodes WHERE node_id = ?",
            (r["node_id"],),
        ).fetchall()
        assert rows[0]["collector_type"] == ""

    def test_topology_builder_stores_collector_type(self, store):
        r = store.upsert_node(
            target_id=_TARGET_REPO,
            builder_node_id="repo:humint",
            node_type="repository",
            label="humint",
            collector_type="topology_builder",
            now=_NOW1,
        )
        rows = store._conn.execute(
            "SELECT collector_type FROM graph_nodes WHERE node_id = ?",
            (r["node_id"],),
        ).fetchall()
        assert rows[0]["collector_type"] == "topology_builder"
