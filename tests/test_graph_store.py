"""Tests for memory/graph_store.py and topology/persistence.py.

Validates the properties the consequence brain depends on:
  - Identity is deterministic (same inputs → same SHA-256, always)
  - Upsert creates on first call, updates on subsequent calls
  - Reactivation clears resolved_at and fires a "reactivated" event
  - mark_nodes_resolved / mark_edges_resolved never touch active items
  - Cross-target isolation: same builder_node_id in two targets → distinct node_ids
  - persist_topology correctly maps topology_dict → graph_store operations
  - Reconciliation: a node absent from scan B is resolved after scan B
  - Empty topology dict is handled without errors
  - Event log is append-only (events accumulate, are never deleted)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory.graph_store import GraphStore, compute_edge_id, compute_node_id
from topology.persistence import _derive_collector_type, persist_topology

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


_T1 = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 1, 16, 0, 0, tzinfo=UTC)
_T3 = datetime(2026, 6, 2,  8, 0, 0, tzinfo=UTC)

_TARGET_A = "/root/lesia"
_TARGET_B = "/srv/seo-agent"


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

class TestIdentityHelpers:
    def test_compute_node_id_deterministic(self):
        a = compute_node_id(_TARGET_A, "repo:lesia")
        b = compute_node_id(_TARGET_A, "repo:lesia")
        assert a == b

    def test_compute_node_id_is_sha256_hex(self):
        nid = compute_node_id(_TARGET_A, "repo:lesia")
        assert len(nid) == 64
        assert all(c in "0123456789abcdef" for c in nid)

    def test_compute_node_id_differs_by_target(self):
        a = compute_node_id(_TARGET_A, "port:8001")
        b = compute_node_id(_TARGET_B, "port:8001")
        assert a != b

    def test_compute_node_id_differs_by_builder_id(self):
        a = compute_node_id(_TARGET_A, "port:8001")
        b = compute_node_id(_TARGET_A, "port:8002")
        assert a != b

    def test_compute_node_id_no_prefix_collision(self):
        # "ab" + "c" must not equal "a" + "bc"
        a = compute_node_id("ab", "c")
        b = compute_node_id("a", "bc")
        assert a != b

    def test_compute_edge_id_deterministic(self):
        src = compute_node_id(_TARGET_A, "repo:lesia")
        tgt = compute_node_id(_TARGET_A, "llm_provider:anthropic")
        a = compute_edge_id(src, tgt, "USES_LLM_PROVIDER", "repo_scanner")
        b = compute_edge_id(src, tgt, "USES_LLM_PROVIDER", "repo_scanner")
        assert a == b

    def test_compute_edge_id_differs_by_relationship(self):
        src = compute_node_id(_TARGET_A, "repo:lesia")
        tgt = compute_node_id(_TARGET_A, "port:8001")
        a = compute_edge_id(src, tgt, "EXPOSES_PORT", "service_scanner")
        b = compute_edge_id(src, tgt, "DEPENDS_ON", "service_scanner")
        assert a != b

    def test_compute_edge_id_differs_by_collector(self):
        src = compute_node_id(_TARGET_A, "repo:lesia")
        tgt = compute_node_id(_TARGET_A, "llm_provider:anthropic")
        a = compute_edge_id(src, tgt, "USES_LLM_PROVIDER", "repo_scanner")
        b = compute_edge_id(src, tgt, "USES_LLM_PROVIDER", "llm_detector")
        assert a != b


# ---------------------------------------------------------------------------
# Node upsert lifecycle
# ---------------------------------------------------------------------------

class TestNodeUpsert:
    def test_insert_new_node(self, store):
        result = store.upsert_node(
            target_id=_TARGET_A,
            builder_node_id="repo:lesia",
            node_type="repository",
            label="lesia",
            now=_T1,
        )
        assert "node_id" in result
        nodes = store.get_active_nodes(_TARGET_A)
        assert len(nodes) == 1
        assert nodes[0]["label"] == "lesia"
        assert nodes[0]["occurrence_count"] == 1
        assert nodes[0]["resolved_at"] is None

    def test_upsert_increments_occurrence_count(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T2,
        )
        nodes = store.get_active_nodes(_TARGET_A)
        assert nodes[0]["occurrence_count"] == 2

    def test_upsert_updates_last_seen(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T2,
        )
        nodes = store.get_active_nodes(_TARGET_A)
        assert nodes[0]["last_seen"] == _T2.isoformat()
        assert nodes[0]["first_seen"] == _T1.isoformat()

    def test_upsert_returns_same_node_id(self, store):
        r1 = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        r2 = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T2,
        )
        assert r1["node_id"] == r2["node_id"]

    def test_node_id_matches_compute_helper(self, store):
        result = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        expected = compute_node_id(_TARGET_A, "repo:lesia")
        assert result["node_id"] == expected

    def test_appeared_event_on_insert(self, store):
        result = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        history = store.get_node_history(result["node_id"])
        assert len(history) == 1
        assert history[0]["event_type"] == "appeared"

    def test_no_duplicate_events_on_update(self, store):
        result = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T2,
        )
        history = store.get_node_history(result["node_id"])
        # second call is a plain update — only the original "appeared" event
        assert len(history) == 1
        assert history[0]["event_type"] == "appeared"


# ---------------------------------------------------------------------------
# Node reactivation
# ---------------------------------------------------------------------------

class TestNodeReactivation:
    def test_reactivation_clears_resolved_at(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        # resolve it
        store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        # verify it's resolved
        assert store.count_nodes(_TARGET_A, active_only=True) == 0

        # reappears
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T3,
        )
        nodes = store.get_active_nodes(_TARGET_A)
        assert len(nodes) == 1
        assert nodes[0]["resolved_at"] is None

    def test_reactivation_fires_event(self, store):
        r = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T3,
        )
        history = store.get_node_history(r["node_id"])
        event_types = [e["event_type"] for e in history]
        assert "appeared" in event_types
        assert "resolved" in event_types
        assert "reactivated" in event_types


# ---------------------------------------------------------------------------
# Edge upsert lifecycle
# ---------------------------------------------------------------------------

class TestEdgeUpsert:
    def _nodes(self, store):
        r1 = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        r2 = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="llm_provider:anthropic",
            node_type="llm_provider", label="anthropic", now=_T1,
        )
        return r1["node_id"], r2["node_id"]

    def test_insert_new_edge(self, store):
        src, tgt = self._nodes(store)
        result = store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=[{"source": "package_manifest", "detail": "anthropic in deps"}],
            now=_T1,
        )
        assert "edge_id" in result
        edges = store.get_active_edges(_TARGET_A)
        assert len(edges) == 1
        assert edges[0]["relationship"] == "USES_LLM_PROVIDER"
        assert edges[0]["confidence"] == pytest.approx(0.92)

    def test_upsert_edge_increments_occurrence_count(self, store):
        src, tgt = self._nodes(store)
        store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=[], now=_T1,
        )
        store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=[], now=_T2,
        )
        edges = store.get_active_edges(_TARGET_A)
        assert edges[0]["occurrence_count"] == 2

    def test_edge_id_matches_compute_helper(self, store):
        src, tgt = self._nodes(store)
        result = store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=[], now=_T1,
        )
        expected = compute_edge_id(src, tgt, "USES_LLM_PROVIDER", "repo_scanner")
        assert result["edge_id"] == expected

    def test_appeared_event_on_edge_insert(self, store):
        src, tgt = self._nodes(store)
        result = store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=[], now=_T1,
        )
        history = store.get_edge_history(result["edge_id"])
        assert len(history) == 1
        assert history[0]["event_type"] == "appeared"

    def test_evidence_survives_round_trip(self, store):
        src, tgt = self._nodes(store)
        ev = [{"source": "package_manifest", "detail": "anthropic==0.25.0"}]
        store.upsert_edge(
            source_node_id=src, target_node_id=tgt,
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.92, evidence=ev, now=_T1,
        )
        edges = store.get_active_edges(_TARGET_A)
        assert edges[0]["evidence"] == ev


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class TestReconciliation:
    def test_mark_nodes_resolved_removes_absent_node(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        count = store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        assert count == 1
        assert store.count_nodes(_TARGET_A, active_only=True) == 0

    def test_mark_nodes_resolved_keeps_active_node(self, store):
        r = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        active_ids = {r["node_id"]}
        count = store.mark_nodes_resolved(active_ids, _TARGET_A, now=_T2)
        assert count == 0
        assert store.count_nodes(_TARGET_A, active_only=True) == 1

    def test_mark_nodes_resolved_fires_event(self, store):
        r = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        history = store.get_node_history(r["node_id"])
        event_types = [e["event_type"] for e in history]
        assert "resolved" in event_types

    def test_mark_nodes_resolved_does_not_double_resolve(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        count2 = store.mark_nodes_resolved(set(), _TARGET_A, now=_T3)
        # second call finds nothing active to resolve
        assert count2 == 0

    def test_mark_edges_resolved_scoped_by_target(self, store):
        # Node in target A
        rA = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        rA2 = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="llm_provider:anthropic",
            node_type="llm_provider", label="anthropic", now=_T1,
        )
        store.upsert_edge(
            source_node_id=rA["node_id"], target_node_id=rA2["node_id"],
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.9, evidence=[], now=_T1,
        )
        # Node in target B
        rB = store.upsert_node(
            target_id=_TARGET_B, builder_node_id="repo:seo-agent",
            node_type="repository", label="seo-agent", now=_T1,
        )
        rB2 = store.upsert_node(
            target_id=_TARGET_B, builder_node_id="llm_provider:openai",
            node_type="llm_provider", label="openai", now=_T1,
        )
        store.upsert_edge(
            source_node_id=rB["node_id"], target_node_id=rB2["node_id"],
            relationship="USES_LLM_PROVIDER", collector_type="repo_scanner",
            confidence=0.9, evidence=[], now=_T1,
        )

        # Resolve all edges for target A only
        count = store.mark_edges_resolved(set(), _TARGET_A, now=_T2)
        assert count == 1  # only target A's edge resolved

        # Target B's edge remains active
        edges_b = store.get_active_edges(_TARGET_B)
        assert len(edges_b) == 1


# ---------------------------------------------------------------------------
# Cross-target isolation
# ---------------------------------------------------------------------------

class TestCrossTargetIsolation:
    def test_same_builder_id_different_targets_different_node_ids(self, store):
        rA = store.upsert_node(
            target_id=_TARGET_A, builder_node_id="llm_provider:anthropic",
            node_type="llm_provider", label="anthropic", now=_T1,
        )
        rB = store.upsert_node(
            target_id=_TARGET_B, builder_node_id="llm_provider:anthropic",
            node_type="llm_provider", label="anthropic", now=_T1,
        )
        assert rA["node_id"] != rB["node_id"]

    def test_resolving_target_a_does_not_affect_target_b(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_B, builder_node_id="repo:seo-agent",
            node_type="repository", label="seo-agent", now=_T1,
        )
        store.mark_nodes_resolved(set(), _TARGET_A, now=_T2)
        assert store.count_nodes(_TARGET_B, active_only=True) == 1

    def test_get_active_nodes_scoped_to_target(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_B, builder_node_id="repo:seo-agent",
            node_type="repository", label="seo-agent", now=_T1,
        )
        nodes_a = store.get_active_nodes(_TARGET_A)
        assert len(nodes_a) == 1
        assert nodes_a[0]["target_id"] == _TARGET_A

    def test_get_all_graphs_returns_both_targets(self, store):
        store.upsert_node(
            target_id=_TARGET_A, builder_node_id="repo:lesia",
            node_type="repository", label="lesia", now=_T1,
        )
        store.upsert_node(
            target_id=_TARGET_B, builder_node_id="repo:seo-agent",
            node_type="repository", label="seo-agent", now=_T1,
        )
        all_graphs = store.get_all_graphs()
        assert all_graphs["node_count"] == 2


# ---------------------------------------------------------------------------
# persist_topology adapter
# ---------------------------------------------------------------------------

def _make_topology_dict(
    repo_name: str = "lesia",
    llm_providers: list[str] | None = None,
    ports: list[int] | None = None,
) -> dict:
    """Build a topology_dict in the shape TopologyGraph.to_dict() produces."""
    nodes = [
        {"id": f"repo:{repo_name}", "node_type": "repository",
         "label": repo_name, "metadata": {"primary_language": "python"}},
    ]
    edges = []

    for provider in (llm_providers or []):
        nodes.append({"id": f"llm_provider:{provider}", "node_type": "llm_provider",
                      "label": provider, "metadata": {}})
        edges.append({
            "source": f"repo:{repo_name}",
            "target": f"llm_provider:{provider}",
            "relationship": "USES_LLM_PROVIDER",
            "confidence": 0.92,
            "evidence": [{"source": "package_manifest", "detail": f"{provider} in deps"}],
        })

    for port in (ports or []):
        nodes.append({"id": f"port:{port}", "node_type": "port",
                      "label": f":{port}", "metadata": {}})
        edges.append({
            "source": f"repo:{repo_name}",
            "target": f"port:{port}",
            "relationship": "EXPOSES_PORT",
            "confidence": 0.90,
            "evidence": [{"source": "service_scanner", "detail": f"listener on {port}"}],
        })

    return {"node_count": len(nodes), "edge_count": len(edges),
            "nodes": nodes, "edges": edges}


class TestPersistTopology:
    def test_empty_topology_no_error(self, store):
        summary = persist_topology({}, _TARGET_A, store, now=_T1)
        assert summary["nodes_upserted"] == 0
        assert summary["edges_upserted"] == 0

    def test_nodes_appear_in_store(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        nodes = store.get_active_nodes(_TARGET_A)
        labels = {n["label"] for n in nodes}
        assert "lesia" in labels
        assert "anthropic" in labels

    def test_edges_appear_in_store(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        edges = store.get_active_edges(_TARGET_A)
        assert len(edges) == 1
        assert edges[0]["relationship"] == "USES_LLM_PROVIDER"

    def test_summary_counts_are_correct(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic", "openai"])
        summary = persist_topology(topo, _TARGET_A, store, now=_T1)
        # 3 nodes (repo + 2 providers), 2 edges
        assert summary["nodes_upserted"] == 3
        assert summary["edges_upserted"] == 2
        assert summary["nodes_resolved"] == 0
        assert summary["edges_resolved"] == 0

    def test_reconciliation_resolves_disappeared_node(self, store):
        # Scan 1: lesia + anthropic
        topo1 = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo1, _TARGET_A, store, now=_T1)

        # Scan 2: lesia only (anthropic dropped from deps)
        topo2 = _make_topology_dict("lesia", llm_providers=[])
        summary = persist_topology(topo2, _TARGET_A, store, now=_T2)

        assert summary["nodes_resolved"] == 1   # anthropic node resolved
        assert summary["edges_resolved"] == 1   # USES_LLM_PROVIDER edge resolved
        active = store.get_active_nodes(_TARGET_A)
        assert len(active) == 1
        assert active[0]["label"] == "lesia"

    def test_reconciliation_reactivates_returned_node(self, store):
        # Scan 1: lesia + anthropic
        persist_topology(
            _make_topology_dict("lesia", llm_providers=["anthropic"]),
            _TARGET_A, store, now=_T1,
        )
        # Scan 2: anthropic gone
        persist_topology(
            _make_topology_dict("lesia", llm_providers=[]),
            _TARGET_A, store, now=_T2,
        )
        # Scan 3: anthropic back
        persist_topology(
            _make_topology_dict("lesia", llm_providers=["anthropic"]),
            _TARGET_A, store, now=_T3,
        )
        active = store.get_active_nodes(_TARGET_A)
        labels = {n["label"] for n in active}
        assert "anthropic" in labels

        # Check event log includes reactivated
        all_nodes = store.get_active_nodes(_TARGET_A)
        anthropic_node = next(n for n in all_nodes if n["label"] == "anthropic")
        history = store.get_node_history(anthropic_node["node_id"])
        event_types = [e["event_type"] for e in history]
        assert "reactivated" in event_types

    def test_idempotent_second_call_increments_occurrence(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        persist_topology(topo, _TARGET_A, store, now=_T2)
        nodes = store.get_active_nodes(_TARGET_A)
        for node in nodes:
            assert node["occurrence_count"] == 2

    def test_collector_type_derived_from_package_manifest(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        edges = store.get_active_edges(_TARGET_A)
        assert edges[0]["collector_type"] == "repo_scanner"

    def test_collector_type_derived_from_service_scanner(self, store):
        topo = _make_topology_dict("lesia", ports=[8001])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        edges = store.get_active_edges(_TARGET_A)
        assert edges[0]["collector_type"] == "service_scanner"

    def test_get_graph_for_target_returns_correct_shape(self, store):
        topo = _make_topology_dict("lesia", llm_providers=["anthropic"])
        persist_topology(topo, _TARGET_A, store, now=_T1)
        graph = store.get_graph_for_target(_TARGET_A)
        assert graph["target_id"] == _TARGET_A
        assert graph["node_count"] == 2
        assert graph["edge_count"] == 1
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1

    def test_two_targets_independent(self, store):
        persist_topology(
            _make_topology_dict("lesia", llm_providers=["anthropic"]),
            _TARGET_A, store, now=_T1,
        )
        persist_topology(
            _make_topology_dict("seo-agent", llm_providers=["openai"]),
            _TARGET_B, store, now=_T1,
        )
        graph_a = store.get_graph_for_target(_TARGET_A)
        graph_b = store.get_graph_for_target(_TARGET_B)
        labels_a = {n["label"] for n in graph_a["nodes"]}
        labels_b = {n["label"] for n in graph_b["nodes"]}
        assert "anthropic" in labels_a
        assert "openai" not in labels_a
        assert "openai" in labels_b
        assert "anthropic" not in labels_b


# ---------------------------------------------------------------------------
# _derive_collector_type
# ---------------------------------------------------------------------------

class TestDeriveCollectorType:
    def test_package_manifest_maps_to_repo_scanner(self):
        ev = [{"source": "package_manifest", "detail": "x"}]
        assert _derive_collector_type(ev) == "repo_scanner"

    def test_filesystem_maps_to_repo_scanner(self):
        ev = [{"source": "filesystem", "detail": "x"}]
        assert _derive_collector_type(ev) == "repo_scanner"

    def test_service_scanner_maps_correctly(self):
        ev = [{"source": "service_scanner", "detail": "x"}]
        assert _derive_collector_type(ev) == "service_scanner"

    def test_import_pattern_maps_to_llm_detector(self):
        ev = [{"source": "import_pattern", "detail": "x"}]
        assert _derive_collector_type(ev) == "llm_detector"

    def test_unknown_source_defaults_to_repo_scanner(self):
        ev = [{"source": "alien_source", "detail": "x"}]
        assert _derive_collector_type(ev) == "repo_scanner"

    def test_empty_evidence_defaults_to_repo_scanner(self):
        assert _derive_collector_type([]) == "repo_scanner"

    def test_first_recognised_source_wins(self):
        # filesystem first, then service_scanner — should return repo_scanner
        ev = [{"source": "filesystem", "detail": "x"},
              {"source": "service_scanner", "detail": "y"}]
        assert _derive_collector_type(ev) == "repo_scanner"
