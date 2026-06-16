"""Tests for tools/selfcheck.py — system self-check."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tools.selfcheck import SelfCheckItem, SelfCheckReport, SystemSelfChecker


def _fresh_snapshot() -> dict:
    return {"id": 1, "created_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")}


def _stale_snapshot() -> dict:
    ts = datetime.now(UTC) - timedelta(hours=2)
    return {"id": 1, "created_at": ts.strftime("%Y-%m-%d %H:%M:%S")}


def _scheduler_ok() -> dict:
    return {
        "running": True,
        "overall_status": "ok",
        "job_count": 1,
        "degraded_jobs": [],
        "stale_jobs": [],
        "jobs": [],
    }


def _storage_ok() -> dict:
    return {
        "pressure_level": "ok",
        "disk_usage_percent": 30.0,
        "snapshot_count": 10,
        "max_snapshot_count": 200,
        "snapshot_count_fraction": 0.05,
        "observations": ["Storage pressure normal."],
    }


class TestSelfCheckItem:
    def test_to_dict_keys(self):
        item = SelfCheckItem(
            name="Test Check", passed=True, message="All good", severity="ok"
        )
        d = item.to_dict()
        assert "name" in d
        assert "passed" in d
        assert "message" in d
        assert "severity" in d
        assert "details" in d


class TestSelfCheckReport:
    def test_passed_count(self):
        items = [
            SelfCheckItem("A", True, "ok", "ok"),
            SelfCheckItem("B", False, "bad", "warning"),
        ]
        report = SelfCheckReport(items=items, overall_status="warning")
        assert report.passed_count == 1
        assert report.failed_count == 1

    def test_to_dict_advisory(self):
        items = [SelfCheckItem("A", True, "ok", "ok")]
        report = SelfCheckReport(items=items, overall_status="ok")
        d = report.to_dict()
        assert "advisory" in d

    def test_markdown_returns_string(self):
        items = [SelfCheckItem("Scheduler", True, "Running.", "ok")]
        report = SelfCheckReport(items=items, overall_status="ok")
        md = report.markdown()
        assert isinstance(md, str)
        assert "Self-Check" in md


class TestSystemSelfChecker:
    def setup_method(self):
        self.checker = SystemSelfChecker()

    def test_all_ok(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        assert report.overall_status == "ok"
        assert report.passed_count == 5

    def test_scheduler_stopped_gives_critical(self):
        bad_scheduler = {
            "running": False,
            "overall_status": "stopped",
            "job_count": 0,
            "degraded_jobs": [],
            "stale_jobs": [],
        }
        report = self.checker.run(
            scheduler_health=bad_scheduler,
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        assert report.overall_status == "critical"

    def test_no_snapshot_gives_warning(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=None,
            snapshot_count=0,
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        # no snapshot → warning
        failed = [i for i in report.items if not i.passed]
        names = [i.name for i in failed]
        assert any("Snapshot" in n or "Fresh" in n for n in names)

    def test_stale_snapshot_gives_warning(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_stale_snapshot(),
            snapshot_count=5,
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        failed = [i for i in report.items if not i.passed]
        assert any("Freshness" in i.name or "Stale" in i.name or i.severity == "warning" for i in failed)

    def test_high_snapshot_count_gives_warning(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=170,  # 85% of 200
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        count_items = [i for i in report.items if "Count" in i.name]
        assert len(count_items) == 1
        assert not count_items[0].passed

    def test_critical_snapshot_count(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=195,  # 97.5% of 200
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        count_items = [i for i in report.items if "Count" in i.name]
        assert count_items[0].severity == "critical"
        assert report.overall_status == "critical"

    def test_critical_storage_gives_critical(self):
        bad_storage = {
            "pressure_level": "critical",
            "disk_usage_percent": 90.0,
            "observations": ["Critical disk pressure"],
        }
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
            storage_estimate=bad_storage,
        )
        assert report.overall_status == "critical"

    def test_scheduler_degraded_gives_warning(self):
        degraded = {
            "running": True,
            "overall_status": "degraded",
            "job_count": 1,
            "degraded_jobs": ["scan_123"],
            "stale_jobs": [],
        }
        report = self.checker.run(
            scheduler_health=degraded,
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
            storage_estimate=_storage_ok(),
        )
        sched_items = [i for i in report.items if "Scheduler" in i.name]
        assert not sched_items[0].passed
        assert sched_items[0].severity == "warning"

    def test_none_scheduler_gives_warning(self):
        report = self.checker.run(
            scheduler_health=None,
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
        )
        sched_items = [i for i in report.items if "Scheduler" in i.name]
        assert not sched_items[0].passed

    def test_schema_error_gives_warning(self):
        bad_schema = {
            "valid": False,
            "violations": [{"severity": "error", "field": "id", "message": "missing"}],
        }
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
            schema_validation=bad_schema,
        )
        schema_items = [i for i in report.items if "Schema" in i.name]
        assert not schema_items[0].passed

    def test_to_dict_total(self):
        report = self.checker.run(
            scheduler_health=_scheduler_ok(),
            latest_snapshot=_fresh_snapshot(),
            snapshot_count=10,
            max_snapshot_count=200,
        )
        d = report.to_dict()
        assert d["total"] == 5  # 5 checks defined
