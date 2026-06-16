"""Tests for tools/storage_optimizer.py."""

from __future__ import annotations

from tools.storage_optimizer import (
    RetentionTuningRecommendation,
    StorageOptimizationReport,
    StorageOptimizerEngine,
    StoragePressureForecast,
    _build_pressure_forecast,
    _build_sqlite_guidance,
    _check_cold_storage_pressure,
    _check_oversized_evidence_pressure,
    _check_retention_policy_fit,
    _compute_urgency,
    _IDSequencer,
)

_GB = 1024 * 1024 * 1024
_MB = 1024 * 1024


def _base_kwargs(**overrides):
    base = {
        "snapshot_count": 50,
        "max_snapshot_count": 200,
        "db_size_bytes": 20 * _MB,
        "disk_total_bytes": 100 * _GB,
        "disk_used_bytes": 40 * _GB,
    }
    base.update(overrides)
    return base


class TestIDSequencer:
    def test_sequential_within_prefix(self):
        seq = _IDSequencer()
        assert seq.next("RET") == "RET-01"
        assert seq.next("RET") == "RET-02"

    def test_independent_across_prefixes(self):
        seq = _IDSequencer()
        seq.next("RET")
        assert seq.next("ARC") == "ARC-01"

    def test_format_two_digits(self):
        seq = _IDSequencer()
        for _ in range(9):
            seq.next("X")
        assert seq.next("X") == "X-10"


class TestRetentionPolicyFitCheck:
    def _seq(self):
        return _IDSequencer()

    def test_high_snapshot_fraction_generates_high_rec(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=175,
            max_snapshot_count=200,
            deletion_count=None,
            total_at_run=None,
            retention_days=30,
        )
        assert any(r.priority == "high" for r in recs)

    def test_low_snapshot_fraction_no_rec(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=50,
            max_snapshot_count=200,
            deletion_count=None,
            total_at_run=None,
            retention_days=30,
        )
        assert not recs

    def test_very_low_deletion_rate_lenient_rec(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=50,
            max_snapshot_count=200,
            deletion_count=1,
            total_at_run=100,
            retention_days=30,
        )
        assert any("lenient" in r.title.lower() for r in recs)
        assert any(r.priority == "low" for r in recs)

    def test_high_deletion_rate_aggressive_rec(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=50,
            max_snapshot_count=200,
            deletion_count=60,
            total_at_run=100,
            retention_days=30,
        )
        assert any("aggressive" in r.title.lower() for r in recs)
        assert any(r.priority == "medium" for r in recs)

    def test_healthy_deletion_rate_no_rec(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=50,
            max_snapshot_count=200,
            deletion_count=10,
            total_at_run=100,
            retention_days=30,
        )
        # 10% deletion — within healthy range, no rec expected
        retention_recs = [r for r in recs if "lenient" in r.title or "aggressive" in r.title]
        assert not retention_recs

    def test_to_dict_has_advisory(self):
        recs = _check_retention_policy_fit(
            self._seq(),
            snapshot_count=180,
            max_snapshot_count=200,
            deletion_count=None,
            total_at_run=None,
            retention_days=30,
        )
        for r in recs:
            d = r.to_dict()
            assert "advisory" in d


class TestColdStoragePressure:
    def _seq(self):
        return _IDSequencer()

    def test_cold_snapshots_generate_suggestion(self):
        sugs = _check_cold_storage_pressure(
            self._seq(), cold_snapshot_count=20, oldest_snapshot_days=None
        )
        assert len(sugs) >= 1
        assert any("cold" in s.title.lower() for s in sugs)

    def test_very_old_snapshots_generate_suggestion(self):
        sugs = _check_cold_storage_pressure(
            self._seq(), cold_snapshot_count=None, oldest_snapshot_days=200
        )
        assert len(sugs) >= 1

    def test_zero_cold_no_suggestion(self):
        sugs = _check_cold_storage_pressure(
            self._seq(), cold_snapshot_count=0, oldest_snapshot_days=None
        )
        assert not sugs

    def test_none_inputs_no_suggestion(self):
        sugs = _check_cold_storage_pressure(
            self._seq(), cold_snapshot_count=None, oldest_snapshot_days=None
        )
        assert not sugs


