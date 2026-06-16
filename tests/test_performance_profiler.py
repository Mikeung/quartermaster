"""
Tests for tools/performance_profiler.py — Phase 13D.
"""

from __future__ import annotations

import time

import pytest

from tools.performance_profiler import (
    BUDGETS,
    OperationBudget,
    OperationTimer,
    PerformanceBudgetReport,
    PerformanceBudgetViolation,
    PerformanceProfiler,
    ProfiledOperation,
    _build_observations,
)

# ---------------------------------------------------------------------------
# BUDGETS dict
# ---------------------------------------------------------------------------

class TestBudgets:
    def test_all_budgets_have_positive_limits(self):
        for name, b in BUDGETS.items():
            assert b.soft_limit_ms > 0, name
            assert b.hard_limit_ms > 0, name

    def test_hard_limit_exceeds_soft(self):
        for name, b in BUDGETS.items():
            assert b.hard_limit_ms > b.soft_limit_ms, name

    def test_expected_keys_present(self):
        expected = {
            "signal_quality", "storage_optimizer", "investigation_quality",
            "investigation_triage", "deduplication_small", "deduplication_large",
            "snapshot_synthesis", "report_generation", "retention_analysis",
            "storage_hygiene",
        }
        assert expected <= set(BUDGETS)

    def test_budgets_are_frozen(self):
        b = BUDGETS["signal_quality"]
        with pytest.raises((AttributeError, TypeError)):
            b.soft_limit_ms = 999  # type: ignore[misc]

    def test_categories_are_valid(self):
        valid = {"cognition", "storage", "report", "general"}
        for name, b in BUDGETS.items():
            assert b.category in valid, name


# ---------------------------------------------------------------------------
# OperationBudget
# ---------------------------------------------------------------------------

class TestOperationBudget:
    def test_frozen_dataclass(self):
        b = OperationBudget(name="x", soft_limit_ms=10.0, hard_limit_ms=50.0)
        with pytest.raises((AttributeError, TypeError)):
            b.name = "y"  # type: ignore[misc]

    def test_default_category(self):
        b = OperationBudget(name="x", soft_limit_ms=5.0, hard_limit_ms=20.0)
        assert b.category == "general"


# ---------------------------------------------------------------------------
# ProfiledOperation.check_violation
# ---------------------------------------------------------------------------

class TestProfiledOperationViolation:
    def _budget(self) -> OperationBudget:
        return OperationBudget(name="test_op", soft_limit_ms=10.0, hard_limit_ms=50.0)

    def test_no_budget_returns_none(self):
        op = ProfiledOperation(name="x", elapsed_ms=999.0)
        assert op.check_violation() is None

    def test_within_soft_returns_none(self):
        op = ProfiledOperation(name="x", elapsed_ms=5.0, budget=self._budget())
        assert op.check_violation() is None

    def test_at_soft_limit_passes(self):
        op = ProfiledOperation(name="x", elapsed_ms=10.0, budget=self._budget())
        assert op.check_violation() is None

    def test_above_soft_below_hard_is_soft_violation(self):
        op = ProfiledOperation(name="x", elapsed_ms=25.0, budget=self._budget())
        v = op.check_violation()
        assert v is not None
        assert v.limit_type == "soft"
        assert v.elapsed_ms == 25.0
        assert v.budget_ms == 10.0
        assert v.overage_ms == pytest.approx(15.0)
        assert v.overage_fraction == pytest.approx(1.5)

    def test_at_hard_limit_is_soft_violation(self):
        # elapsed == hard limit → no hard violation, but soft limit still exceeded
        op = ProfiledOperation(name="x", elapsed_ms=50.0, budget=self._budget())
        v = op.check_violation()
        assert v is not None
        assert v.limit_type == "soft"

    def test_above_hard_is_hard_violation(self):
        op = ProfiledOperation(name="x", elapsed_ms=100.0, budget=self._budget())
        v = op.check_violation()
        assert v is not None
        assert v.limit_type == "hard"
        assert v.budget_ms == 50.0
        assert v.overage_ms == pytest.approx(50.0)
        assert v.overage_fraction == pytest.approx(1.0)

    def test_to_dict_no_budget(self):
        op = ProfiledOperation(name="x", elapsed_ms=5.0)
        d = op.to_dict()
        assert d["name"] == "x"
        assert d["budget_name"] is None

    def test_to_dict_with_budget(self):
        op = ProfiledOperation(name="x", elapsed_ms=5.0, budget=self._budget())
        d = op.to_dict()
        assert d["soft_limit_ms"] == 10.0
        assert d["hard_limit_ms"] == 50.0


