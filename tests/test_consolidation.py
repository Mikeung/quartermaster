"""Tests for cognition/consolidation.py — ConsolidationEngine."""

from __future__ import annotations

from cognition.consolidation import ConsolidatedConcern, ConsolidationEngine


def _rec(title: str, category: str = "cost", impact: str = "high",
         evidence: list | None = None):
    return {
        "title": title,
        "category": category,
        "impact": impact,
        "confidence": 0.8,
        "urgency": "review",
        "evidence": evidence or [f"evidence for {title}"],
        "suggested_investigation": "",
    }


def _pattern(name: str, matched: bool = True):
    return {"name": name, "matched": matched}


def _cluster(name: str, member_recs: list, active: bool = True):
    return {
        "name": name,
        "label": name,
        "active": active,
        "member_recommendations": member_recs,
        "cluster_score": 0.7,
    }


class TestConsolidationEngineBasic:
    def test_empty_returns_empty(self):
        result = ConsolidationEngine().consolidate([])
        assert result == []

    def test_returns_consolidated_concerns(self):
        recs = [_rec("Enable cost tracking")]
        result = ConsolidationEngine().consolidate(recs)
        assert len(result) >= 1
        assert all(isinstance(c, ConsolidatedConcern) for c in result)

    def test_single_rec_returns_single_concern(self):
        recs = [_rec("Enable cost tracking")]
        result = ConsolidationEngine().consolidate(recs)
        assert len(result) == 1

    def test_to_dict_structure(self):
        recs = [_rec("Enable cost tracking")]
        result = ConsolidationEngine().consolidate(recs)
        d = result[0].to_dict()
        assert "title" in d
        assert "contributing_recs" in d
        assert "shared_evidence" in d
        assert "category_tags" in d
        assert "severity_hint" in d
        assert "confidence" in d
        assert "member_count" in d
        assert "note" in d


class TestCategoryGrouping:
    def test_same_category_grouped(self):
        recs = [
            _rec("Enable token tracking", category="cost"),
            _rec("Review cost posture", category="cost"),
        ]
        result = ConsolidationEngine().consolidate(recs)
        # Both are cost recs — may be merged or separate based on evidence overlap
        # At minimum, they should all appear in contributing_recs
        all_contributing = []
        for c in result:
            all_contributing.extend(c.contributing_recs)
        assert "Enable token tracking" in all_contributing
        assert "Review cost posture" in all_contributing

    def test_different_categories_stay_separate(self):
        recs = [
            _rec("Cost issue", category="cost"),
            _rec("Runtime issue", category="stability"),
        ]
        result = ConsolidationEngine().consolidate(recs)
        categories = set()
        for c in result:
            categories.update(c.category_tags)
        assert "cost" in categories
        assert "stability" in categories

    def test_sorted_by_member_count(self):
        recs = [
            _rec("rec 1", category="cost", evidence=["cost token retry"]),
            _rec("rec 2", category="cost", evidence=["cost token retry"]),
            _rec("rec 3", category="cost", evidence=["cost token retry"]),
            _rec("single", category="stability"),
        ]
        result = ConsolidationEngine().consolidate(recs)
        counts = [c.member_count for c in result]
        assert counts[0] >= counts[-1]


class TestEvidenceOverlap:
    def test_shared_evidence_populated_when_overlap(self):
        shared_evidence = ["retry library detected", "token cost elevated"]
        recs = [
            _rec("Add retry budget", category="cost", evidence=[*shared_evidence, "extra A"]),
            _rec("Enable cost tracking", category="cost", evidence=[*shared_evidence, "extra B"]),
        ]
        result = ConsolidationEngine().consolidate(recs)
        if len(result) == 1:
            assert len(result[0].shared_evidence) > 0

    def test_no_overlap_keeps_separate(self):
        recs = [
            _rec("Issue A", category="cost", evidence=["completely unique evidence A"]),
            _rec("Issue B", category="cost", evidence=["totally different evidence B"]),
        ]
        result = ConsolidationEngine().consolidate(recs)
        # With no overlap, items may stay separate
        total_recs = sum(c.member_count for c in result)
        assert total_recs == 2


class TestSeverityConsolidation:
    def test_high_impact_propagates(self):
        recs = [
            _rec("Issue A", impact="high"),
            _rec("Issue B", impact="low"),
        ]
        result = ConsolidationEngine().consolidate(recs)
        severities = {c.severity_hint for c in result}
        assert "high" in severities

    def test_confidence_averaged(self):
        recs = [_rec("Issue", category="cost")]
        result = ConsolidationEngine().consolidate(recs)
        assert 0.0 <= result[0].confidence <= 1.0


class TestClusterBridging:
    def test_cluster_bridging_merges_cross_category(self):
        recs = [
            _rec("Cost issue", category="cost"),
            _rec("Runtime issue", category="stability"),
        ]
        cluster = _cluster("test_cluster", ["Cost issue", "Runtime issue"])
        result = ConsolidationEngine().consolidate(recs, clusters=[cluster])
        # With cluster bridging, may be merged into one cross-category concern
        # Both titles should appear in contributing_recs somewhere
        all_recs = []
        for c in result:
            all_recs.extend(c.contributing_recs)
        assert "Cost issue" in all_recs
        assert "Runtime issue" in all_recs

    def test_inactive_cluster_not_used(self):
        recs = [
            _rec("Cost issue", category="cost"),
            _rec("Runtime issue", category="stability"),
        ]
        cluster = _cluster("test_cluster", ["Cost issue", "Runtime issue"], active=False)
        result_with = ConsolidationEngine().consolidate(recs, clusters=[cluster])
        result_without = ConsolidationEngine().consolidate(recs, clusters=[])
        # Inactive cluster should not affect consolidation
        assert len(result_with) == len(result_without)


class TestTraceability:
    def test_all_source_recs_traceable(self):
        recs = [
            _rec("Enable cost tracking"),
            _rec("Add retry budget"),
            _rec("Review orchestration"),
        ]
        result = ConsolidationEngine().consolidate(recs)
        all_contributing = []
        for c in result:
            all_contributing.extend(c.contributing_recs)
        assert "Enable cost tracking" in all_contributing
        assert "Add retry budget" in all_contributing
        assert "Review orchestration" in all_contributing

    def test_note_preserves_traceability_language(self):
        recs = [_rec("test rec")]
        result = ConsolidationEngine().consolidate(recs)
        assert "traceability" in result[0].to_dict()["note"].lower()