class TestOversizedEvidencePressure:
    def _seq(self):
        return _IDSequencer()

    def test_oversized_count_generates_suggestion(self):
        sugs = _check_oversized_evidence_pressure(
            self._seq(),
            oversized_snapshot_count=10,
            oversized_estimated_bytes=5 * _MB,
            avg_evidence_tokens=None,
        )
        assert len(sugs) >= 1
        assert any("oversized" in s.title.lower() for s in sugs)

    def test_high_avg_tokens_generates_suggestion(self):
        sugs = _check_oversized_evidence_pressure(
            self._seq(),
            oversized_snapshot_count=None,
            oversized_estimated_bytes=None,
            avg_evidence_tokens=15_000.0,
        )
        assert len(sugs) >= 1

    def test_zero_oversized_no_suggestion(self):
        sugs = _check_oversized_evidence_pressure(
            self._seq(),
            oversized_snapshot_count=0,
            oversized_estimated_bytes=None,
            avg_evidence_tokens=None,
        )
        assert not sugs


class TestPressureForecast:
    def test_returns_none_on_zero_disk(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=0,
            disk_used_bytes=0, db_growth_bytes_last_window=None,
            window_days=None, snapshot_growth_last_window=None,
        )
        assert result is None

    def test_low_confidence_when_no_growth_data(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=100 * _GB,
            disk_used_bytes=30 * _GB, db_growth_bytes_last_window=None,
            window_days=None, snapshot_growth_last_window=None,
        )
        assert result is not None
        assert result.confidence == "low"

    def test_medium_confidence_with_size_growth(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=100 * _GB,
            disk_used_bytes=30 * _GB,
            db_growth_bytes_last_window=50 * _MB,
            window_days=7,
            snapshot_growth_last_window=None,
        )
        assert result is not None
        assert result.confidence == "medium"

    def test_high_confidence_with_all_data(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=100 * _GB,
            disk_used_bytes=30 * _GB,
            db_growth_bytes_last_window=50 * _MB,
            window_days=7,
            snapshot_growth_last_window=10,
        )
        assert result is not None
        assert result.confidence == "high"

    def test_critical_forecast_on_large_growth(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=80 * _GB,
            disk_total_bytes=100 * _GB,
            disk_used_bytes=82 * _GB,
            db_growth_bytes_last_window=2 * _GB,
            window_days=7,
            snapshot_growth_last_window=5,
        )
        assert result is not None
        assert result.expected_pressure_level in ("warning", "critical")

    def test_to_dict_structure(self):
        result = _build_pressure_forecast(
            snapshot_count=50, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=100 * _GB,
            disk_used_bytes=40 * _GB,
            db_growth_bytes_last_window=None,
            window_days=None,
            snapshot_growth_last_window=None,
        )
        assert result is not None
        d = result.to_dict()
        assert "projected_db_size_bytes" in d
        assert "expected_pressure_level" in d
        assert "confidence" in d
        assert "projected_db_size_human" in d

    def test_projected_snapshot_count(self):
        result = _build_pressure_forecast(
            snapshot_count=100, max_snapshot_count=200,
            db_size_bytes=10 * _MB, disk_total_bytes=100 * _GB,
            disk_used_bytes=40 * _GB,
            db_growth_bytes_last_window=_MB,
            window_days=7,
            snapshot_growth_last_window=7,  # 1/day
        )
        assert result is not None
        assert result.projected_snapshot_count > 100


class TestSQLiteGuidance:
    def test_returns_none_on_no_page_count(self):
        assert _build_sqlite_guidance(
            db_size_bytes=10 * _MB, db_page_count=None, db_freelist_count=None
        ) is None

    def test_returns_none_on_zero_page_count(self):
        assert _build_sqlite_guidance(
            db_size_bytes=10 * _MB, db_page_count=0, db_freelist_count=None
        ) is None

    def test_high_fragmentation_vacuum_recommended(self):
        g = _build_sqlite_guidance(
            db_size_bytes=100 * _MB,
            db_page_count=1000,
            db_freelist_count=400,  # 40% → critical
        )
        assert g is not None
        assert g.vacuum_recommended
        assert g.fragmentation_severity == "high"

    def test_low_fragmentation_no_vacuum(self):
        g = _build_sqlite_guidance(
            db_size_bytes=10 * _MB,
            db_page_count=1000,
            db_freelist_count=10,  # 1%
        )
        assert g is not None
        assert not g.vacuum_recommended
        assert g.fragmentation_severity in ("none", "low")

    def test_large_db_analyze_recommended(self):
        g = _build_sqlite_guidance(
            db_size_bytes=200 * _MB,
            db_page_count=10000,
            db_freelist_count=0,
        )
        assert g is not None
        assert g.analyze_recommended

    def test_to_dict_has_advisory(self):
        g = _build_sqlite_guidance(
            db_size_bytes=10 * _MB,
            db_page_count=1000,
            db_freelist_count=300,
        )
        assert g is not None
        d = g.to_dict()
        assert "advisory" in d
        assert "estimated_space_recovery_human" in d


