"""Tests for llm_intelligence/ingestion_limits.py — ingestion rate limits."""

from __future__ import annotations

import pytest

from llm_intelligence.ingestion_limits import (
    IngestionLimits,
    IngestionLimitsChecker,
    _detect_noisy_workflows,
    check_ingestion_allowed,
)


def _limits(**overrides) -> IngestionLimits:
    base = {
        "max_events_per_hour": 1000,
        "burst_threshold": 200,
        "burst_window_minutes": 5,
        "noisy_workflow_share": 0.80,
    }
    base.update(overrides)
    return IngestionLimits(**base)


class TestIngestionLimits:
    def test_default_limits(self):
        lim = IngestionLimits()
        assert lim.max_events_per_hour == 1000
        assert lim.burst_threshold == 200
        assert lim.noisy_workflow_share == 0.80

    def test_frozen(self):
        lim = IngestionLimits()
        with pytest.raises((AttributeError, TypeError)):
            lim.max_events_per_hour = 999


class TestCheckProject:
    def test_ok_under_limit(self):
        checker = IngestionLimitsChecker()
        status = checker.check_project("proj-a", events_last_hour=100)
        assert status.pressure_level == "ok"
        assert status.warnings == []

    def test_warning_approaching_limit(self):
        checker = IngestionLimitsChecker()
        status = checker.check_project(
            "proj-a",
            events_last_hour=750,
            limits=_limits(max_events_per_hour=1000),
        )
        assert status.pressure_level == "warning"
        assert any(w.warning_type == "rate_exceeded" for w in status.warnings)

    def test_critical_over_limit(self):
        checker = IngestionLimitsChecker()
        status = checker.check_project(
            "proj-a",
            events_last_hour=1500,
            limits=_limits(max_events_per_hour=1000),
        )
        assert status.pressure_level == "critical"
        assert any(w.severity == "critical" for w in status.warnings)

    def test_rate_fraction_computed(self):
        checker = IngestionLimitsChecker()
        status = checker.check_project(
            "proj-a",
            events_last_hour=500,
            limits=_limits(max_events_per_hour=1000),
        )
        assert abs(status.rate_fraction - 0.5) < 0.001

    def test_noisy_workflow_detected(self):
        checker = IngestionLimitsChecker()
        workflow_counts = {"noisy-wf": 900, "other-wf": 100}
        status = checker.check_project(
            "proj-a",
            events_last_hour=500,
            workflow_counts=workflow_counts,
            limits=_limits(noisy_workflow_share=0.80),
        )
        assert any(w.warning_type == "noisy_workflow" for w in status.warnings)

    def test_balanced_workflows_ok(self):
        checker = IngestionLimitsChecker()
        workflow_counts = {"wf-a": 300, "wf-b": 400, "wf-c": 300}
        status = checker.check_project(
            "proj-a",
            events_last_hour=200,
            workflow_counts=workflow_counts,
        )
        assert not any(w.warning_type == "noisy_workflow" for w in status.warnings)

    def test_to_dict_serializable(self):
        checker = IngestionLimitsChecker()
        status = checker.check_project("proj-a", events_last_hour=100)
        d = status.to_dict()
        assert "project_id" in d
        assert "pressure_level" in d
        assert "warnings" in d


class TestCheckBurst:
    def test_no_burst_below_threshold(self):
        checker = IngestionLimitsChecker()
        result = checker.check_burst("proj-a", events_in_window=100)
        assert result is None

    def test_burst_detected_over_threshold(self):
        checker = IngestionLimitsChecker()
        result = checker.check_burst(
            "proj-a",
            events_in_window=300,
            limits=_limits(burst_threshold=200),
        )
        assert result is not None
        assert result.warning_type == "burst_detected"
        assert result.severity == "warning"

    def test_burst_result_serializable(self):
        checker = IngestionLimitsChecker()
        result = checker.check_burst("proj-a", events_in_window=300)
        if result:
            d = result.to_dict()
            assert "warning_type" in d


class TestPressureSummary:
    def test_build_summary_all_ok(self):
        checker = IngestionLimitsChecker()
        statuses = [
            checker.check_project(f"proj-{i}", events_last_hour=50)
            for i in range(3)
        ]
        summary = checker.build_pressure_summary(statuses)
        assert summary.ok_count == 3
        assert summary.warning_count == 0
        assert summary.critical_count == 0

    def test_build_summary_with_warnings(self):
        checker = IngestionLimitsChecker()
        statuses = [
            checker.check_project("ok-proj", events_last_hour=100),
            checker.check_project("warn-proj", events_last_hour=800, limits=_limits()),
        ]
        summary = checker.build_pressure_summary(statuses)
        assert summary.warning_count >= 1

    def test_build_summary_serializable(self):
        checker = IngestionLimitsChecker()
        statuses = [checker.check_project("proj-a", events_last_hour=100)]
        summary = checker.build_pressure_summary(statuses)
        d = summary.to_dict()
        assert "total_projects_checked" in d
        assert "observations" in d


class TestCheckIngestionAllowed:
    def test_allowed_under_limit(self):
        allowed, reason = check_ingestion_allowed("proj-a", events_last_hour=100)
        assert allowed is True
        assert reason is None

    def test_rejected_at_limit(self):
        allowed, reason = check_ingestion_allowed(
            "proj-a",
            events_last_hour=1000,
            limits=IngestionLimits(max_events_per_hour=1000),
        )
        assert allowed is False
        assert reason is not None
        assert "proj-a" in reason

    def test_rejected_over_limit(self):
        allowed, reason = check_ingestion_allowed(
            "proj-a",
            events_last_hour=2000,
            limits=IngestionLimits(max_events_per_hour=1000),
        )
        assert allowed is False


class TestDetectNoisyWorkflows:
    def test_single_dominant_workflow(self):
        counts = {"dominant": 900, "other": 100}
        warnings = _detect_noisy_workflows("proj-a", counts, threshold=0.80)
        assert len(warnings) == 1
        assert warnings[0].warning_type == "noisy_workflow"

    def test_no_noisy_workflow(self):
        counts = {"wf-a": 400, "wf-b": 600}
        warnings = _detect_noisy_workflows("proj-a", counts, threshold=0.80)
        assert warnings == []

    def test_empty_counts(self):
        warnings = _detect_noisy_workflows("proj-a", {}, threshold=0.80)
        assert warnings == []
