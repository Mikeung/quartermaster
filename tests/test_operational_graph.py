"""Tests for the operator meaning layer: graph_node_annotations and the loader.

Validates:
  - set_node_annotation upserts correctly; returns True on change, False on same value
  - get_node_annotations returns the full annotation dict for a node
  - get_annotations_for_target scopes correctly
  - annotation_set event fires on new/changed, not on unchanged
  - load() creates stubs, sets annotations, loads edges with human_declared
  - load() is idempotent (second run with same YAML produces no new event rows)
  - dry_run=True produces no DB writes
  - nodes with unknown consequence and known consequence are counted correctly
"""

from __future__ import annotations

import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory.graph_store import GraphStore, compute_node_id

_T1 = datetime(2026, 6, 4, 10, 0, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 4, 16, 0, 0, tzinfo=UTC)

_TARGET_A = "/root/lesia"
_TARGET_VPS = "vps"


@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


def _seed_node(store, target_id=_TARGET_A, builder_id="repo:lesia", now=_T1):
    return store.upsert_node(
        target_id=target_id,
        builder_node_id=builder_id,
        node_type="repository",
        label="lesia",
        now=now,
    )


# ---------------------------------------------------------------------------
# set_node_annotation
# ---------------------------------------------------------------------------

class TestSetNodeAnnotation:
    def test_new_annotation_returns_true(self, store):
        r = _seed_node(store)
        changed = store.set_node_annotation(
            node_id=r["node_id"],
            annotation_type="consequence",
            value="if down → nothing",
            evidence="operator",
            now=_T1,
        )
        assert changed is True

    def test_same_value_returns_false(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="if down → nothing", evidence="op", now=_T1,
        )
        changed = store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="if down → nothing", evidence="op", now=_T2,
        )
        assert changed is False

    def test_different_value_returns_true(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="v1", evidence="op", now=_T1,
        )
        changed = store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="v2", evidence="op", now=_T2,
        )
        assert changed is True

    def test_annotation_stored_and_retrievable(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="if down → no reports", evidence="manual survey",
            collector_type="human_declared", now=_T1,
        )
        ann = store.get_node_annotations(r["node_id"])
        assert "consequence" in ann
        assert ann["consequence"]["value"] == "if down → no reports"
        assert ann["consequence"]["evidence"] == "manual survey"
        assert ann["consequence"]["collector_type"] == "human_declared"

    def test_multiple_annotation_types_stored(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="down → bad", evidence="e1", now=_T1,
        )
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="owner_facing",
            value="true", evidence="e2", now=_T1,
        )
        ann = store.get_node_annotations(r["node_id"])
        assert set(ann.keys()) == {"consequence", "owner_facing"}

    def test_annotation_fires_node_event_on_new(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="v1", evidence="e", now=_T1,
        )
        history = store.get_node_history(r["node_id"])
        event_types = [e["event_type"] for e in history]
        assert "annotation_set" in event_types

    def test_annotation_no_event_on_unchanged(self, store):
        r = _seed_node(store)
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="v1", evidence="e", now=_T1,
        )
        history_before = store.get_node_history(r["node_id"])
        store.set_node_annotation(
            node_id=r["node_id"], annotation_type="consequence",
            value="v1", evidence="e", now=_T2,
        )
        history_after = store.get_node_history(r["node_id"])
        assert len(history_after) == len(history_before)


# ---------------------------------------------------------------------------
# get_node_annotations / get_annotations_for_target
# ---------------------------------------------------------------------------

class TestGetAnnotations:
    def test_empty_if_no_annotations(self, store):
        r = _seed_node(store)
        assert store.get_node_annotations(r["node_id"]) == {}

    def test_get_annotations_for_target_scoped(self, store):
        r_a = _seed_node(store, target_id=_TARGET_A, builder_id="repo:lesia")
        r_b = store.upsert_node(
            target_id=_TARGET_VPS, builder_node_id="service:postgresql",
            node_type="service", label="postgresql", now=_T1,
        )
        store.set_node_annotation(
            node_id=r_a["node_id"], annotation_type="consequence",
            value="down → bad", evidence="e", now=_T1,
        )
        store.set_node_annotation(
            node_id=r_b["node_id"], annotation_type="consequence",
            value="db down", evidence="e", now=_T1,
        )
        ann_a = store.get_annotations_for_target(_TARGET_A)
        assert r_a["node_id"] in ann_a
        assert r_b["node_id"] not in ann_a

    def test_get_annotations_for_target_returns_all_types(self, store):
        r = _seed_node(store)
        for atype, val in [("consequence", "bad"), ("owner_facing", "true"),
                           ("liveness", '{"signal":"service"}')]:
            store.set_node_annotation(
                node_id=r["node_id"], annotation_type=atype, value=val,
                evidence="e", now=_T1,
            )
        ann = store.get_annotations_for_target(_TARGET_A)
        node_ann = ann[r["node_id"]]
        assert "consequence" in node_ann
        assert "owner_facing" in node_ann
        assert "liveness" in node_ann

    def test_unknown_node_id_returns_empty(self, store):
        assert store.get_node_annotations("nonexistent-node-id") == {}


