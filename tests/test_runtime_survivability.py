"""Tests for tools/runtime_survivability.py — long-running survivability checker."""

from __future__ import annotations

from tools.runtime_survivability import (
    RuntimeSurvivabilityChecker,
    SurvivabilityReport,
    days_since,
)


def _checker() -> RuntimeSurvivabilityChecker:
    return RuntimeSurvivabilityChecker()


def _default_check(**overrides) -> SurvivabilityReport:
    defaults = {
        "db_size_bytes": 10 * 1024 * 1024,
        "db_size_bytes_7d_ago": 9 * 1024 * 1024,
        "snapshot_count": 50,
        "oldest_snapshot_days": 20,
        "llm_event_count": 1000,
        "oldest_event_days": 15,
        "scheduler_health": {"status": "ok", "stale_jobs": [], "degraded_jobs": [], "running_jobs": 1},
        "archived_project_ids": [],
        "archived_project_last_activity_days": {},
        "events_last_hour_by_project": {"proj-a": 100},
        "events_last_hour_7d_ago": {"proj-a": 95},
    }
    defaults.update(overrides)
    return _checker().check(**defaults)


class TestAllChecksPassing:
    def test_all_ok_produces_ok_status(self):
        report = _default_check()
        assert report.overall_status == "ok"
        assert report.long_term_outlook == "stable"
        assert report.passed >= 4

    def test_report_has_10_checks(self):
        report = _default_check()
        assert len(report.checks) == 10

    def test_to_dict_serializable(self):
        report = _default_check()
        d = report.to_dict()
        assert "overall_status" in d
        assert "checks" in d
        assert "advisory" in d

    def test_markdown_output(self):
        report = _default_check()
        md = report.markdown()
        assert "# Runtime Survivability Report" in md
        assert "Database Growth Rate" in md


class TestDatabaseGrowth:
    def test_no_historical_data_passes(self):
        report = _default_check(db_size_bytes_7d_ago=None)
        check = next(c for c in report.checks if c.name == "Database Growth Rate")
        assert check.passed is True

    def test_normal_growth_passes(self):
        # 1 MB over 7 days = ~140 KB/day (under 10 MB/day threshold)
        report = _default_check(
            db_size_bytes=10 * 1024 * 1024,
            db_size_bytes_7d_ago=9 * 1024 * 1024,
        )
        check = next(c for c in report.checks if c.name == "Database Growth Rate")
        assert check.passed is True

    def test_high_growth_warns(self):
        # 100 MB over 7 days = ~14 MB/day (over 10 MB/day threshold)
        report = _default_check(
            db_size_bytes=200 * 1024 * 1024,
            db_size_bytes_7d_ago=100 * 1024 * 1024,
        )
        check = next(c for c in report.checks if c.name == "Database Growth Rate")
        assert not check.passed
        assert check.severity in ("warning", "critical")

    def test_critical_growth_raises_critical(self):
        # 400 MB over 7 days = ~57 MB/day (over 50 MB/day threshold)
        report = _default_check(
            db_size_bytes=500 * 1024 * 1024,
            db_size_bytes_7d_ago=100 * 1024 * 1024,
        )
        check = next(c for c in report.checks if c.name == "Database Growth Rate")
        assert check.severity == "critical"

    def test_db_shrinkage_passes(self):
        report = _default_check(
            db_size_bytes=5 * 1024 * 1024,
            db_size_bytes_7d_ago=20 * 1024 * 1024,
        )
        check = next(c for c in report.checks if c.name == "Database Growth Rate")
        assert check.passed is True


class TestRetentionBacklog:
    def test_no_backlog_passes(self):
        report = _default_check(oldest_snapshot_days=20, oldest_event_days=15)
        check = next(c for c in report.checks if c.name == "Retention Backlog")
        assert check.passed is True

    def test_old_snapshot_warns(self):
        report = _default_check(oldest_snapshot_days=50)
        check = next(c for c in report.checks if c.name == "Retention Backlog")
        assert not check.passed

    def test_very_old_snapshot_critical(self):
        report = _default_check(oldest_snapshot_days=100)
        check = next(c for c in report.checks if c.name == "Retention Backlog")
        assert check.severity == "critical"

    def test_no_age_data_passes(self):
        report = _default_check(oldest_snapshot_days=None, oldest_event_days=None)
        check = next(c for c in report.checks if c.name == "Retention Backlog")
        assert check.passed is True