# ---------------------------------------------------------------------------
# PerformanceBudgetViolation
# ---------------------------------------------------------------------------

class TestPerformanceBudgetViolation:
    def test_to_dict_fields(self):
        v = PerformanceBudgetViolation(
            operation_name="foo",
            elapsed_ms=120.5,
            budget_ms=100.0,
            limit_type="hard",
            overage_ms=20.5,
            overage_fraction=0.205,
        )
        d = v.to_dict()
        assert d["operation_name"] == "foo"
        assert d["limit_type"] == "hard"
        assert d["overage_fraction"] == pytest.approx(0.205)


# ---------------------------------------------------------------------------
# PerformanceProfiler.analyze
# ---------------------------------------------------------------------------

class TestPerformanceProfiler:
    def _profiler(self) -> PerformanceProfiler:
        return PerformanceProfiler()

    def _budget(self, soft=10.0, hard=50.0) -> OperationBudget:
        return OperationBudget(name="op", soft_limit_ms=soft, hard_limit_ms=hard)

    def test_empty_operations(self):
        report = self._profiler().analyze([])
        assert report.overall_status == "ok"
        assert report.hard_violation_count == 0
        assert report.soft_violation_count == 0
        assert "No operations profiled" in report.observations[0]

    def test_all_within_budget(self):
        ops = [
            ProfiledOperation("a", 5.0, self._budget()),
            ProfiledOperation("b", 3.0, self._budget()),
        ]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "ok"
        assert report.hard_violation_count == 0
        assert report.soft_violation_count == 0
        assert len(report.within_budget) == 2
        assert len(report.violations) == 0

    def test_soft_violation_gives_warning(self):
        ops = [ProfiledOperation("slow", 20.0, self._budget())]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "warning"
        assert report.soft_violation_count == 1
        assert report.hard_violation_count == 0

    def test_hard_violation_gives_critical(self):
        ops = [ProfiledOperation("very_slow", 100.0, self._budget())]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "critical"
        assert report.hard_violation_count == 1

    def test_hard_dominates_status_over_soft(self):
        ops = [
            ProfiledOperation("a", 20.0, self._budget()),   # soft violation
            ProfiledOperation("b", 100.0, self._budget()),  # hard violation
        ]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "critical"
        assert report.hard_violation_count == 1
        assert report.soft_violation_count == 1

    def test_unbudgeted_ops_tracked_separately(self):
        ops = [
            ProfiledOperation("a", 5.0, self._budget()),
            ProfiledOperation("b", 999.0),  # no budget
        ]
        report = self._profiler().analyze(ops)
        assert len(report.unbudgeted) == 1
        assert report.unbudgeted[0].name == "b"
        assert report.overall_status == "ok"

    def test_all_unbudgeted_gives_ok_with_observation(self):
        ops = [ProfiledOperation("x", 99.0)]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "ok"
        # When all ops are unbudgeted the observation mentions inability to assess
        assert any("cannot assess" in o.lower() for o in report.observations)

    def test_to_dict_structure(self):
        ops = [ProfiledOperation("x", 5.0, self._budget())]
        report = self._profiler().analyze(ops)
        d = report.to_dict()
        assert "overall_status" in d
        assert "violations" in d
        assert "total_operations" in d

    def test_real_budgets_lookup(self):
        ops = [
            ProfiledOperation(
                "investigation_quality",
                5.0,
                BUDGETS["investigation_quality"],
            )
        ]
        report = self._profiler().analyze(ops)
        assert report.overall_status == "ok"


# ---------------------------------------------------------------------------
# PerformanceBudgetReport.markdown
# ---------------------------------------------------------------------------

