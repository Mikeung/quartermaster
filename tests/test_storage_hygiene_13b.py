"""Tests for Phase 13B additions to memory/storage_hygiene.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.storage_hygiene import (
    ColdStorageReport,
    OversizedEvidenceReport,
    SnapshotDensityReport,
    analyze_snapshot_density,
    assess_archive_pressure,
    find_cold_storage_candidates,
    find_oversized_snapshots,
)


def _ts(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _snap(snap_id: int, days_ago: float, project_id: str = "proj-a") -> dict:
    return {
        "id": snap_id,
        "project_id": project_id,
        "created_at": _ts(days_ago),
    }


class TestFindOversizedSnapshots:
    def test_empty_list(self):
        report = find_oversized_snapshots([])
        assert isinstance(report, OversizedEvidenceReport)
        assert report.oversized_count == 0
        assert report.total_assessed == 0
        assert not report.has_oversized

    def test_no_oversized(self):
        stats = [{"snapshot_id": i, "total_tokens": 500} for i in range(5)]
        report = find_oversized_snapshots(stats, token_threshold=10_000)
        assert report.oversized_count == 0
        assert report.total_assessed == 5
        assert not report.has_oversized

    def test_oversized_detected(self):
        stats = [
            {"snapshot_id": 1, "total_tokens": 15_000},
            {"snapshot_id": 2, "total_tokens": 500},
        ]
        report = find_oversized_snapshots(stats, token_threshold=10_000)
        assert report.oversized_count == 1
        assert 1 in report.oversized_snapshot_ids
        assert report.has_oversized

    def test_excess_tokens_computed(self):
        stats = [{"snapshot_id": 1, "total_tokens": 12_000}]
        report = find_oversized_snapshots(stats, token_threshold=10_000)
        assert report.estimated_excess_tokens == 2_000

    def test_observations_nonempty(self):
        stats = [{"snapshot_id": 1, "total_tokens": 20_000}]
        report = find_oversized_snapshots(stats)
        assert report.observations

    def test_to_dict_structure(self):
        stats = [{"snapshot_id": 1, "total_tokens": 5_000}]
        d = find_oversized_snapshots(stats).to_dict()
        assert "oversized_count" in d
        assert "token_threshold" in d
        assert "has_oversized" in d
        assert "advisory" in d

    def test_all_oversized(self):
        stats = [{"snapshot_id": i, "total_tokens": 50_000} for i in range(4)]
        report = find_oversized_snapshots(stats, token_threshold=10_000)
        assert report.oversized_count == 4


class TestFindColdStorageCandidates:
    def test_empty_list(self):
        report = find_cold_storage_candidates([])
        assert isinstance(report, ColdStorageReport)
        assert report.candidate_count == 0
        assert not report.has_candidates

    def test_recent_snapshots_not_cold(self):
        snaps = [_snap(i, days_ago=10) for i in range(5)]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidate_count == 0

    def test_old_snapshots_are_cold(self):
        snaps = [_snap(i, days_ago=100) for i in range(3)]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidate_count == 3
        assert report.has_candidates

    def test_mixed_age(self):
        snaps = [_snap(1, days_ago=100), _snap(2, days_ago=5)]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidate_count == 1

    def test_candidate_age_days_populated(self):
        snaps = [_snap(1, days_ago=100)]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidates[0].age_days >= 99.9

    def test_to_dict_structure(self):
        snaps = [_snap(1, days_ago=100)]
        d = find_cold_storage_candidates(snaps).to_dict()
        assert "candidate_count" in d
        assert "cold_after_days" in d
        assert "has_candidates" in d
        assert "advisory" in d

    def test_total_assessed_matches_input(self):
        snaps = [_snap(i, days_ago=50) for i in range(7)]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.total_assessed == 7

    def test_missing_id_skipped_gracefully(self):
        snaps = [{"project_id": "x", "created_at": _ts(100)}]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidate_count == 0

    def test_invalid_timestamp_skipped(self):
        snaps = [{"id": 1, "project_id": "x", "created_at": "not-a-date"}]
        report = find_cold_storage_candidates(snaps, cold_after_days=90)
        assert report.candidate_count == 0

    def test_observations_nonempty(self):
        snaps = [_snap(1, days_ago=100)]
        report = find_cold_storage_candidates(snaps)
        assert report.observations


class TestAnalyzeSnapshotDensity:
    def test_empty_list(self):
        report = analyze_snapshot_density([], window_days=30)
        assert isinstance(report, SnapshotDensityReport)
        assert report.total_snapshots == 0
        assert report.peak_day is None

    def test_counts_within_window(self):
        snaps = [{"created_at": _ts(i)} for i in range(10)]
        report = analyze_snapshot_density(snaps, window_days=30)
        assert report.total_snapshots == 10

    def test_outside_window_excluded(self):
        snaps = [{"created_at": _ts(60)}]  # 60 days ago, outside 30-day window
        report = analyze_snapshot_density(snaps, window_days=30)
        assert report.total_snapshots == 0

    def test_avg_per_day_calculation(self):
        snaps = [{"created_at": _ts(i)} for i in range(30)]
        report = analyze_snapshot_density(snaps, window_days=30)
        assert report.avg_per_day == pytest.approx(1.0)

    def test_peak_day_identified(self):
        # Dump 5 snapshots on same day, 1 on each other day
        today_ts = datetime.now(UTC).replace(hour=12).isoformat()
        snaps = [{"created_at": today_ts} for _ in range(5)]
        snaps += [{"created_at": _ts(i + 1)} for i in range(10)]
        report = analyze_snapshot_density(snaps, window_days=30)
        assert report.peak_day_count >= 5

    def test_to_dict_structure(self):
        d = analyze_snapshot_density([]).to_dict()
        assert "total_snapshots" in d
        assert "avg_per_day" in d
        assert "peak_day" in d
        assert "burst_periods" in d
        assert "sparse_periods" in d

    def test_invalid_timestamp_skipped(self):
        snaps = [{"created_at": "not-a-date"}, {"created_at": _ts(1)}]
        report = analyze_snapshot_density(snaps, window_days=30)
        assert report.total_snapshots == 1


class TestAssessArchivePressure:
    def test_ok_pressure_low_fraction(self):
        indicator = assess_archive_pressure(50, 200)
        assert indicator.pressure_level == "ok"

    def test_warning_at_threshold(self):
        indicator = assess_archive_pressure(165, 200)  # 82.5% > 80% warning
        assert indicator.pressure_level in ("warning", "critical")

    def test_critical_at_threshold(self):
        indicator = assess_archive_pressure(192, 200)  # 96% > 95% critical
        assert indicator.pressure_level == "critical"

    def test_no_days_forecast_without_rate(self):
        indicator = assess_archive_pressure(50, 200, snapshots_per_day=0.0)
        assert indicator.days_to_warning is None
        assert indicator.days_to_critical is None

    def test_days_to_warning_computed(self):
        # 50/200 = 25%, warning at 80% = 160, need 110 more at 5/day = 22 days
        indicator = assess_archive_pressure(50, 200, snapshots_per_day=5.0)
        assert indicator.days_to_warning is not None
        assert indicator.days_to_warning == pytest.approx(22.0, abs=0.5)

    def test_days_to_critical_computed(self):
        indicator = assess_archive_pressure(50, 200, snapshots_per_day=5.0)
        assert indicator.days_to_critical is not None

    def test_already_at_warning_no_days_to_warning(self):
        indicator = assess_archive_pressure(165, 200, snapshots_per_day=5.0)
        # Already above warning threshold
        assert indicator.days_to_warning is None

    def test_fraction_accurate(self):
        indicator = assess_archive_pressure(100, 200)
        assert indicator.current_fraction == pytest.approx(0.5)

    def test_to_dict_structure(self):
        d = assess_archive_pressure(100, 200).to_dict()
        assert "pressure_level" in d
        assert "current_fraction" in d
        assert "days_to_warning" in d
        assert "days_to_critical" in d

    def test_observations_nonempty(self):
        indicator = assess_archive_pressure(100, 200)
        assert indicator.observations