# ---------------------------------------------------------------------------
# Loader integration
# ---------------------------------------------------------------------------

def _minimal_yaml(tmp_path: Path, *, extra_nodes="", extra_edges="") -> Path:
    """Write a minimal operational_graph.yml for testing."""
    content = textwrap.dedent(f"""
        version: "1"
        nodes:
          - id: repo:lesia
            target: /root/lesia
            liveness:
              signal: service
              detail: "lesia.service on port 7600"
              max_age_hours: unknown
              evidence: "systemctl: lesia.service active"
            consequence: "if down → no procurement intel"
            owner_facing: true
          - id: service:postgresql
            target: vps
            liveness:
              signal: service
              detail: "postgresql@16-main.service"
              max_age_hours: unknown
              evidence: "systemctl: postgresql@16-main.service active"
            consequence: "if down → HUMINT fails"
            owner_facing: false
        {extra_nodes}
        edges:
          - from:
              id: repo:lesia
              target: /root/lesia
            to:
              id: service:postgresql
              target: vps
            relationship: DEPENDS_ON
            description: "lesia uses a local Postgres database"
            evidence: "lesia/backend/config.py: database_url field"
            confidence: 0.9
        {extra_edges}
    """)
    yaml_path = tmp_path / "operational_graph.yml"
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


def _make_loader(tmp_path: Path, yaml_path: Path):
    """Return a callable that runs load() with the test YAML and DB."""

    db_path = str(tmp_path / "test.db")
    # Patch the module-level constants so the loader uses our temp files
    import scripts.load_operational_graph as loader_mod
    original_yaml = loader_mod._YAML_PATH
    original_db = loader_mod._DB_PATH
    loader_mod._YAML_PATH = yaml_path
    loader_mod._DB_PATH = db_path

    def run(dry_run=False):
        return loader_mod.load(dry_run=dry_run)

    yield run

    loader_mod._YAML_PATH = original_yaml
    loader_mod._DB_PATH = original_db


@pytest.fixture
def loader(tmp_path):
    yaml_path = _minimal_yaml(tmp_path)
    db_path = str(tmp_path / "test.db")

    import scripts.load_operational_graph as loader_mod
    orig_yaml = loader_mod._YAML_PATH
    orig_db = loader_mod._DB_PATH
    loader_mod._YAML_PATH = yaml_path
    loader_mod._DB_PATH = db_path

    yield loader_mod.load, db_path

    loader_mod._YAML_PATH = orig_yaml
    loader_mod._DB_PATH = orig_db


class TestLoader:
    def test_loader_returns_summary(self, loader):
        load, _ = loader
        summary = load()
        assert summary["nodes_declared"] == 2
        assert summary["edges_declared"] == 1
        assert summary["dry_run"] is False

    def test_loader_creates_node_stubs(self, loader):
        load, db_path = loader
        load()
        store = GraphStore(db_path)
        store.connect()
        nodes = store.get_active_nodes("/root/lesia")
        assert any(n["builder_node_id"] == "repo:lesia" for n in nodes)
        store.disconnect()

    def test_loader_sets_annotations(self, loader):
        load, db_path = loader
        load()
        store = GraphStore(db_path)
        store.connect()
        node_id = compute_node_id("/root/lesia", "repo:lesia")
        ann = store.get_node_annotations(node_id)
        assert "consequence" in ann
        assert ann["consequence"]["value"] == "if down → no procurement intel"
        assert "liveness" in ann
        liveness = json.loads(ann["liveness"]["value"])
        assert liveness["signal"] == "service"
        assert "owner_facing" in ann
        assert ann["owner_facing"]["value"] == "true"
        store.disconnect()

    def test_loader_creates_human_declared_edge(self, loader):
        load, db_path = loader
        load()
        store = GraphStore(db_path)
        store.connect()
        edges = store.get_active_edges("/root/lesia")
        assert len(edges) == 1
        assert edges[0]["collector_type"] == "human_declared"
        assert edges[0]["relationship"] == "DEPENDS_ON"
        assert abs(edges[0]["confidence"] - 0.9) < 0.01
        store.disconnect()

    def test_loader_idempotent_no_extra_events(self, loader):
        load, db_path = loader
        load()

        store = GraphStore(db_path)
        store.connect()
        node_id = compute_node_id("/root/lesia", "repo:lesia")
        history_after_first = store.get_node_history(node_id)
        store.disconnect()

        # second run with same YAML
        load()

        store = GraphStore(db_path)
        store.connect()
        history_after_second = store.get_node_history(node_id)
        # No new annotation_set events — values haven't changed
        ann_events_first = [e for e in history_after_first if e["event_type"] == "annotation_set"]
        ann_events_second = [e for e in history_after_second if e["event_type"] == "annotation_set"]
        assert len(ann_events_second) == len(ann_events_first)
        store.disconnect()

    def test_dry_run_no_db_writes(self, loader):
        load, db_path = loader
        summary = load(dry_run=True)
        assert summary["dry_run"] is True
        # DB should have no graph tables populated
        store = GraphStore(db_path)
        store.connect()
        assert store.count_nodes() == 0
        assert store.count_edges() == 0
        store.disconnect()

    def test_loader_consequence_counts(self, loader):
        load, _ = loader
        summary = load()
        # Both nodes have known consequences in the minimal YAML
        assert summary["nodes_consequence_known"] == 2
        assert summary["nodes_consequence_unknown"] == 0

    def test_vps_node_created_in_correct_target(self, loader):
        load, db_path = loader
        load()
        store = GraphStore(db_path)
        store.connect()
        vps_nodes = store.get_active_nodes("vps")
        assert any(n["builder_node_id"] == "service:postgresql" for n in vps_nodes)
        store.disconnect()

    def test_edge_evidence_contains_description(self, loader):
        load, db_path = loader
        load()
        store = GraphStore(db_path)
        store.connect()
        edges = store.get_active_edges("/root/lesia")
        assert len(edges) >= 1
        ev = edges[0]["evidence"]
        # evidence list should contain the human_declared detail and the description
        detail_texts = [e.get("detail", "") for e in ev if isinstance(e, dict)]
        combined = " ".join(detail_texts)
        assert "lesia/backend/config.py" in combined
        store.disconnect()


