"""Tests for reports/integration.py — integration reporting."""

from __future__ import annotations

from reports.integration import (
    _check_event_sample,
    generate_event_quality_summary,
    generate_ingestion_compatibility_report,
    generate_integration_readiness_report,
    generate_project_integration_summary,
    generate_sdk_usage_guidance,
)


def _valid_sample(**overrides) -> dict:
    base = {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "workflow": "test/workflow",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 800.0,
        "success": True,
    }
    base.update(overrides)
    return base


class TestCheckEventSample:
    def test_valid_sample_has_no_issues(self):
        issues = _check_event_sample(_valid_sample())
        assert issues == []

    def test_missing_required_field(self):
        sample = _valid_sample()
        del sample["provider"]
        issues = _check_event_sample(sample)
        assert any("provider" in i for i in issues)

    def test_forbidden_field_detected(self):
        sample = _valid_sample()
        sample["prompt"] = "Hello world"
        issues = _check_event_sample(sample)
        assert any("prompt" in i for i in issues)

    def test_metadata_too_many_keys(self):
        sample = _valid_sample()
        sample["metadata"] = {f"k{i}": "v" for i in range(15)}
        issues = _check_event_sample(sample)
        assert any("metadata" in i for i in issues)

    def test_metadata_value_too_long(self):
        sample = _valid_sample()
        sample["metadata"] = {"key": "x" * 300}
        issues = _check_event_sample(sample)
        assert any("256" in i for i in issues)

    def test_token_inconsistency_detected(self):
        sample = _valid_sample(prompt_tokens=100, completion_tokens=50, total_tokens=999)
        issues = _check_event_sample(sample)
        assert any("total_tokens" in i for i in issues)

    def test_forbidden_metadata_key_detected(self):
        sample = _valid_sample()
        sample["metadata"] = {"prompt": "oops"}
        issues = _check_event_sample(sample)
        assert any("prompt" in i for i in issues)


class TestIngestionCompatibilityReport:
    def test_empty_samples_returns_note(self):
        report = generate_ingestion_compatibility_report([])
        assert "No event samples" in report

    def test_clean_samples_reported(self):
        samples = [_valid_sample(), _valid_sample(workflow="w2")]
        report = generate_ingestion_compatibility_report(samples)
        assert "Clean: 2" in report

    def test_flagged_samples_reported(self):
        samples = [_valid_sample(), {"provider": "openai"}]  # missing required fields
        report = generate_ingestion_compatibility_report(samples)
        assert "Flagged: 1" in report

    def test_header_present(self):
        report = generate_ingestion_compatibility_report([_valid_sample()])
        assert "# Ingestion Compatibility Report" in report

    def test_required_fields_table_present(self):
        report = generate_ingestion_compatibility_report([_valid_sample()])
        assert "prompt_tokens" in report


class TestIntegrationReadinessReport:
    def test_no_blocking_issues_shows_ready(self):
        report = generate_integration_readiness_report(
            project_profiles=[{"project_id": "my-app", "ingestion_enabled": True}],
            ingestion_pressure_summary=None,
            survivability_report=None,
            llm_storage=None,
        )
        assert "READY" in report

    def test_critical_survivability_shows_not_recommended(self):
        report = generate_integration_readiness_report(
            project_profiles=[],
            ingestion_pressure_summary=None,
            survivability_report={"overall_status": "critical", "checks": []},
            llm_storage=None,
        )
        assert "NOT RECOMMENDED" in report

    def test_warning_survivability_shows_caution(self):
        report = generate_integration_readiness_report(
            project_profiles=[],
            ingestion_pressure_summary=None,
            survivability_report={"overall_status": "warning", "checks": []},
            llm_storage=None,
        )
        assert "CAUTION" in report

    def test_header_present(self):
        report = generate_integration_readiness_report([], None, None, None)
        assert "# Integration Readiness Report" in report

    def test_advisory_footer_present(self):
        report = generate_integration_readiness_report([], None, None, None)
        assert "advisory" in report.lower()


class TestProjectIntegrationSummary:
    def test_header_contains_project_id(self):
        project = {"project_id": "my-app", "name": "My App"}
        report = generate_project_integration_summary(project, None, None)
        assert "my-app" in report

    def test_archived_project_shows_archived(self):
        project = {"project_id": "old-proj", "name": "Old", "archived": True}
        report = generate_project_integration_summary(project, None, None)
        assert "Archived" in report

    def test_event_stats_included(self):
        project = {"project_id": "my-app", "name": "My App"}
        stats = {"event_count": 5000, "distinct_providers": 2, "distinct_workflows": 8}
        report = generate_project_integration_summary(project, event_stats=stats, pressure_status=None)
        assert "5,000" in report

    def test_pressure_status_included(self):
        project = {"project_id": "my-app", "name": "My App"}
        pressure = {"pressure_level": "warning", "rate_fraction": 0.78, "warnings": []}
        report = generate_project_integration_summary(project, None, pressure_status=pressure)
        assert "WARNING" in report


class TestSdkUsageGuidance:
    def test_header_present(self):
        report = generate_sdk_usage_guidance("my-app", "http://localhost:8000")
        assert "# SDK Usage Guidance" in report

    def test_project_id_in_code_examples(self):
        report = generate_sdk_usage_guidance("my-rag-app", "http://localhost:8000")
        assert "my-rag-app" in report

    def test_stack_guidance_included_when_provided(self):
        report = generate_sdk_usage_guidance("my-app", "http://localhost:8000", stack="fastapi")
        assert "FastAPI" in report

    def test_privacy_constraints_section_present(self):
        report = generate_sdk_usage_guidance("my-app", "http://localhost:8000")
        assert "Privacy Constraints" in report

    def test_unknown_stack_returns_generic(self):
        report = generate_sdk_usage_guidance("my-app", "http://localhost:8000", stack="unknown-stack")
        assert "# SDK Usage Guidance" in report  # still returns something valid


class TestEventQualitySummary:
    def test_no_issues_clean_report(self):
        providers = [{"provider": "openai", "total_events": 100, "error_count": 2, "avg_latency_ms": 800}]
        workflows = [{"workflow": "my-wf", "total_events": 100, "avg_prompt_tokens": 500, "avg_completion_tokens": 100}]
        report = generate_event_quality_summary(providers, workflows)
        assert "# Event Quality Summary" in report
        assert "No quality issues" in report

    def test_high_error_rate_flagged(self):
        providers = [{"provider": "openai", "total_events": 100, "error_count": 25, "avg_latency_ms": 800}]
        report = generate_event_quality_summary(providers, [])
        assert "error rate" in report.lower()

    def test_zero_latency_noted(self):
        providers = [{"provider": "openai", "total_events": 100, "error_count": 0, "avg_latency_ms": 0}]
        report = generate_event_quality_summary(providers, [])
        assert "latency" in report.lower()

    def test_zero_prompt_tokens_noted(self):
        providers = [{"provider": "openai", "total_events": 10, "error_count": 0, "avg_latency_ms": 500}]
        workflows = [{"workflow": "w", "total_events": 10, "avg_prompt_tokens": 0, "avg_completion_tokens": 50}]
        report = generate_event_quality_summary(providers, workflows)
        assert "prompt tokens" in report.lower() or "token" in report.lower()
