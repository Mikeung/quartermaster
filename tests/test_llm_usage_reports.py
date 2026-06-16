"""Tests for reports/llm_usage.py — LLM usage report generators."""

from __future__ import annotations

from reports.llm_usage import (
    generate_cost_concentration_report,
    generate_error_trend_report,
    generate_latency_trend_report,
    generate_provider_usage_report,
    generate_token_concentration_report,
    generate_workflow_economics_report,
)


def _summary_dict(**overrides) -> dict:
    base = {
        "window_hours": 168,
        "total_events": 500,
        "total_tokens": 100000,
        "total_estimated_cost": 0.30,
        "provider_summaries": [
            {
                "provider": "anthropic",
                "event_count": 300,
                "total_tokens": 70000,
                "prompt_tokens": 50000,
                "completion_tokens": 20000,
                "avg_latency_ms": 2200.0,
                "max_latency_ms": 8000.0,
                "error_count": 5,
                "error_rate": 0.017,
                "total_estimated_cost": 0.21,
                "observations": [],
            },
            {
                "provider": "openai",
                "event_count": 200,
                "total_tokens": 30000,
                "prompt_tokens": 22000,
                "completion_tokens": 8000,
                "avg_latency_ms": 1800.0,
                "max_latency_ms": 4000.0,
                "error_count": 2,
                "error_rate": 0.01,
                "total_estimated_cost": 0.09,
                "observations": [],
            },
        ],
        "workflow_summaries": [
            {
                "workflow": "doc-processing",
                "event_count": 250,
                "total_tokens": 65000,
                "prompt_tokens": 48000,
                "completion_tokens": 17000,
                "avg_latency_ms": 2500.0,
                "error_count": 3,
                "error_rate": 0.012,
                "total_estimated_cost": 0.20,
                "token_share": 0.65,
                "cost_share": 0.67,
                "observations": ["Token concentration detected."],
            },
            {
                "workflow": "chat",
                "event_count": 250,
                "total_tokens": 35000,
                "prompt_tokens": 24000,
                "completion_tokens": 11000,
                "avg_latency_ms": 1500.0,
                "error_count": 4,
                "error_rate": 0.016,
                "total_estimated_cost": 0.10,
                "token_share": 0.35,
                "cost_share": 0.33,
                "observations": [],
            },
        ],
        "latency_trends": [
            {
                "provider": None,
                "window_hours": 168,
                "trend_direction": "stable",
                "avg_latency_ms": 2000.0,
                "max_latency_ms": 8000.0,
                "bucket_count": 28,
                "observations": ["Latency appears stable."],
            }
        ],
        "high_cost_workflows": ["doc-processing"],
        "fragmented_providers": [],
        "error_trend": [],
        "system_observations": ["No significant concerns."],
    }
    base.update(overrides)
    return base


class TestProviderUsageReport:
    def test_generates_markdown(self):
        report = generate_provider_usage_report(_summary_dict())
        assert "# LLM Provider Usage Report" in report

    def test_contains_provider_names(self):
        report = generate_provider_usage_report(_summary_dict())
        assert "anthropic" in report
        assert "openai" in report

    def test_contains_token_counts(self):
        report = generate_provider_usage_report(_summary_dict())
        assert "70,000" in report or "70000" in report

    def test_empty_providers_handled(self):
        report = generate_provider_usage_report(_summary_dict(
            total_events=0, provider_summaries=[]
        ))
        assert "No provider data" in report

    def test_includes_advisory_footer(self):
        report = generate_provider_usage_report(_summary_dict())
        assert "Advisory" in report or "advisory" in report.lower()


