"""Tests for cognition/comparison.py — ComparisonEngine."""

from __future__ import annotations

from cognition.comparison import ComparisonEngine, SnapshotComparison


def _snap(snap_id: int, created_at: str, topo=None, workflows=None, rt=None, recs=None, cost=None):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "topology": topo or {},
            "workflows": workflows or [],
            "runtime_health": rt or {},
            "recommendations": recs or [],
            "cost_observations": cost or [],
        },
    }


def _rec(title: str, impact: str = "medium"):
    return {"title": title, "impact": impact, "category": "cost", "confidence": 0.7}


def _rt(score: float = 0.9, status: str = "healthy"):
    return {
        "health_score": score,
        "overall_status": status,
        "instability_signals": [],
        "failed_services": [],
    }


def _topo(node_ids: list, edges: list | None = None):
    nodes = [{"id": n, "label": n} for n in node_ids]
    return {"nodes": nodes, "edges": edges or []}


class TestComparisonEngine:
    def test_returns_snapshot_comparison(self):
        snap_a = _snap(1, "2026-01-01T00:00:00")
        snap_b = _snap(2, "2026-01-08T00:00:00")
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert isinstance(result, SnapshotComparison)

    def test_to_dict_structure(self):
        snap_a = _snap(1, "2026-01-01T00:00:00")
        snap_b = _snap(2, "2026-01-08T00:00:00")
        d = ComparisonEngine().compare(snap_a, snap_b).to_dict()
        assert "snapshot_a_id" in d
        assert "snapshot_b_id" in d
        assert "change_count" in d
        assert "overall_summary" in d
        assert "topology_delta" in d
        assert "workflow_delta" in d
        assert "runtime_delta" in d
        assert "recommendation_delta" in d
        assert "cost_delta" in d
        assert "severity_delta" in d

    def test_same_snapshots_zero_changes(self):
        topo = _topo(["agent_a", "agent_b"])
        snap = _snap(1, "2026-01-01T00:00:00", topo=topo)
        result = ComparisonEngine().compare(snap, snap)
        assert result.topology_delta.nodes_added == []
        assert result.topology_delta.nodes_removed == []


class TestTopologyDelta:
    def test_nodes_added(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", topo=_topo(["a", "b"]))
        snap_b = _snap(2, "2026-01-08T00:00:00", topo=_topo(["a", "b", "c"]))
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert "c" in result.topology_delta.nodes_added

    def test_nodes_removed(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", topo=_topo(["a", "b", "c"]))
        snap_b = _snap(2, "2026-01-08T00:00:00", topo=_topo(["a", "b"]))
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert "c" in result.topology_delta.nodes_removed

    def test_has_changes_property(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", topo=_topo(["a"]))
        snap_b = _snap(2, "2026-01-08T00:00:00", topo=_topo(["a", "b"]))
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert result.topology_delta.has_changes is True


class TestRecommendationDelta:
    def test_new_recommendations(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", recs=[_rec("old rec")])
        snap_b = _snap(2, "2026-01-08T00:00:00", recs=[_rec("old rec"), _rec("new rec")])
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert "new rec" in result.recommendation_delta.new_recommendations

    def test_resolved_recommendations(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", recs=[_rec("old rec"), _rec("gone rec")])
        snap_b = _snap(2, "2026-01-08T00:00:00", recs=[_rec("old rec")])
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert "gone rec" in result.recommendation_delta.resolved_recommendations

    def test_persisting_recommendations(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", recs=[_rec("same rec")])
        snap_b = _snap(2, "2026-01-08T00:00:00", recs=[_rec("same rec")])
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert "same rec" in result.recommendation_delta.persisting_recommendations


class TestRuntimeDelta:
    def test_status_changed(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", rt=_rt(0.9, "healthy"))
        snap_b = _snap(2, "2026-01-08T00:00:00", rt=_rt(0.4, "degraded"))
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert result.runtime_delta.status_changed is True
        assert result.runtime_delta.degraded is True

    def test_no_change(self):
        snap_a = _snap(1, "2026-01-01T00:00:00", rt=_rt(0.9, "healthy"))
        snap_b = _snap(2, "2026-01-08T00:00:00", rt=_rt(0.9, "healthy"))
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert result.runtime_delta.status_changed is False


class TestSeverityDelta:
    def test_escalation_detected(self):
        snap_a = _snap(1, "2026-01-01T00:00:00")
        snap_b = _snap(2, "2026-01-08T00:00:00",
                       recs=[_rec("r1", "high"), _rec("r2", "high"), _rec("r3", "high")])
        result = ComparisonEngine().compare(snap_a, snap_b)
        d = result.to_dict()
        assert "severity_delta" in d
        assert "level_a" in d["severity_delta"]
        assert "level_b" in d["severity_delta"]


class TestChangeCount:
    def test_change_count_increments(self):
        snap_a = _snap(1, "2026-01-01T00:00:00",
                       topo=_topo(["a"]),
                       recs=[_rec("old")])
        snap_b = _snap(2, "2026-01-08T00:00:00",
                       topo=_topo(["a", "b"]),
                       recs=[_rec("new")])
        result = ComparisonEngine().compare(snap_a, snap_b)
        assert result.change_count > 0
