"""Tests for reports/evidence_trace.py — EvidenceTracer."""

from __future__ import annotations

from reports.evidence_trace import EvidenceNode, EvidenceTracer, EvidenceTree


def _rec(title: str, category: str = "cost", impact: str = "high"):
    return {
        "title": title,
        "category": category,
        "impact": impact,
        "confidence": 0.75,
        "urgency": "review",
        "evidence": ["evidence item 1", "evidence item 2"],
        "suggested_investigation": "Check the thing",
    }


def _snap(snap_id: int = 1, rt_status: str = "healthy"):
    return {
        "id": snap_id,
        "created_at": "2026-01-01T12:00:00",
        "data": {
            "recommendations": [_rec("test rec")],
            "workflows": [
                {
                    "name": "cost workflow",
                    "workflow_type": "cost_management",
                    "confidence": 0.7,
                    "evidence": ["cost evidence"],
                }
            ],
            "cost_observations": [
                {"severity": "high", "observation": "cost issue related to cost category"},
            ],
            "runtime_health": {
                "overall_status": rt_status,
                "health_score": 0.7,
                "instability_signals": ["signal 1"],
                "resource_pressure": [],
            },
        },
    }


def _severity(level: str = "moderate", score: float = 0.45):
    return {
        "level": level,
        "score": score,
        "evidence": ["severity evidence 1"],
        "factors": [
            {
                "name": "recommendation_signal",
                "contribution": 0.20,
                "description": "recs present",
                "weight": 0.25,
                "raw_value": 0.8,
            },
            {
                "name": "runtime_instability",
                "contribution": 0.10,
                "description": "runtime degraded",
                "weight": 0.30,
                "raw_value": 0.33,
            },
        ],
        "confidence": 0.7,
    }


class TestEvidenceNodeStructure:
    def test_to_dict(self):
        node = EvidenceNode(kind="recommendation", label="test", evidence=["ev"], snapshot_id=1)
        d = node.to_dict()
        assert d["kind"] == "recommendation"
        assert d["label"] == "test"
        assert d["evidence"] == ["ev"]
        assert d["snapshot_id"] == 1
        assert d["children"] == []

    def test_children_serialized(self):
        child = EvidenceNode(kind="observation", label="child", evidence=[], snapshot_id=1)
        parent = EvidenceNode(kind="factor", label="parent", evidence=[], snapshot_id=1, children=[child])
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["kind"] == "observation"


class TestEvidenceTreeStructure:
    def test_to_dict(self):
        root = EvidenceNode(kind="recommendation", label="root", evidence=[], snapshot_id=1)
        tree = EvidenceTree(root=root, depth=2, node_count=1, generated_at="2026-01-01")
        d = tree.to_dict()
        assert "root" in d
        assert d["depth"] == 2
        assert d["node_count"] == 1
        assert d["generated_at"] == "2026-01-01"


class TestTraceRecommendation:
    def test_returns_evidence_tree(self):
        snap = _snap()
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        assert isinstance(tree, EvidenceTree)

    def test_root_is_recommendation(self):
        snap = _snap()
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        assert tree.root.kind == "recommendation"
        assert "test rec" in tree.root.label

    def test_root_evidence_contains_category(self):
        snap = _snap()
        rec = _rec("test rec", category="cost")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        assert any("cost" in e.lower() for e in tree.root.evidence)

    def test_snapshot_anchor_child(self):
        snap = _snap(42)
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        snap_children = [c for c in tree.root.children if c.kind == "snapshot"]
        assert len(snap_children) == 1
        assert "42" in snap_children[0].label

    def test_observation_child_present(self):
        snap = _snap()
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        obs_children = [c for c in tree.root.children if c.kind == "observation"]
        assert len(obs_children) >= 1

    def test_unhealthy_runtime_adds_runtime_child(self):
        snap = _snap(rt_status="degraded")
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        rt_children = [c for c in tree.root.children if c.kind == "runtime"]
        assert len(rt_children) >= 1

    def test_node_count_positive(self):
        snap = _snap()
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        assert tree.node_count >= 2

    def test_to_dict_complete(self):
        snap = _snap()
        rec = _rec("test rec")
        d = EvidenceTracer().trace_recommendation(rec, snap).to_dict()
        assert "root" in d
        assert "depth" in d
        assert "node_count" in d
        assert "generated_at" in d


class TestTraceSeverity:
    def test_returns_evidence_tree(self):
        snap = _snap()
        sev = _severity()
        tree = EvidenceTracer().trace_severity(sev, snap)
        assert isinstance(tree, EvidenceTree)

    def test_root_is_observation(self):
        snap = _snap()
        sev = _severity("moderate", 0.45)
        tree = EvidenceTracer().trace_severity(sev, snap)
        assert tree.root.kind == "observation"
        assert "moderate" in tree.root.label.lower()

    def test_factor_nodes_added(self):
        snap = _snap()
        sev = _severity()
        tree = EvidenceTracer().trace_severity(sev, snap)
        factor_children = [c for c in tree.root.children if c.kind == "factor"]
        assert len(factor_children) >= 1

    def test_snapshot_anchor(self):
        snap = _snap(7)
        sev = _severity()
        tree = EvidenceTracer().trace_severity(sev, snap)
        snap_children = [c for c in tree.root.children if c.kind == "snapshot"]
        assert len(snap_children) == 1

    def test_with_temporal(self):
        snap = _snap()
        sev = _severity()
        temporal = {"volatility_score": 0.6, "total_changes": 5, "churn_indicators": ["churn 1"]}
        tree = EvidenceTracer().trace_severity(sev, snap, temporal=temporal)
        assert isinstance(tree, EvidenceTree)


class TestToMarkdown:
    def test_renders_markdown(self):
        snap = _snap()
        rec = _rec("test rec")
        tree = EvidenceTracer().trace_recommendation(rec, snap)
        md = EvidenceTracer().to_markdown(tree)
        assert "# Evidence Trace" in md
        assert "Advisory only" in md
        assert "RECOMMENDATION" in md