class TestWorkflowEconomicsReport:
    def test_generates_markdown(self):
        report = generate_workflow_economics_report(_summary_dict())
        assert "# LLM Workflow Economics Report" in report

    def test_contains_workflow_names(self):
        report = generate_workflow_economics_report(_summary_dict())
        assert "doc-processing" in report
        assert "chat" in report

    def test_contains_token_share(self):
        report = generate_workflow_economics_report(_summary_dict())
        assert "65.0%" in report or "65%" in report

    def test_empty_workflows_handled(self):
        report = generate_workflow_economics_report(_summary_dict(
            total_events=0, workflow_summaries=[]
        ))
        assert "No workflow data" in report

    def test_high_cost_workflows_shown(self):
        report = generate_workflow_economics_report(_summary_dict())
        assert "doc-processing" in report


class TestLatencyTrendReport:
    def test_generates_markdown(self):
        trends = [
            {
                "provider": None,
                "window_hours": 168,
                "trend_direction": "increasing",
                "avg_latency_ms": 3000.0,
                "max_latency_ms": 12000.0,
                "bucket_count": 20,
                "observations": ["Latency is increasing."],
            }
        ]
        report = generate_latency_trend_report(trends, window_hours=168, total_events=100)
        assert "# LLM Latency Trend Report" in report

    def test_increasing_trend_shown(self):
        trends = [
            {
                "provider": None,
                "window_hours": 168,
                "trend_direction": "increasing",
                "avg_latency_ms": 3000.0,
                "max_latency_ms": 12000.0,
                "bucket_count": 10,
                "observations": [],
            }
        ]
        report = generate_latency_trend_report(trends)
        assert "Increasing" in report

    def test_no_data_handled(self):
        report = generate_latency_trend_report([], total_events=0)
        assert "No latency data" in report


class TestTokenConcentrationReport:
    def test_generates_markdown(self):
        summaries = [
            {"workflow": "ocr", "total_tokens": 70000, "token_share": 0.70},
            {"workflow": "chat", "total_tokens": 30000, "token_share": 0.30},
        ]
        report = generate_token_concentration_report(
            summaries, total_tokens=100000, window_hours=168, total_events=100
        )
        assert "# LLM Token Concentration Report" in report

    def test_contains_workflow_names(self):
        summaries = [{"workflow": "ocr", "total_tokens": 70000, "token_share": 0.70}]
        report = generate_token_concentration_report(summaries, total_tokens=70000)
        assert "ocr" in report

    def test_no_data_handled(self):
        report = generate_token_concentration_report([], total_tokens=0)
        assert "No workflow token data" in report


class TestErrorTrendReport:
    def test_generates_markdown(self):
        rows = [
            {"provider": "anthropic", "error_type": "rate_limit", "error_count": 15},
            {"provider": "anthropic", "error_type": "timeout", "error_count": 5},
        ]
        report = generate_error_trend_report(rows, window_hours=168, total_events=100)
        assert "# LLM Error Trend Report" in report

    def test_contains_error_types(self):
        rows = [{"provider": "openai", "error_type": "context_length", "error_count": 3}]
        report = generate_error_trend_report(rows)
        assert "context_length" in report

    def test_no_errors_handled(self):
        report = generate_error_trend_report([])
        assert "No error events" in report

    def test_includes_retry_advisory(self):
        rows = [{"provider": "anthropic", "error_type": "rate_limit", "error_count": 10}]
        report = generate_error_trend_report(rows)
        assert "retry" in report.lower() or "Retry" in report


class TestCostConcentrationReport:
    def test_generates_markdown(self):
        report = generate_cost_concentration_report(
            workflow_summaries=_summary_dict()["workflow_summaries"],
            provider_summaries=_summary_dict()["provider_summaries"],
            total_cost=0.30,
        )
        assert "# LLM Operational Cost Concentration Report" in report

    def test_flags_high_concentration(self):
        wf = [{"workflow": "ocr", "total_estimated_cost": 0.25, "cost_share": 0.83}]
        report = generate_cost_concentration_report(
            workflow_summaries=wf,
            provider_summaries=[],
            total_cost=0.30,
        )
        assert "Concentration" in report or "concentration" in report.lower()

    def test_no_data_handled(self):
        report = generate_cost_concentration_report(
            workflow_summaries=[],
            provider_summaries=[],
            total_cost=0.0,
        )
        assert "No cost data" in report