class TestComputeUrgency:
    def test_high_priority_rec_means_high_urgency(self):
        rec = RetentionTuningRecommendation(
            recommendation_id="RET-01", priority="high",
            title="t", observation="o", suggested_action="a",
            current_value="c", suggested_value=None,
        )
        urgency = _compute_urgency([rec], [], None, None)
        assert urgency == "high"

    def test_no_issues_means_none_urgency(self):
        assert _compute_urgency([], [], None, None) == "none"

    def test_critical_forecast_means_high_urgency(self):
        forecast = StoragePressureForecast(
            forecast_horizon_days=30, current_db_size_bytes=10,
            projected_db_size_bytes=10, growth_rate_bytes_per_day=0,
            projected_disk_usage_fraction=0.9, projected_snapshot_count=100,
            expected_pressure_level="critical", observations=[], confidence="high",
        )
        urgency = _compute_urgency([], [], forecast, None)
        assert urgency == "high"


class TestStorageOptimizerEngineGenerate:
    def test_returns_report(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        assert isinstance(report, StorageOptimizationReport)

    def test_urgency_valid_value(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        assert report.overall_urgency in ("none", "low", "moderate", "high")

    def test_summary_observations_nonempty(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        assert len(report.summary_observations) >= 1

    def test_no_forecast_on_zero_disk(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs(disk_total_bytes=0))
        assert report.pressure_forecast is None

    def test_sqlite_guidance_present_with_page_count(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(
            **_base_kwargs(),
            db_page_count=5000,
            db_freelist_count=1200,
        )
        assert report.sqlite_guidance is not None

    def test_sqlite_guidance_absent_without_page_count(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        assert report.sqlite_guidance is None

    def test_cold_storage_suggestion_generated(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs(cold_snapshot_count=15))
        assert any("cold" in s.title.lower() for s in report.archive_suggestions)

    def test_high_snapshot_count_generates_retention_rec(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs(snapshot_count=180, max_snapshot_count=200))
        assert any(r.priority == "high" for r in report.retention_recommendations)

    def test_to_dict_complete(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        d = report.to_dict()
        assert "overall_urgency" in d
        assert "retention_recommendations" in d
        assert "archive_suggestions" in d
        assert "pressure_forecast" in d
        assert "sqlite_guidance" in d
        assert "advisory" in d
        assert "generated_at" in d

    def test_markdown_contains_urgency(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        md = report.markdown()
        assert report.overall_urgency.upper() in md

    def test_markdown_contains_advisory(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(**_base_kwargs())
        md = report.markdown()
        assert "Advisory only" in md or "advisory" in md.lower()

    def test_forecast_present_with_growth_data(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(
            **_base_kwargs(),
            db_growth_bytes_last_window=5 * _MB,
            window_days=7,
            snapshot_growth_last_window=10,
        )
        assert report.pressure_forecast is not None
        assert report.pressure_forecast.confidence == "high"

    def test_oversized_evidence_suggestion(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(
            **_base_kwargs(),
            oversized_snapshot_count=5,
            oversized_estimated_bytes=10 * _MB,
        )
        assert any("oversized" in s.title.lower() for s in report.archive_suggestions)

    def test_lenient_retention_rec_on_low_deletion_rate(self):
        engine = StorageOptimizerEngine()
        report = engine.generate(
            **_base_kwargs(),
            deletion_count_last_run=1,
            total_count_last_run=100,
        )
        assert any("lenient" in r.title.lower() for r in report.retention_recommendations)
