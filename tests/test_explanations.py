"""Tests for reports/explanations.py — ExplanationGenerator."""

from __future__ import annotations

from reports.explanations import Explanation, ExplanationGenerator


def _severity(level: str = "high", score: float = 0.7, factors=None):
    return {
        "level": level,
        "score": score,
        "confidence": 0.8,
        "evidence": ["sev evidence"],
        "factors": factors or [
            {"name": "recommendation_signal", "contribution": 0.25, "description": "recs", "weight": 0.25, "raw_value": 1.0},
            {"name": "runtime_instability", "contribution": 0.20, "description": "runtime", "weight": 0.30, "raw_value": 0.67},
        ],
    }


def _rec(title: str = "test rec", category: str = "cost", impact: str = "high", confidence: float = 0.8):
    return {
        "title": title,
        "category": category,
        "impact": impact,
        "confidence": confidence,
        "urgency": "review",
        "evidence": ["rec evidence 1"],
        "suggested_investigation": "investigate this",
    }


def _pattern(name: str = "retry_amplification", matched: bool = True, severity_hint: str = "high"):
    return {
        "name": name,
        "matched": matched,
        "matching_evidence": ["evidence 1", "evidence 2"],
        "operational_impact": "impacts ops",
        "mitigation_guidance": "do something",
        "severity_hint": severity_hint,
        "confidence_notes": "structural match",
    }


def _comparison(snap_a_id: int = 1, snap_b_id: int = 2, change_count: int = 3):
    return {
        "snapshot_a_id": snap_a_id,
        "snapshot_b_id": snap_b_id,
        "change_count": change_count,
        "overall_summary": "Some changes detected.",
        "topology_delta": {"nodes_added": ["c"], "nodes_removed": []},
        "workflow_delta": {"workflows_added": [], "workflows_removed": []},
        "runtime_delta": {"status_changed": False, "health_score_delta": 0.0, "new_instability_signals": []},
        "recommendation_delta": {"new_recommendations": ["new rec"], "persisting_recommendations": [], "resolved_recommendations": []},
        "severity_delta": {"level_changed": True, "escalated": True, "level_a": "low", "level_b": "high", "contributing_factors": ["recs increased"]},
        "cost_delta": {"new_cost_concerns": [], "resolved_cost_concerns": []},
    }


class TestExplanationStructure:
    def test_is_explanation_instance(self):
        gen = ExplanationGenerator()
        exp = gen.explain_severity(_severity())
        assert isinstance(exp, Explanation)

    def test_to_dict_keys(self):
        gen = ExplanationGenerator()
        d = gen.explain_severity(_severity()).to_dict()
        assert "title" in d
        assert "what_changed" in d
        assert "what_contributed" in d
        assert "why_it_matters" in d
        assert "uncertainty_notes" in d
        assert "confidence" in d
        assert "language" in d

    def test_language_always_bounded(self):
        gen = ExplanationGenerator()
        d = gen.explain_severity(_severity()).to_dict()
        assert d["language"] == "bounded"


class TestExplainSeverity:
    def test_title_includes_level(self):
        gen = ExplanationGenerator()
        exp = gen.explain_severity(_severity("moderate", 0.45))
        assert "moderate" in exp.title.lower()

    def test_factors_in_what_contributed(self):
        gen = ExplanationGenerator()
        exp = gen.explain_severity(_severity())
        assert len(exp.what_contributed) > 0
        # Each factor with contribution > 0.01 should appear
        assert any("recommendation_signal" in c for c in exp.what_contributed)

    def test_temporal_high_volatility_in_what_changed(self):
        gen = ExplanationGenerator()
        temporal = {"volatility_score": 0.55, "total_changes": 8, "churn_indicators": ["churn A"]}
        exp = gen.explain_severity(_severity(), temporal=temporal)
        assert len(exp.what_changed) > 0
        assert any("volatility" in c.lower() for c in exp.what_changed)

    def test_recurrence_in_what_changed(self):
        gen = ExplanationGenerator()
        recurrence = [
            {"pattern": "Service failing", "occurrences": 4},
            {"pattern": "Another issue", "occurrences": 3},
            {"pattern": "Third issue", "occurrences": 3},
        ]
        exp = gen.explain_severity(_severity(), recurrence=recurrence)
        assert any("3+" in c or "structural" in c.lower() for c in exp.what_changed)

    def test_uncertainty_notes_present(self):
        gen = ExplanationGenerator()
        exp = gen.explain_severity(_severity())
        assert len(exp.uncertainty_notes) >= 2

    def test_confidence_matches_severity(self):
        gen = ExplanationGenerator()
        exp = gen.explain_severity(_severity(score=0.7))
        assert 0.0 <= exp.confidence <= 1.0

    def test_all_severity_levels(self):
        gen = ExplanationGenerator()
        for level in ("informational", "low", "moderate", "high", "critical"):
            exp = gen.explain_severity(_severity(level=level, score=0.5))
            assert level in exp.title.lower()
            assert len(exp.why_it_matters) > 10


