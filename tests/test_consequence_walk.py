"""Tests for cognition/consequence_walk.py — the WHAT-IF brain.

Uses a minimal seeded graph so tests are self-contained and never touch
the live operational_memory.db. Each test class builds its own tmp_path store.

Graph topology used in most tests:
  postgres  [service, vps]            ← no dependencies
     ↑  DEPENDS_ON (hard)
  humint    [repo, /root/humint]     owner_facing=true
     ↑  DEPENDS_ON (hard) — NOT in test graph (nothing depends on humint in the base graph)
  quartermaster    [repo, /root/quartermaster]     owner_facing=true
     ↑  SCANS humint  (non-propagating)
  lesia     [repo, /root/lesia]      consequence=unknown, owner_facing=true
     ↓  FEEDS_SPEND_TO quartermaster (soft)

Annotations:
  postgres : consequence="if down → HUMINT fails", owner_facing=false
  humint   : consequence="if down → no HUMINT reports", owner_facing=true
  quartermaster   : consequence="if down → no incident reports", owner_facing=true
  lesia    : consequence=unknown, owner_facing=true
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cognition.consequence_walk import (
    ConsequenceWalk,
    _dep_type,
    _propagates,
    walk,
    walk_by_label,
)
from memory.graph_store import GraphStore

_NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)

# Target constants
_T_VPS = "vps"
_T_HUMINT = "/root/humint"
_T_OPSMEM = "/root/quartermaster"
_T_LESIA = "/root/lesia"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


@pytest.fixture
def seeded_store(tmp_path):
    """A store pre-seeded with the base test graph described in the module docstring."""
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    _seed_base_graph(s)
    yield s
    s.disconnect()


def _seed_base_graph(store: GraphStore) -> dict[str, str]:
    """Seed the canonical test topology. Returns {name: node_id} for convenience."""
    ids: dict[str, str] = {}

    # Nodes
    for target, builder_id, label, node_type in [
        (_T_VPS,    "service:postgresql", "postgresql", "service"),
        (_T_HUMINT, "repo:humint",        "humint",     "repository"),
        (_T_OPSMEM, "repo:quartermaster",        "quartermaster",     "repository"),
        (_T_LESIA,  "repo:lesia",         "lesia",      "repository"),
    ]:
        r = store.upsert_node(
            target_id=target, builder_node_id=builder_id,
            node_type=node_type, label=label, now=_NOW,
        )
        ids[label] = r["node_id"]

    # Edges
    # humint DEPENDS_ON postgres (hard)
    store.upsert_edge(
        source_node_id=ids["humint"],
        target_node_id=ids["postgresql"],
        relationship="DEPENDS_ON",
        collector_type="human_declared",
        confidence=1.0,
        evidence=[{"source": "human_declared", "detail": "humint-api.service Wants=postgresql.service"}],
        now=_NOW,
    )
    # quartermaster SCANS humint (non-propagating)
    store.upsert_edge(
        source_node_id=ids["quartermaster"],
        target_node_id=ids["humint"],
        relationship="SCANS",
        collector_type="human_declared",
        confidence=1.0,
        evidence=[{"source": "human_declared", "detail": "SCAN_TARGETS includes /root/humint"}],
        now=_NOW,
    )
    # quartermaster READS_FROM lesia (soft) — quartermaster (dependent) → lesia (dependency)
    store.upsert_edge(
        source_node_id=ids["quartermaster"],
        target_node_id=ids["lesia"],
        relationship="READS_FROM",
        collector_type="human_declared",
        confidence=0.7,
        evidence=[{"source": "human_declared", "detail": "data/spend/lesia_p7_audit.jsonl in quartermaster drop dir"}],
        now=_NOW,
    )

    # Annotations
    _annotate(store, ids["postgresql"],
              consequence="if down → HUMINT fails", owner_facing="false")
    _annotate(store, ids["humint"],
              consequence="if down → no HUMINT reports", owner_facing="true")
    _annotate(store, ids["quartermaster"],
              consequence="if down → no incident reports", owner_facing="true")
    _annotate(store, ids["lesia"],
              consequence="unknown", owner_facing="true")

    return ids


def _annotate(store: GraphStore, node_id: str, consequence: str, owner_facing: str) -> None:
    store.set_node_annotation(node_id=node_id, annotation_type="consequence",
                              value=consequence, evidence="test", now=_NOW)
    store.set_node_annotation(node_id=node_id, annotation_type="owner_facing",
                              value=owner_facing, evidence="test", now=_NOW)


def _ids(store: GraphStore) -> dict[str, str]:
    """Return {label: node_id} for all active nodes in the store."""
    return {n["label"]: n["node_id"] for n in store.get_active_nodes()}


# ---------------------------------------------------------------------------
# Edge classification constants
# ---------------------------------------------------------------------------

class TestEdgeClassification:
    def test_hard_dep_rels_propagate(self):
        for rel in ("DEPENDS_ON", "USES_VENV"):
            assert _propagates(rel), f"{rel} should propagate"

    def test_soft_dep_rels_propagate(self):
        for rel in ("READS_FROM",):
            assert _propagates(rel), f"{rel} should propagate"

    def test_feeds_spend_to_does_not_propagate(self):
        """FEEDS_SPEND_TO uses producer→consumer direction; excluded to avoid
        backwards traversal. Use READS_FROM on the consumer side instead."""
        assert not _propagates("FEEDS_SPEND_TO")

    def test_non_propagating_rels(self):
        for rel in ("SCANS", "EXPOSES_PORT", "RUNS_IN_DOCKER",
                    "USES_FRAMEWORK", "USES_LLM_PROVIDER", "LIKELY_RELATED_TO"):
            assert not _propagates(rel), f"{rel} should NOT propagate"

    def test_dep_type_hard(self):
        assert _dep_type("DEPENDS_ON") == "hard"
        assert _dep_type("USES_VENV") == "hard"

    def test_dep_type_soft(self):
        assert _dep_type("FEEDS_SPEND_TO") == "soft"


# ---------------------------------------------------------------------------
# Empty and trivial cases
# ---------------------------------------------------------------------------

class TestTrivialCases:
    def test_empty_down_list(self, seeded_store):
        result = walk([], seeded_store)
        assert result.hypothetical == []
        assert result.affected == []
        assert result.root_causes == []
        assert result.owner_facing_lost == []

    def test_unknown_node_id_graceful(self, seeded_store):
        result = walk(["nonexistent-sha256"], seeded_store)
        assert result.affected == []
        # unknown node is treated as a root cause (no deps found)
        assert len(result.root_causes) == 1

    def test_empty_store(self, store):
        result = walk(["some-id"], store)
        assert result.affected == []


# ---------------------------------------------------------------------------
# Single-node hypothetical: postgres down
# ---------------------------------------------------------------------------

class TestPostgresDown:
    def test_humint_is_affected(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "humint" in affected_labels

    def test_quartermaster_not_affected_scans_is_non_propagating(self, seeded_store):
        """SCANS edge between quartermaster and humint should NOT cascade postgres→quartermaster."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "quartermaster" not in affected_labels

    def test_lesia_not_affected_no_dep_on_postgres(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "lesia" not in affected_labels

    def test_humint_depth_is_1(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        humint_affected = next(a for a in result.affected if a.label == "humint")
        assert humint_affected.depth == 1

    def test_humint_dependency_type_is_hard(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        humint_affected = next(a for a in result.affected if a.label == "humint")
        assert humint_affected.dependency_type == "hard"

    def test_postgres_is_root_cause(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        assert len(result.root_causes) == 1
        assert result.root_causes[0].label == "postgresql"

    def test_owner_facing_lost_includes_humint(self, seeded_store):
        """HUMINT is owner_facing=true and goes dark when postgres fails."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        lost_labels = {x["label"] for x in result.owner_facing_lost}
        assert "humint" in lost_labels

    def test_owner_facing_lost_excludes_postgres(self, seeded_store):
        """postgres is owner_facing=false."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        lost_labels = {x["label"] for x in result.owner_facing_lost}
        assert "postgresql" not in lost_labels

    def test_humint_consequence_is_populated(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        humint_affected = next(a for a in result.affected if a.label == "humint")
        assert humint_affected.consequence == "if down → no HUMINT reports"

    def test_path_confidence_is_product_of_edge_confidences(self, seeded_store):
        """postgres→humint edge has confidence=1.0; path_confidence should be 1.0."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        humint_affected = next(a for a in result.affected if a.label == "humint")
        assert abs(humint_affected.path_confidence - 1.0) < 0.01

    def test_evidence_trail_not_empty(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        assert len(result.evidence_trail) > 0

    def test_summary_mentions_root_cause(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"]], seeded_store)
        assert "postgresql" in result.summary.lower() or "root cause" in result.summary.lower()


# ---------------------------------------------------------------------------
# Root cause collapse: postgres + humint both down
# ---------------------------------------------------------------------------

class TestRootCauseCollapse:
    def test_postgres_is_root_cause_humint_is_collateral(self, seeded_store):
        """When both postgres and humint are down, postgres is the root cause
        because it has no hard deps in the down set. Humint's hard dep (postgres)
        IS in the down set, so humint is collateral."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"], nids["humint"]], seeded_store)
        rc_labels = {rc.label for rc in result.root_causes}
        assert "postgresql" in rc_labels
        assert "humint" not in rc_labels

    def test_collateral_contains_humint(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"], nids["humint"]], seeded_store)
        combined = " ".join(result.collateral)
        assert "humint" in combined

    def test_affected_is_empty_when_all_dependents_are_initial_down(self, seeded_store):
        """Both postgres and humint are already in the initial down set.
        SCANS is non-propagating, so nothing cascades to quartermaster or lesia."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"], nids["humint"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "quartermaster" not in affected_labels
        assert "lesia" not in affected_labels

    def test_both_initial_down_are_owner_facing_considered(self, seeded_store):
        """humint is owner_facing=true and is in the initial down set at depth=0."""
        nids = _ids(seeded_store)
        result = walk([nids["postgresql"], nids["humint"]], seeded_store)
        lost_labels = {x["label"] for x in result.owner_facing_lost}
        assert "humint" in lost_labels


# ---------------------------------------------------------------------------
# Soft dependency: lesia down
# ---------------------------------------------------------------------------

class TestLesiaDown:
    def test_quartermaster_is_degraded_not_down(self, seeded_store):
        """lesia FEEDS_SPEND_TO quartermaster is a soft dep. quartermaster appears in affected
        with dependency_type=soft."""
        nids = _ids(seeded_store)
        result = walk([nids["lesia"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "quartermaster" in affected_labels

    def test_quartermaster_affected_as_soft(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["lesia"]], seeded_store)
        quartermaster_affected = next(a for a in result.affected if a.label == "quartermaster")
        assert quartermaster_affected.dependency_type == "soft"

    def test_confidence_degraded_for_soft_dep(self, seeded_store):
        """READS_FROM edge has confidence=0.7; soft multiplier=0.7 → path_conf = 0.7*0.7 = 0.49."""
        nids = _ids(seeded_store)
        result = walk([nids["lesia"]], seeded_store)
        quartermaster_affected = next(a for a in result.affected if a.label == "quartermaster")
        assert quartermaster_affected.path_confidence < 0.7

    def test_lesia_consequence_is_unknown(self, seeded_store):
        """lesia's consequence annotation is 'unknown' — it appears in unknown_consequences."""
        nids = _ids(seeded_store)
        result = walk([nids["lesia"]], seeded_store)
        # lesia is in the initial down set; its consequence should appear in owner_facing_lost
        # as "unknown" (owner_facing=true)
        lesia_lost = next(
            (x for x in result.owner_facing_lost if x["label"] == "lesia"), None
        )
        assert lesia_lost is not None
        assert lesia_lost["consequence"] == "unknown"

    def test_unknown_consequences_list_includes_affected_unknowns(self, seeded_store):
        """quartermaster is affected via soft dep; its consequence is known. No unknowns from cascade."""
        nids = _ids(seeded_store)
        result = walk([nids["lesia"]], seeded_store)
        # quartermaster has a known consequence annotation, so it should NOT be in unknown_consequences
        assert "quartermaster" not in result.unknown_consequences


# ---------------------------------------------------------------------------
# HUMINT down alone (single node, owner-facing)
# ---------------------------------------------------------------------------

class TestHumintDown:
    def test_owner_facing_lost_includes_humint_consequence(self, seeded_store):
        nids = _ids(seeded_store)
        result = walk([nids["humint"]], seeded_store)
        lost = {x["label"]: x for x in result.owner_facing_lost}
        assert "humint" in lost
        assert lost["humint"]["consequence"] == "if down → no HUMINT reports"

    def test_postgres_not_in_affected_it_is_humints_dep_not_dependent(self, seeded_store):
        """postgres is what humint depends ON — it doesn't go dark when humint goes down."""
        nids = _ids(seeded_store)
        result = walk([nids["humint"]], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "postgresql" not in affected_labels

    def test_humint_alone_is_root_cause(self, seeded_store):
        """humint's dependency (postgres) is NOT in the down set — so humint is root cause."""
        nids = _ids(seeded_store)
        result = walk([nids["humint"]], seeded_store)
        assert len(result.root_causes) == 1
        assert result.root_causes[0].label == "humint"


# ---------------------------------------------------------------------------
# Consequence unknown reporting
# ---------------------------------------------------------------------------

class TestUnknownConsequence:
    def test_no_consequence_annotation_reported_as_unknown(self, store):
        """A node with no consequence annotation at all → consequence='unknown'."""
        r = store.upsert_node(
            target_id="vps", builder_node_id="service:mystery",
            node_type="service", label="mystery", now=_NOW,
        )
        r2 = store.upsert_node(
            target_id="/root/consumer", builder_node_id="repo:consumer",
            node_type="repository", label="consumer", now=_NOW,
        )
        store.upsert_edge(
            source_node_id=r2["node_id"], target_node_id=r["node_id"],
            relationship="DEPENDS_ON", collector_type="human_declared",
            confidence=0.9, evidence=[], now=_NOW,
        )
        # No consequence annotation on either node
        result = walk([r["node_id"]], store)
        consumer_affected = next(
            (a for a in result.affected if a.label == "consumer"), None
        )
        assert consumer_affected is not None
        assert consumer_affected.consequence == "unknown"
        assert "consumer" in result.unknown_consequences


# ---------------------------------------------------------------------------
# walk_by_label convenience wrapper
# ---------------------------------------------------------------------------

class TestWalkByLabel:
    def test_walk_by_label_same_as_walk_by_id(self, seeded_store):
        nids = _ids(seeded_store)
        result_by_id = walk([nids["postgresql"]], seeded_store)
        result_by_label = walk_by_label(["postgresql"], seeded_store)
        assert {a.label for a in result_by_id.affected} == \
               {a.label for a in result_by_label.affected}

    def test_walk_by_label_unknown_label_returns_empty(self, seeded_store):
        result = walk_by_label(["no_such_service"], seeded_store)
        assert result.hypothetical == []
        assert result.affected == []

    def test_walk_by_label_case_insensitive(self, seeded_store):
        result = walk_by_label(["POSTGRESQL"], seeded_store)
        affected_labels = {a.label for a in result.affected}
        assert "humint" in affected_labels


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_inputs_same_result(self, seeded_store):
        nids = _ids(seeded_store)
        r1 = walk([nids["postgresql"]], seeded_store)
        r2 = walk([nids["postgresql"]], seeded_store)
        assert r1.to_dict() == r2.to_dict()

    def test_two_node_walk_deterministic(self, seeded_store):
        nids = _ids(seeded_store)
        r1 = walk([nids["postgresql"], nids["lesia"]], seeded_store)
        r2 = walk([nids["postgresql"], nids["lesia"]], seeded_store)
        assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# Multi-edge deduplication
# ---------------------------------------------------------------------------

class TestMultiEdgeDedup:
    def test_two_edges_same_pair_merged(self, store):
        """When two edges exist between the same (src, tgt) pair, they are merged
        into one logical dependency with max(confidence) and union(evidence)."""
        r_src = store.upsert_node(
            target_id="/root/app", builder_node_id="repo:app",
            node_type="repository", label="app", now=_NOW,
        )
        r_tgt = store.upsert_node(
            target_id="vps", builder_node_id="service:db",
            node_type="service", label="db", now=_NOW,
        )
        # Two edges: one from repo_scanner (inferred), one human_declared
        store.upsert_edge(
            source_node_id=r_src["node_id"], target_node_id=r_tgt["node_id"],
            relationship="DEPENDS_ON", collector_type="repo_scanner",
            confidence=0.8,
            evidence=[{"source": "repo_scanner", "detail": "inferred from port"}],
            now=_NOW,
        )
        store.upsert_edge(
            source_node_id=r_src["node_id"], target_node_id=r_tgt["node_id"],
            relationship="DEPENDS_ON", collector_type="human_declared",
            confidence=1.0,
            evidence=[{"source": "human_declared", "detail": "unit file confirms"}],
            now=_NOW,
        )
        _annotate(store, r_tgt["node_id"], "if down → app fails", "false")

        result = walk([r_tgt["node_id"]], store)
        app_affected = next(a for a in result.affected if a.label == "app")
        # max confidence = 1.0 (from human_declared)
        assert app_affected.path_confidence == pytest.approx(1.0)
        # evidence contains both details
        combined_ev = " ".join(app_affected.evidence)
        assert "unit file" in combined_ev or "inferred from port" in combined_ev


# ---------------------------------------------------------------------------
# Cycle guard
# ---------------------------------------------------------------------------

class TestCycleGuard:
    def test_cycle_does_not_loop_forever(self, store):
        """A → B → A cycle must not produce infinite recursion."""
        rA = store.upsert_node(
            target_id="vps", builder_node_id="service:a",
            node_type="service", label="a", now=_NOW,
        )
        rB = store.upsert_node(
            target_id="vps", builder_node_id="service:b",
            node_type="service", label="b", now=_NOW,
        )
        # A DEPENDS_ON B and B DEPENDS_ON A (cycle)
        store.upsert_edge(
            source_node_id=rA["node_id"], target_node_id=rB["node_id"],
            relationship="DEPENDS_ON", collector_type="human_declared",
            confidence=1.0, evidence=[], now=_NOW,
        )
        store.upsert_edge(
            source_node_id=rB["node_id"], target_node_id=rA["node_id"],
            relationship="DEPENDS_ON", collector_type="human_declared",
            confidence=1.0, evidence=[], now=_NOW,
        )
        # Should terminate without error
        result = walk([rA["node_id"]], store)
        assert isinstance(result, ConsequenceWalk)

    def test_max_depth_limits_long_chain(self, store):
        """A chain longer than max_depth is cut off at max_depth."""
        # Create a chain: n0 → n1 → n2 → ... → n5
        nodes = []
        for i in range(6):
            r = store.upsert_node(
                target_id="vps", builder_node_id=f"service:n{i}",
                node_type="service", label=f"n{i}", now=_NOW,
            )
            nodes.append(r)
        for i in range(5):
            store.upsert_edge(
                source_node_id=nodes[i]["node_id"],
                target_node_id=nodes[i + 1]["node_id"],
                relationship="DEPENDS_ON", collector_type="human_declared",
                confidence=1.0, evidence=[], now=_NOW,
            )
        # Walk from n5 (the leaf dependency) with max_depth=2 — only n4 and n3 affected
        result = walk([nodes[5]["node_id"]], store, max_depth=2)
        affected_labels = {a.label for a in result.affected}
        assert "n4" in affected_labels
        assert "n3" in affected_labels
        assert "n0" not in affected_labels
