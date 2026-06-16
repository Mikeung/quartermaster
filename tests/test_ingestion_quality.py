"""Tests for llm_intelligence/ingestion_quality.py."""

import pytest

from llm_intelligence.ingestion_quality import (
    IngestionQualityReport,
    IngestionQualityScorer,
)


def _provider(
    provider: str = "openai",
    total_events: int = 100,
    avg_prompt_tokens: float = 500.0,
    avg_completion_tokens: float = 200.0,
    avg_latency_ms: float = 1200.0,
    error_count: int = 2,
) -> dict:
    return {
        "provider": provider,
        "total_events": total_events,
        "avg_prompt_tokens": avg_prompt_tokens,
        "avg_completion_tokens": avg_completion_tokens,
        "avg_latency_ms": avg_latency_ms,
        "error_count": error_count,
    }


def _workflow(
    workflow: str = "api/summarize",
    total_events: int = 50,
    avg_prompt_tokens: float = 400.0,
    avg_completion_tokens: float = 150.0,
    error_count: int = 1,
) -> dict:
    return {
        "workflow": workflow,
        "total_events": total_events,
        "avg_prompt_tokens": avg_prompt_tokens,
        "avg_completion_tokens": avg_completion_tokens,
        "error_count": error_count,
    }


def _score(**kwargs) -> IngestionQualityReport:
    scorer = IngestionQualityScorer()
    defaults = {
        "provider_stats": [_provider()],
        "workflow_stats": [_workflow()],
        "total_events": 100,
        "events_with_metadata": 60,
        "events_with_error_type": 1,
        "total_failures": 2,
    }
    defaults.update(kwargs)
    return scorer.score(**defaults)