class TestExplainRecommendation:
    def test_title_contains_rec_title(self):
        gen = ExplanationGenerator()
        exp = gen.explain_recommendation(_rec("test rec"))
        assert "test rec" in exp.title

    def test_evidence_in_what_contributed(self):
        gen = ExplanationGenerator()
        exp = gen.explain_recommendation(_rec())
        assert "rec evidence 1" in exp.what_contributed

    def test_why_includes_category(self):
        gen = ExplanationGenerator()
        exp = gen.explain_recommendation(_rec(category="cost"))
        assert "cost" in exp.why_it_matters.lower()

    def test_uncertainty_notes_present(self):
        gen = ExplanationGenerator()
        exp = gen.explain_recommendation(_rec())
        assert len(exp.uncertainty_notes) >= 2

    def test_snapshot_context_adds_workflow(self):
        gen = ExplanationGenerator()
        snap = {
            "id": 1,
            "data": {
                "workflows": [{"name": "cost_wf", "workflow_type": "cost_management", "evidence": ["cost evidence"]}]
            }
        }
        exp = gen.explain_recommendation(_rec(category="cost"), context_snapshot=snap)
        assert any("workflow" in c.lower() for c in exp.what_changed)


class TestExplainPattern:
    def test_matched_pattern(self):
        gen = ExplanationGenerator()
        exp = gen.explain_pattern(_pattern(matched=True))
        assert "retry_amplification" in exp.title.lower()
        assert len(exp.what_contributed) > 0

    def test_unmatched_pattern(self):
        gen = ExplanationGenerator()
        exp = gen.explain_pattern(_pattern(matched=False))
        assert "not matched" in exp.title.lower()
        assert exp.confidence == 0.0

    def test_why_it_matters_has_impact(self):
        gen = ExplanationGenerator()
        exp = gen.explain_pattern(_pattern(matched=True))
        assert "impacts ops" in exp.why_it_matters


class TestExplainComparison:
    def test_title_has_snapshot_ids(self):
        gen = ExplanationGenerator()
        exp = gen.explain_comparison(_comparison(1, 2))
        assert "1" in exp.title
        assert "2" in exp.title

    def test_what_changed_has_topology(self):
        gen = ExplanationGenerator()
        exp = gen.explain_comparison(_comparison())
        assert any("c" in c.lower() for c in exp.what_changed)

    def test_what_contributed_has_new_recs(self):
        gen = ExplanationGenerator()
        exp = gen.explain_comparison(_comparison())
        assert any("new rec" in c.lower() for c in exp.what_contributed)

    def test_why_it_matters_has_change_count(self):
        gen = ExplanationGenerator()
        exp = gen.explain_comparison(_comparison(change_count=5))
        assert "5" in exp.why_it_matters

    def test_confidence_scales_with_changes(self):
        gen = ExplanationGenerator()
        exp_low = gen.explain_comparison(_comparison(change_count=1))
        exp_high = gen.explain_comparison(_comparison(change_count=10))
        assert exp_high.confidence > exp_low.confidence

    def test_uncertainty_notes_present(self):
        gen = ExplanationGenerator()
        exp = gen.explain_comparison(_comparison())
        assert len(exp.uncertainty_notes) >= 1