class TestLoaderUnknownFields:
    def test_unknown_consequence_in_yaml(self, tmp_path):
        yaml_content = textwrap.dedent("""
            version: "1"
            nodes:
              - id: repo:mystery
                target: /root/mystery
                consequence: unknown
                owner_facing: unknown
            edges: []
        """)
        yaml_path = tmp_path / "operational_graph.yml"
        yaml_path.write_text(yaml_content)
        db_path = str(tmp_path / "test.db")

        import scripts.load_operational_graph as loader_mod
        orig_yaml, orig_db = loader_mod._YAML_PATH, loader_mod._DB_PATH
        loader_mod._YAML_PATH = yaml_path
        loader_mod._DB_PATH = db_path
        try:
            summary = loader_mod.load()
        finally:
            loader_mod._YAML_PATH = orig_yaml
            loader_mod._DB_PATH = orig_db

        assert summary["nodes_consequence_unknown"] == 1
        assert summary["nodes_consequence_known"] == 0

        store = GraphStore(db_path)
        store.connect()
        node_id = compute_node_id("/root/mystery", "repo:mystery")
        ann = store.get_node_annotations(node_id)
        assert ann["consequence"]["value"] == "unknown"
        store.disconnect()

    def test_decommissioned_node_sets_status_annotation(self, tmp_path):
        """A node declaring decommissioned:true gets a 'status'=decommissioned annotation.

        This is the operator's way to declare that a node's down/absent state is
        intentional and EXPECTED, not a fault. Absence of the field (or false)
        leaves status untouched.
        """
        yaml_content = textwrap.dedent("""
            version: "1"
            nodes:
              - id: container:dead
                target: vps
                decommissioned:
                  value: 'true'
                  status: decommissioned
                  source: human_authored
                  provenance: human_authored
                  confirmed_at: '2026-06-08'
                  evidence: "reason: dead idea, intentionally stopped"
                consequence: "none — decommissioned"
                owner_facing: false
              - id: container:live
                target: vps
                consequence: "if down → something"
                owner_facing: true
            edges: []
        """)
        yaml_path = tmp_path / "operational_graph.yml"
        yaml_path.write_text(yaml_content)
        db_path = str(tmp_path / "test.db")

        import scripts.load_operational_graph as loader_mod
        orig_yaml, orig_db = loader_mod._YAML_PATH, loader_mod._DB_PATH
        loader_mod._YAML_PATH = yaml_path
        loader_mod._DB_PATH = db_path
        try:
            loader_mod.load()
        finally:
            loader_mod._YAML_PATH = orig_yaml
            loader_mod._DB_PATH = orig_db

        store = GraphStore(db_path)
        store.connect()
        dead = store.get_node_annotations(compute_node_id("vps", "container:dead"))
        assert dead["status"]["value"] == "decommissioned"
        assert "dead idea" in dead["status"]["evidence"]
        # A node that does not declare decommissioned has no 'status' annotation.
        live = store.get_node_annotations(compute_node_id("vps", "container:live"))
        assert "status" not in live
        store.disconnect()