class TestEmptyInput:
    def test_zero_events_returns_poor_band(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(
            provider_stats=[],
            workflow_stats=[],
            total_events=0,
        )
        assert result.quality_band == "poor"

    def test_zero_events_score_zero(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(
            provider_stats=[], workflow_stats=[], total_events=0
        )
        assert result.quality_score == pytest.approx(0.0)

    def test_zero_events_has_warning(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(
            provider_stats=[], workflow_stats=[], total_events=0
        )
        assert len(result.integration_warnings) > 0


class TestQualityBands:
    def test_excellent_band_threshold(self):
        # Full data should yield excellent score
        result = _score(
            provider_stats=[_provider(provider="openai", avg_latency_ms=800.0)],
            workflow_stats=[_workflow(workflow="api/summarize/v2")],
            total_events=200,
            events_with_metadata=190,
            events_with_error_type=3,
            total_failures=3,
        )
        assert result.quality_score >= 0.70  # at least good
        assert result.quality_band in ("good", "excellent")

    def test_poor_band_when_no_data(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(
            provider_stats=[],
            workflow_stats=[],
            total_events=0,
        )
        assert result.quality_band == "poor"

    def test_fair_band_on_partial_data(self):
        result = _score(
            provider_stats=[_provider(provider="openai", avg_prompt_tokens=0.0, avg_latency_ms=0.0)],
            workflow_stats=[_workflow(workflow="default")],
            events_with_metadata=0,
        )
        assert result.quality_band in ("poor", "fair")


class TestScoreRange:
    def test_score_between_0_and_1(self):
        for _ in range(5):
            result = _score()
            assert 0.0 <= result.quality_score <= 1.0

    def test_zero_events_score_not_above_zero(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(provider_stats=[], workflow_stats=[], total_events=0)
        assert result.quality_score == pytest.approx(0.0)


class TestDimensions:
    def test_six_dimensions_returned(self):
        result = _score()
        assert len(result.dimensions) == 6

    def test_dimension_names(self):
        result = _score()
        names = {d.name for d in result.dimensions}
        assert "Field Completeness" in names
        assert "Token Quality" in names
        assert "Latency Quality" in names
        assert "Workflow Naming" in names
        assert "Error Coverage" in names
        assert "Metadata Utilization" in names

    def test_dimension_scores_in_range(self):
        result = _score()
        for d in result.dimensions:
            assert 0.0 <= d.score <= 1.0


class TestFieldCompleteness:
    def test_unknown_provider_reduces_completeness(self):
        result_good = _score(provider_stats=[_provider(provider="openai")])
        result_bad = _score(provider_stats=[_provider(provider="unknown")])
        completeness_good = next(d for d in result_good.dimensions if d.name == "Field Completeness")
        completeness_bad = next(d for d in result_bad.dimensions if d.name == "Field Completeness")
        assert completeness_good.score > completeness_bad.score

    def test_generic_workflow_reduces_completeness(self):
        result_good = _score(workflow_stats=[_workflow(workflow="api/process/v2")])
        result_bad = _score(workflow_stats=[_workflow(workflow="default")])
        completeness_good = next(d for d in result_good.dimensions if d.name == "Field Completeness")
        completeness_bad = next(d for d in result_bad.dimensions if d.name == "Field Completeness")
        assert completeness_good.score > completeness_bad.score


class TestTokenQuality:
    def test_zero_prompt_tokens_reduces_score(self):
        result_good = _score(provider_stats=[_provider(avg_prompt_tokens=500.0)])
        result_bad = _score(provider_stats=[_provider(avg_prompt_tokens=0.0)])
        tokens_good = next(d for d in result_good.dimensions if d.name == "Token Quality")
        tokens_bad = next(d for d in result_bad.dimensions if d.name == "Token Quality")
        assert tokens_good.score > tokens_bad.score

    def test_zero_completion_on_small_provider_not_penalised(self):
        # Small providers (≤5 events) don't get penalized for zero completion tokens
        result = _score(provider_stats=[_provider(avg_completion_tokens=0.0, total_events=3)])
        tokens = next(d for d in result.dimensions if d.name == "Token Quality")
        assert tokens.score == pytest.approx(1.0)


class TestLatencyQuality:
    def test_zero_latency_reduces_score(self):
        result_good = _score(provider_stats=[_provider(avg_latency_ms=1200.0)])
        result_bad = _score(provider_stats=[_provider(avg_latency_ms=0.0)])
        lat_good = next(d for d in result_good.dimensions if d.name == "Latency Quality")
        lat_bad = next(d for d in result_bad.dimensions if d.name == "Latency Quality")
        assert lat_good.score > lat_bad.score


class TestWorkflowNaming:
    def test_generic_names_reduce_score(self):
        result_bad = _score(workflow_stats=[_workflow(workflow="default")])
        result_good = _score(workflow_stats=[_workflow(workflow="api/summarize")])
        wf_bad = next(d for d in result_bad.dimensions if d.name == "Workflow Naming")
        wf_good = next(d for d in result_good.dimensions if d.name == "Workflow Naming")
        assert wf_good.score > wf_bad.score

    def test_hierarchical_name_scores_higher(self):
        result = _score(workflow_stats=[_workflow(workflow="api/document/summarize")])
        wf = next(d for d in result.dimensions if d.name == "Workflow Naming")
        assert wf.score >= 0.8

    def test_no_workflows_returns_neutral_score(self):
        result = _score(workflow_stats=[])
        wf = next(d for d in result.dimensions if d.name == "Workflow Naming")
        assert wf.score == pytest.approx(0.5)


class TestErrorCoverage:
    def test_zero_failures_perfect_coverage(self):
        result = _score(total_failures=0, events_with_error_type=0)
        ec = next(d for d in result.dimensions if d.name == "Error Coverage")
        assert ec.score == pytest.approx(1.0)

    def test_failures_without_error_type_reduces_score(self):
        result_good = _score(total_failures=10, events_with_error_type=10)
        result_bad = _score(total_failures=10, events_with_error_type=0)
        ec_good = next(d for d in result_good.dimensions if d.name == "Error Coverage")
        ec_bad = next(d for d in result_bad.dimensions if d.name == "Error Coverage")
        assert ec_good.score > ec_bad.score


class TestMetadataUtilization:
    def test_high_metadata_usage_scores_high(self):
        result = _score(events_with_metadata=90, total_events=100)
        meta = next(d for d in result.dimensions if d.name == "Metadata Utilization")
        assert meta.score >= 0.8

    def test_no_metadata_scores_low(self):
        result = _score(events_with_metadata=0, total_events=100)
        meta = next(d for d in result.dimensions if d.name == "Metadata Utilization")
        assert meta.score < 0.5


class TestReportOutput:
    def test_to_dict_complete(self):
        result = _score()
        d = result.to_dict()
        assert "quality_score" in d
        assert "quality_band" in d
        assert "total_events_assessed" in d
        assert "dimensions" in d
        assert "integration_warnings" in d
        assert "improvement_suggestions" in d
        assert "advisory" in d

    def test_markdown_contains_quality_band(self):
        result = _score()
        md = result.markdown()
        assert result.quality_band in md.lower()

    def test_total_events_assessed(self):
        result = _score(total_events=250)
        assert result.total_events_assessed == 250


class TestImprovementSuggestions:
    def test_suggestions_provided_for_low_score(self):
        scorer = IngestionQualityScorer()
        result = scorer.score(
            provider_stats=[_provider(provider="unknown", avg_prompt_tokens=0.0, avg_latency_ms=0.0)],
            workflow_stats=[_workflow(workflow="test")],
            total_events=50,
            events_with_metadata=0,
            events_with_error_type=0,
            total_failures=10,
        )
        assert len(result.improvement_suggestions) > 0

    def test_excellent_score_has_fewer_suggestions(self):
        result_good = _score(
            provider_stats=[_provider(avg_prompt_tokens=600, avg_latency_ms=900)],
            workflow_stats=[_workflow(workflow="api/process/main")],
            events_with_metadata=98,
            total_events=100,
        )
        result_poor = _score(
            provider_stats=[_provider(provider="unknown", avg_prompt_tokens=0, avg_latency_ms=0)],
            workflow_stats=[_workflow(workflow="default")],
            events_with_metadata=0,
            total_events=100,
        )
        assert len(result_good.improvement_suggestions) <= len(result_poor.improvement_suggestions)