class TestSchedulerHealth:
    def test_healthy_scheduler_passes(self):
        report = _default_check(
            scheduler_health={"status": "ok", "stale_jobs": [], "degraded_jobs": [], "running_jobs": 2}
        )
        check = next(c for c in report.checks if c.name == "Scheduler Health")
        assert check.passed is True

    def test_degraded_job_raises_critical(self):
        report = _default_check(
            scheduler_health={
                "status": "degraded",
                "stale_jobs": [],
                "degraded_jobs": ["scan-job"],
                "running_jobs": 0,
            }
        )
        check = next(c for c in report.checks if c.name == "Scheduler Health")
        assert not check.passed
        assert check.severity == "critical"

    def test_stale_jobs_warn(self):
        report = _default_check(
            scheduler_health={
                "status": "ok",
                "stale_jobs": ["old-job"],
                "degraded_jobs": [],
                "running_jobs": 1,
            }
        )
        check = next(c for c in report.checks if c.name == "Scheduler Health")
        assert not check.passed
        assert check.severity == "warning"

    def test_none_scheduler_passes(self):
        report = _default_check(scheduler_health=None)
        check = next(c for c in report.checks if c.name == "Scheduler Health")
        assert check.passed is True


class TestStaleArchives:
    def test_no_archives_passes(self):
        report = _default_check(
            archived_project_ids=[],
            archived_project_last_activity_days={},
        )
        check = next(c for c in report.checks if c.name == "Stale Archived Projects")
        assert check.passed is True

    def test_recent_archive_passes(self):
        report = _default_check(
            archived_project_ids=["old-proj"],
            archived_project_last_activity_days={"old-proj": 30},
        )
        check = next(c for c in report.checks if c.name == "Stale Archived Projects")
        assert check.passed is True

    def test_stale_archive_warns(self):
        report = _default_check(
            archived_project_ids=["stale-proj"],
            archived_project_last_activity_days={"stale-proj": 200},
        )
        check = next(c for c in report.checks if c.name == "Stale Archived Projects")
        assert not check.passed
        assert check.severity == "warning"


class TestIngestionTrend:
    def test_stable_ingestion_passes(self):
        report = _default_check(
            events_last_hour_by_project={"proj-a": 100},
            events_last_hour_7d_ago={"proj-a": 95},
        )
        check = next(c for c in report.checks if c.name == "Ingestion Pressure Trend")
        assert check.passed is True

    def test_no_historical_data_passes(self):
        report = _default_check(events_last_hour_7d_ago=None)
        check = next(c for c in report.checks if c.name == "Ingestion Pressure Trend")
        assert check.passed is True

    def test_growing_ingestion_warns(self):
        report = _default_check(
            events_last_hour_by_project={"proj-a": 1000},
            events_last_hour_7d_ago={"proj-a": 200},
        )
        check = next(c for c in report.checks if c.name == "Ingestion Pressure Trend")
        assert not check.passed

    def test_no_current_ingestion_passes(self):
        report = _default_check(
            events_last_hour_by_project={},
            events_last_hour_7d_ago={},
        )
        check = next(c for c in report.checks if c.name == "Ingestion Pressure Trend")
        assert check.passed is True


class TestOverallStatus:
    def test_critical_check_produces_critical_status(self):
        report = _default_check(
            db_size_bytes=500 * 1024 * 1024,
            db_size_bytes_7d_ago=100 * 1024 * 1024,
        )
        assert report.overall_status == "critical"
        assert report.long_term_outlook == "intervention_recommended"

    def test_warning_check_produces_warning_status(self):
        report = _default_check(oldest_snapshot_days=50)
        assert report.overall_status == "warning"
        assert report.long_term_outlook == "attention_needed"

    def test_all_ok_produces_stable_outlook(self):
        report = _default_check()
        assert report.long_term_outlook == "stable"


class TestDaysSince:
    def test_none_returns_none(self):
        assert days_since(None) is None

    def test_recent_timestamp_returns_small_number(self):
        from datetime import UTC, datetime, timedelta
        recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        result = days_since(recent)
        assert result is not None
        assert abs(result - 3) <= 1

    def test_old_timestamp_returns_large_number(self):
        result = days_since("2020-01-01T00:00:00Z")
        assert result is not None
        assert result > 365 * 5

    def test_unparseable_returns_none(self):
        assert days_since("not-a-date") is None