class TestReportMarkdown:
    def _report(
        self,
        hard_count: int = 0,
        soft_count: int = 0,
    ) -> PerformanceBudgetReport:
        budget = OperationBudget("op", soft_limit_ms=10.0, hard_limit_ms=50.0)
        ops = [ProfiledOperation("op", 5.0, budget)]
        violations = []
        within = [ops[0]] if hard_count == 0 and soft_count == 0 else []
        if hard_count:
            v = PerformanceBudgetViolation(
                "op", 100.0, 50.0, "hard", 50.0, 1.0
            )
            violations.append(v)
        if soft_count:
            v = PerformanceBudgetViolation(
                "op", 20.0, 10.0, "soft", 10.0, 1.0
            )
            violations.append(v)
        status = "critical" if hard_count else ("warning" if soft_count else "ok")
        return PerformanceBudgetReport(
            operations=ops,
            violations=violations,
            within_budget=within,
            unbudgeted=[],
            hard_violation_count=hard_count,
            soft_violation_count=soft_count,
            overall_status=status,
            observations=["Test observation."],
        )

    def test_markdown_contains_title(self):
        md = self._report().markdown()
        assert "# Performance Budget Report" in md

    def test_markdown_contains_status(self):
        md = self._report(hard_count=1).markdown()
        assert "CRITICAL" in md

    def test_markdown_advisory_footer(self):
        md = self._report().markdown()
        assert "Advisory only" in md

    def test_markdown_hard_section(self):
        md = self._report(hard_count=1).markdown()
        assert "Hard Limit Violations" in md

    def test_markdown_soft_section(self):
        md = self._report(soft_count=1).markdown()
        assert "Soft Limit Warnings" in md

    def test_markdown_within_budget_section(self):
        md = self._report().markdown()
        assert "Within Budget" in md

    def test_markdown_observations_section(self):
        md = self._report().markdown()
        assert "Test observation." in md


# ---------------------------------------------------------------------------
# OperationTimer context manager
# ---------------------------------------------------------------------------

class TestOperationTimer:
    def test_result_is_none_before_exit(self):
        t = OperationTimer("x")
        assert t.result is None

    def test_result_filled_after_exit(self):
        with OperationTimer("my_op") as t:
            pass
        assert t.result is not None
        assert t.result.name == "my_op"
        assert t.result.elapsed_ms >= 0.0

    def test_elapsed_ms_is_positive(self):
        with OperationTimer("x") as t:
            time.sleep(0.001)
        assert t.result.elapsed_ms > 0.0

    def test_budget_propagated(self):
        b = BUDGETS["report_generation"]
        with OperationTimer("report_generation", budget=b) as t:
            pass
        assert t.result.budget is b

    def test_no_budget_propagated(self):
        with OperationTimer("custom_op") as t:
            pass
        assert t.result.budget is None

    def test_fast_op_within_budget(self):
        b = BUDGETS["report_generation"]
        with OperationTimer("report_generation", budget=b) as t:
            pass  # near-zero time
        v = t.result.check_violation()
        assert v is None


# ---------------------------------------------------------------------------
# _build_observations helper
# ---------------------------------------------------------------------------

class TestBuildObservations:
    def test_no_operations(self):
        obs = _build_observations([], [], [])
        assert any("No operations profiled" in o for o in obs)

    def test_all_budgeted_all_pass(self):
        b = OperationBudget("x", 10.0, 50.0)
        ops = [ProfiledOperation("x", 5.0, b)]
        obs = _build_observations(ops, [], [])
        assert any("within expected latency" in o for o in obs)

    def test_slowest_reported(self):
        b = OperationBudget("x", 100.0, 500.0)
        ops = [
            ProfiledOperation("fast", 1.0, b),
            ProfiledOperation("slow", 80.0, b),
        ]
        obs = _build_observations(ops, [], [])
        assert any("slow" in o for o in obs)

    def test_unbudgeted_count_mentioned(self):
        # Mix budgeted + unbudgeted so the per-item unbudgeted note fires
        b = OperationBudget("y", 10.0, 50.0)
        budgeted = ProfiledOperation("y", 5.0, b)
        unbudgeted = ProfiledOperation("x", 5.0)
        obs = _build_observations([budgeted, unbudgeted], [], [unbudgeted])
        assert any("no budget" in o.lower() for o in obs)

    def test_worst_hard_violation_mentioned(self):
        b = OperationBudget("x", 10.0, 50.0)
        v = PerformanceBudgetViolation("x", 200.0, 50.0, "hard", 150.0, 3.0)
        ops = [ProfiledOperation("x", 200.0, b)]
        obs = _build_observations(ops, [v], [])
        assert any("hard violation" in o.lower() for o in obs)

    def test_soft_overload_fraction_triggers_when_majority(self):
        b = OperationBudget("x", 10.0, 50.0)
        slow_op = ProfiledOperation("slow", 20.0, b)
        v = PerformanceBudgetViolation("slow", 20.0, 10.0, "soft", 10.0, 1.0)
        obs = _build_observations([slow_op], [v], [])
        assert any("soft limit" in o.lower() for o in obs)
