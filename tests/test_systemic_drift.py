"""Tests for cognition/systemic_drift.py — SystemicDriftEngine."""

from __future__ import annotations

from cognition.systemic_drift import (
    OperationalComplexityTrend,
    SystemicDriftAnalysis,
    SystemicDriftEngine,
)


def _snap(snap_id: int, created_at: str, packages=None, providers=None,
          rt_score=0.9, rt_status="healthy", recs=None, cost_obs=None):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "recommendations": recs or [],
            "cost_observations": cost_obs or [],
            "llm_detections": [{"provider": p} for p in (providers or [])],
            "scanner_results": {"results": {"repo_scanner": {"packages": packages or []}}},
            "runtime_health": {
                "health_score": rt_score,
                "overall_status": rt_status,
                "instability_signals": [],
            },
        },
    }


class TestSystemicDriftEngineBasic:
    def test_empty_returns_analysis(self):
        result = SystemicDriftEngine().analyze([])
        assert isinstance(result, SystemicDriftAnalysis)
        assert result.snapshot_count == 0

    def test_single_snapshot_returns_empty(self):
        snap = _snap(1, "2026-01-01T00:00:00")
        result = SystemicDriftEngine().analyze([snap])
        assert result.snapshot_count == 0

    def test_two_snapshots_returns_trends(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00"),
            _snap(2, "2026-01-08T00:00:00"),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        assert len(result.drift_trends) == 5

    def test_to_dict_structure(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        d = SystemicDriftEngine().analyze(snaps).to_dict()
        assert "drift_trends" in d
        assert "instability_indicators" in d
        assert "complexity_trend" in d
        assert "overall_drift_score" in d
        assert "significant_drift_count" in d
        assert "advisory" in d


class TestDriftTrends:
    def test_five_dimensions_covered(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        dimensions = {t.dimension for t in result.drift_trends}
        assert "orchestration_complexity" in dimensions
        assert "provider_diversity" in dimensions
        assert "runtime_stability" in dimensions
        assert "recommendation_volume" in dimensions
        assert "cost_severity" in dimensions

    def test_trend_to_dict(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        d = result.drift_trends[0].to_dict()
        assert "dimension" in d
        assert "direction" in d
        assert "early_score" in d
        assert "recent_score" in d
        assert "magnitude" in d
        assert "significant" in d

    def test_runtime_stability_decreasing_when_degraded(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", rt_score=0.9, rt_status="healthy"),
            _snap(2, "2026-01-08T00:00:00", rt_score=0.3, rt_status="critical"),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        rt_trend = next((t for t in result.drift_trends if t.dimension == "runtime_stability"), None)
        assert rt_trend is not None
        assert rt_trend.direction == "decreasing"

    def test_orchestration_complexity_increases_with_frameworks(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", packages=[]),
            _snap(2, "2026-01-08T00:00:00", packages=["langchain", "autogen", "crewai", "haystack"]),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        orch = next((t for t in result.drift_trends if t.dimension == "orchestration_complexity"), None)
        assert orch is not None
        assert orch.recent_score > orch.early_score


class TestSignificantDrift:
    def test_significant_flag_set_on_large_magnitude(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", rt_score=0.95),
            _snap(2, "2026-01-08T00:00:00", rt_score=0.30),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        rt_trend = next((t for t in result.drift_trends if t.dimension == "runtime_stability"), None)
        assert rt_trend is not None
        assert rt_trend.significant is True

    def test_significant_count_correct(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        actual_significant = sum(1 for t in result.drift_trends if t.significant)
        assert result.significant_drift_count == actual_significant


class TestInstabilityIndicators:
    def test_indicators_present(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        assert len(result.instability_indicators) > 0

    def test_indicator_to_dict(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        d = result.instability_indicators[0].to_dict()
        assert "name" in d
        assert "active" in d
        assert "score" in d

    def test_runtime_degradation_active_when_low_score(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", rt_score=0.95),
            _snap(2, "2026-01-08T00:00:00", rt_score=0.30),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        rt_indicator = next(
            (i for i in result.instability_indicators if i.name == "runtime_degradation"), None
        )
        assert rt_indicator is not None
        assert rt_indicator.active is True


class TestComplexityTrend:
    def test_complexity_trend_present(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = SystemicDriftEngine().analyze(snaps)
        assert isinstance(result.complexity_trend, OperationalComplexityTrend)

    def test_complexity_to_dict(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        d = SystemicDriftEngine().analyze(snaps).complexity_trend.to_dict()
        assert "current_score" in d
        assert "previous_score" in d
        assert "delta" in d
        assert "direction" in d

    def test_complexity_increases_with_frameworks(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", packages=[]),
            _snap(2, "2026-01-08T00:00:00", packages=["langchain", "autogen", "crewai", "haystack"]),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        assert result.complexity_trend.current_score >= result.complexity_trend.previous_score


class TestOverallDriftScore:
    def test_score_zero_for_no_drift(self):
        snap = _snap(1, "2026-01-01T00:00:00")
        snaps = [snap, snap]
        result = SystemicDriftEngine().analyze(snaps)
        assert result.overall_drift_score == 0.0

    def test_score_positive_for_drift(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00", rt_score=0.95),
            _snap(2, "2026-01-08T00:00:00", rt_score=0.30),
        ]
        result = SystemicDriftEngine().analyze(snaps)
        assert result.overall_drift_score > 0.0
