"""Tests for cognition/clustering.py — ConcernClusteringEngine."""

from __future__ import annotations

from cognition.clustering import ConcernCluster, ConcernClusteringEngine


def _rec(title: str, category: str = "cost", impact: str = "high"):
    return {"title": title, "category": category, "impact": impact,
            "confidence": 0.8, "urgency": "review",
            "evidence": [f"evidence for {title}"], "suggested_investigation": ""}


def _pattern(name: str, matched: bool = True):
    return {"name": name, "matched": matched, "matching_evidence": [],
            "severity_hint": "moderate", "description": ""}


def _rt(score: float = 0.9, status: str = "healthy"):
    return {"health_score": score, "overall_status": status,
            "instability_signals": [], "failed_services": [], "resource_pressure": []}


class TestClusteringEngineBasic:
    def test_returns_5_clusters(self):
        clusters = ConcernClusteringEngine().cluster([])
        assert len(clusters) == 5

    def test_all_are_concern_clusters(self):
        clusters = ConcernClusteringEngine().cluster([])
        assert all(isinstance(c, ConcernCluster) for c in clusters)

    def test_sorted_by_score_desc(self):
        clusters = ConcernClusteringEngine().cluster([])
        scores = [c.cluster_score for c in clusters]
        assert scores == sorted(scores, reverse=True)

    def test_to_dict_structure(self):
        clusters = ConcernClusteringEngine().cluster([])
        d = clusters[0].to_dict()
        assert "name" in d
        assert "label" in d
        assert "cluster_score" in d
        assert "active" in d
        assert "note" in d

    def test_empty_inputs_all_inactive(self):
        clusters = ConcernClusteringEngine().cluster([])
        assert all(not c.active for c in clusters)


class TestHighCostLLMProcessingCluster:
    def test_activates_with_cost_patterns(self):
        patterns = [
            _pattern("retry_amplification"),
            _pattern("ocr_token_amplification"),
        ]
        recs = [_rec("Enable token tracking")]
        clusters = ConcernClusteringEngine().cluster(recs, patterns=patterns)
        cluster = next((c for c in clusters if c.name == "high_cost_llm_processing"), None)
        assert cluster is not None
        assert cluster.active is True

    def test_member_patterns_populated(self):
        patterns = [_pattern("retry_amplification")]
        clusters = ConcernClusteringEngine().cluster([], patterns=patterns)
        cluster = next((c for c in clusters if c.name == "high_cost_llm_processing"), None)
        assert cluster is not None
        assert "retry_amplification" in cluster.member_patterns


class TestUnstableOrchestrationCluster:
    def test_activates_with_orch_patterns_and_workflow(self):
        patterns = [
            _pattern("framework_stacking"),
            _pattern("orchestration_sprawl"),
        ]
        workflows = [{"workflow_type": "multi_agent_orchestration", "name": "orchestrator"}]
        clusters = ConcernClusteringEngine().cluster([], patterns=patterns, workflows=workflows)
        cluster = next((c for c in clusters if c.name == "unstable_orchestration"), None)
        assert cluster is not None
        assert cluster.active is True

    def test_member_workflows_populated(self):
        workflows = [{"workflow_type": "multi_agent_orchestration", "name": "agent"}]
        clusters = ConcernClusteringEngine().cluster([], workflows=workflows)
        cluster = next((c for c in clusters if c.name == "unstable_orchestration"), None)
        assert cluster is not None
        assert "multi_agent_orchestration" in cluster.member_workflows


class TestProviderRiskCluster:
    def test_activates_with_provider_pattern(self):
        patterns = [
            _pattern("single_provider_dependency"),
            _pattern("volatile_provider_switching"),
        ]
        clusters = ConcernClusteringEngine().cluster([], patterns=patterns)
        cluster = next((c for c in clusters if c.name == "provider_risk"), None)
        assert cluster is not None
        assert cluster.active is True


class TestRuntimeDegradationCluster:
    def test_activates_with_degraded_runtime(self):
        rt = _rt(0.3, "critical")
        rt["failed_services"] = ["svc1", "svc2", "svc3"]
        clusters = ConcernClusteringEngine().cluster([], runtime_health=rt)
        cluster = next((c for c in clusters if c.name == "runtime_degradation"), None)
        assert cluster is not None
        assert cluster.active is True

    def test_member_runtime_signals_populated(self):
        rt = _rt(0.3, "critical")
        rt["instability_signals"] = ["high CPU", "swap pressure"]
        clusters = ConcernClusteringEngine().cluster([], runtime_health=rt)
        cluster = next((c for c in clusters if c.name == "runtime_degradation"), None)
        assert cluster is not None
        assert len(cluster.member_runtime_signals) > 0


class TestActiveOnly:
    def test_active_only_filters(self):
        engine = ConcernClusteringEngine()
        patterns = [_pattern("retry_amplification")]
        recs = [_rec("track costs")]
        clusters = engine.cluster(recs, patterns=patterns)
        active = engine.active_only(clusters)
        assert all(c.active for c in active)
        assert len(active) <= len(clusters)


class TestClusterNote:
    def test_note_preserves_advisory_language(self):
        clusters = ConcernClusteringEngine().cluster([])
        for c in clusters:
            d = c.to_dict()
            assert "organizational aids" in d["note"].lower() or "causal" in d["note"].lower()
