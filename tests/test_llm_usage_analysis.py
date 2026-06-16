"""Tests for llm_intelligence/usage_analysis.py — usage analysis engine."""

from __future__ import annotations

from llm_intelligence.usage_analysis import (
    UsageAnalysisEngine,
    _compute_trend_direction,
)


def _make_provider_row(**overrides) -> dict:
    base = {
        "provider": "anthropic",
        "event_count": 100,
        "total_tokens": 50000,
        "prompt_tokens": 35000,
        "completion_tokens": 15000,
        "avg_latency_ms": 2000.0,
        "max_latency_ms": 8000.0,
        "error_count": 2,
        "total_estimated_cost": 0.15,
    }
    base.update(overrides)
    return base


def _make_workflow_row(**overrides) -> dict:
    base = {
        "workflow": "doc-processing",
        "event_count": 50,
        "total_tokens": 30000,
        "prompt_tokens": 22000,
        "completion_tokens": 8000,
        "avg_latency_ms": 1800.0,
        "max_latency_ms": 5000.0,
        "error_count": 1,
        "total_estimated_cost": 0.09,
    }
    base.update(overrides)
    return base


class TestUsageAnalysisEngine:
    def test_analyze_empty_data(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert result.total_events == 0
        assert result.total_tokens == 0
        assert result.provider_summaries == []
        assert result.workflow_summaries == []

    def test_analyze_single_provider(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[_make_provider_row()],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert len(result.provider_summaries) == 1
        assert result.provider_summaries[0].provider == "anthropic"
        assert result.total_events == 100
        assert result.total_tokens == 50000

    def test_error_rate_computed(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[_make_provider_row(event_count=100, error_count=15)],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert abs(result.provider_summaries[0].error_rate - 0.15) < 0.001

    def test_high_error_rate_generates_observation(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[_make_provider_row(event_count=100, error_count=15)],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        obs = result.provider_summaries[0].observations
        assert any("error" in o.lower() for o in obs)

    def test_token_share_computed(self):
        engine = UsageAnalysisEngine()
        rows = [
            _make_workflow_row(workflow="ocr", total_tokens=70000),
            _make_workflow_row(workflow="chat", total_tokens=30000),
        ]
        result = engine.analyze(
            provider_rows=[_make_provider_row(total_tokens=100000)],
            workflow_rows=rows,
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        ocr = next(w for w in result.workflow_summaries if w.workflow == "ocr")
        assert abs(ocr.token_share - 0.70) < 0.01

    def test_high_token_concentration_generates_observation(self):
        engine = UsageAnalysisEngine()
        rows = [
            _make_workflow_row(workflow="ocr", total_tokens=70000),
            _make_workflow_row(workflow="chat", total_tokens=10000),
        ]
        result = engine.analyze(
            provider_rows=[_make_provider_row(total_tokens=80000)],
            workflow_rows=rows,
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        ocr = next(w for w in result.workflow_summaries if w.workflow == "ocr")
        assert any("concentration" in o.lower() or "token" in o.lower() for o in ocr.observations)

    def test_high_cost_workflows_detected(self):
        engine = UsageAnalysisEngine()
        rows = [_make_workflow_row(total_tokens=60000)]
        result = engine.analyze(
            provider_rows=[_make_provider_row()],
            workflow_rows=rows,
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert "doc-processing" in result.high_cost_workflows

    def test_provider_fragmentation_detected(self):
        engine = UsageAnalysisEngine()
        providers = [
            _make_provider_row(provider=f"provider-{i}", event_count=10)
            for i in range(5)
        ]
        result = engine.analyze(
            provider_rows=providers,
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert len(result.fragmented_providers) >= 4

    def test_insufficient_latency_data(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert result.latency_trends[0].trend_direction == "insufficient_data"

    def test_latency_trend_stable(self):
        engine = UsageAnalysisEngine()
        rows = [
            {"avg_latency_ms": 2000, "max_latency_ms": 4000, "event_count": 10},
            {"avg_latency_ms": 2100, "max_latency_ms": 4200, "event_count": 10},
            {"avg_latency_ms": 1950, "max_latency_ms": 3900, "event_count": 10},
        ]
        result = engine.analyze(
            provider_rows=[],
            workflow_rows=[],
            latency_trend_rows=rows,
            error_trend_rows=[],
        )
        assert result.latency_trends[0].trend_direction == "stable"

    def test_to_dict_returns_serializable(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[_make_provider_row()],
            workflow_rows=[_make_workflow_row()],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        d = result.to_dict()
        assert "provider_summaries" in d
        assert "workflow_summaries" in d
        assert "confidence_note" in d

    def test_no_observations_when_no_data(self):
        engine = UsageAnalysisEngine()
        result = engine.analyze(
            provider_rows=[],
            workflow_rows=[],
            latency_trend_rows=[],
            error_trend_rows=[],
        )
        assert len(result.system_observations) >= 1
        # Should mention no significant concerns
        assert any("no significant" in o.lower() for o in result.system_observations)


class TestTrendDirection:
    def test_stable_values(self):
        assert _compute_trend_direction([100, 105, 98, 102]) == "stable"

    def test_increasing_values(self):
        assert _compute_trend_direction([100, 120, 140, 160, 180, 200]) == "increasing"

    def test_decreasing_values(self):
        assert _compute_trend_direction([200, 180, 160, 140, 120, 100]) == "decreasing"

    def test_insufficient_data(self):
        assert _compute_trend_direction([100]) == "insufficient_data"
        assert _compute_trend_direction([]) == "insufficient_data"

    def test_two_values_insufficient(self):
        assert _compute_trend_direction([100, 200]) == "insufficient_data"
