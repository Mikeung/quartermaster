"""Tests for cognition/investigation.py — InvestigationEngine."""

from __future__ import annotations

from cognition.investigation import VALID_KINDS, InvestigationEngine, InvestigationResult


def _make_snap(snap_id: int, created_at: str, recs=None, workflows=None, rt=None, cost_obs=None):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "recommendations": recs or [],
            "workflows": workflows or [],
            "runtime_health": rt or {},
            "cost_observations": cost_obs or [],
        },
    }


def _rec(title: str, category: str = "cost", impact: str = "high", confidence: float = 0.8):
    return {
        "title": title,
        "category": category,
        "impact": impact,
        "confidence": confidence,
        "urgency": "review",
        "evidence": [f"Evidence for {title}"],
        "suggested_investigation": f"Investigate {title}",
    }


def _workflow(name: str, wf_type: str = "cost_management", confidence: float = 0.7):
    return {
        "name": name,
        "workflow_type": wf_type,
        "confidence": confidence,
        "evidence": [f"workflow evidence: {name}"],
    }


def _rt(score: float = 0.5, status: str = "degraded"):
    return {
        "health_score": score,
        "overall_status": status,
        "instability_signals": ["high CPU"],
        "resource_pressure": [],
        "failed_services": [],
    }


SNAP_OLD = _make_snap(
    1, "2026-01-01T00:00:00",
    recs=[_rec("old rec", impact="low", confidence=0.3)],
    rt=_rt(0.8, "healthy"),
)
SNAP_NEW = _make_snap(
    2, "2026-01-08T00:00:00",
    recs=[_rec("new rec", impact="high"), _rec("another rec", impact="high")],
    rt=_rt(0.3, "degraded"),
)


class TestValidKinds:
    def test_valid_kinds_set(self):
        assert "recent_changes" in VALID_KINDS
        assert "severity_increase" in VALID_KINDS
        assert "recommendation_evidence" in VALID_KINDS
        assert "workflow_instability" in VALID_KINDS
        assert "component_involvement" in VALID_KINDS
        assert "concern_contribution" in VALID_KINDS
        assert len(VALID_KINDS) == 6


class TestInvestigationResult:
    def test_to_dict_structure(self):
        engine = InvestigationEngine()
        result = engine.investigate("recent_changes", [SNAP_OLD, SNAP_NEW])
        d = result.to_dict()
        assert "kind" in d
        assert "summary" in d
        assert "evidence_chain" in d
        assert "confidence" in d
        assert "uncertainty_notes" in d
        assert "investigated_at" in d
        assert isinstance(d["evidence_chain"], list)

    def test_result_is_investigation_result(self):
        engine = InvestigationEngine()
        result = engine.investigate("recent_changes", [SNAP_OLD, SNAP_NEW])
        assert isinstance(result, InvestigationResult)


class TestRecentChanges:
    def test_returns_result(self):
        engine = InvestigationEngine()
        result = engine.investigate("recent_changes", [SNAP_OLD, SNAP_NEW])
        assert result.kind == "recent_changes"
        assert len(result.evidence_chain) > 0

    def test_single_snapshot(self):
        engine = InvestigationEngine()
        result = engine.investigate("recent_changes", [SNAP_OLD])
        assert result.kind == "recent_changes"
        assert result.confidence >= 0.0

    def test_empty_snapshots(self):
        engine = InvestigationEngine()
        result = engine.investigate("recent_changes", [])
        assert result.kind == "recent_changes"
        assert result.confidence == 0.0


class TestSeverityIncrease:
    def test_detects_increase(self):
        engine = InvestigationEngine()
        result = engine.investigate("severity_increase", [SNAP_OLD, SNAP_NEW])
        assert result.kind == "severity_increase"
        assert len(result.evidence_chain) > 0

    def test_insufficient_snapshots(self):
        engine = InvestigationEngine()
        result = engine.investigate("severity_increase", [SNAP_OLD])
        assert "insufficient" in result.summary.lower() or result.confidence == 0.0


class TestRecommendationEvidence:
    def test_finds_by_title(self):
        engine = InvestigationEngine()
        result = engine.investigate(
            "recommendation_evidence",
            [SNAP_NEW],
            context={"title": "new rec"},
        )
        assert result.kind == "recommendation_evidence"
        assert len(result.evidence_chain) > 0

    def test_no_title_falls_back(self):
        engine = InvestigationEngine()
        result = engine.investigate("recommendation_evidence", [SNAP_NEW])
        assert result.kind == "recommendation_evidence"

    def test_no_snapshot(self):
        engine = InvestigationEngine()
        result = engine.investigate("recommendation_evidence", [])
        assert result.confidence == 0.0


class TestWorkflowInstability:
    def test_with_workflow_type(self):
        snap = _make_snap(3, "2026-01-01T00:00:00", workflows=[_workflow("w1"), _workflow("w2")])
        snaps = [snap] * 3
        engine = InvestigationEngine()
        result = engine.investigate(
            "workflow_instability",
            snaps,
            context={"workflow_type": "cost_management"},
        )
        assert result.kind == "workflow_instability"

    def test_no_workflows(self):
        engine = InvestigationEngine()
        result = engine.investigate("workflow_instability", [SNAP_OLD])
        assert result.kind == "workflow_instability"


class TestComponentInvolvement:
    def test_with_repeated_recs(self):
        snaps = [SNAP_OLD, SNAP_NEW, SNAP_NEW]
        engine = InvestigationEngine()
        result = engine.investigate("component_involvement", snaps)
        assert result.kind == "component_involvement"

    def test_single_snap(self):
        engine = InvestigationEngine()
        result = engine.investigate("component_involvement", [SNAP_OLD])
        assert result.kind == "component_involvement"


class TestConcernContribution:
    def test_with_data(self):
        engine = InvestigationEngine()
        result = engine.investigate("concern_contribution", [SNAP_NEW])
        assert result.kind == "concern_contribution"
        assert len(result.evidence_chain) > 0

    def test_empty(self):
        engine = InvestigationEngine()
        result = engine.investigate("concern_contribution", [])
        assert result.confidence == 0.0


class TestInvalidKind:
    def test_invalid_kind(self):
        engine = InvestigationEngine()
        result = engine.investigate("not_a_real_kind", [SNAP_OLD])
        assert result.confidence == 0.0
        assert "unknown" in result.kind.lower() or result.kind == "not_a_real_kind"
