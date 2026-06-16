"""Tests for reports/maintenance.py — maintenance report generators."""

from __future__ import annotations

from reports.maintenance import (
    generate_deployment_readiness_report,
    generate_maintenance_report,
    generate_retention_summary,
    generate_scheduler_health_report,
    generate_storage_growth_report,
)


def _selfcheck_ok() -> dict:
    return {
        "overall_status": "ok",
        "passed": 5,
        "failed": 0,
        "total": 5,
        "items": [
            {
                "name": "Scheduler Health",
                "passed": True,
                "message": "Running",
                "severity": "ok",
                "details": {},
            }
        ],
    }


def _selfcheck_warn() -> dict:
    return {
        "overall_status": "warning",
        "passed": 4,
        "failed": 1,
        "total": 5,
        "items": [
            {
                "name": "Latest Snapshot Freshness",
                "passed": False,
                "message": "Snapshot is stale",
                "severity": "warning",
                "details": {"age_minutes": 45},
            }
        ],
    }


def _storage() -> dict:
    return {
        "pressure_level": "ok",
        "disk_usage_percent": 35.0,
        "db_size_human": "12.0 MB",
        "snapshot_count": 15,
        "max_snapshot_count": 200,
        "observations": ["Storage pressure normal."],
    }


def _scheduler_health() -> dict:
    return {
        "running": True,
        "overall_status": "ok",
        "job_count": 1,
        "degraded_jobs": [],
        "stale_jobs": [],
        "jobs": [
            {
                "id": "scan_123",
                "status": "ok",
                "last_success": "2026-05-16T10:00:00+00:00",
                "consecutive_errors": 0,
                "total_runs": 42,
                "next_run": "2026-05-16T10:05:00+00:00",
            }
        ],
    }


def _retention_result() -> dict:
    return {
        "executed": False,
        "message": "Dry run: 3 snapshot(s) identified for deletion.",
        "deleted_ids": [],
        "plan": {
            "total_snapshots": 15,
            "deletion_count": 3,
            "kept_count": 12,
            "dry_run": True,
            "candidates": [
                {"id": 1, "created_at": "2026-04-01 10:00:00", "reason": "too_old"}
            ],
            "policy": {
                "retention_days": 30,
                "max_snapshot_count": 200,
                "min_keep_count": 10,
                "dry_run": True,
            },
            "generated_at": "2026-05-16T10:00:00+00:00",
        },
    }


class TestGenerateMaintenanceReport:
    def test_returns_string(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_ok())
        assert isinstance(md, str)

    def test_contains_header(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_ok())
        assert "Maintenance Report" in md

    def test_contains_status(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_ok())
        assert "OK" in md

    def test_includes_storage_section(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_ok(), storage=_storage())
        assert "Storage" in md
        assert "35.0" in md

    def test_includes_scheduler_section(self):
        md = generate_maintenance_report(
            selfcheck=_selfcheck_ok(), scheduler=_scheduler_health()
        )
        assert "Scheduler" in md

    def test_includes_retention_section(self):
        plan = _retention_result()["plan"]
        md = generate_maintenance_report(
            selfcheck=_selfcheck_ok(), retention_plan=plan
        )
        assert "Retention" in md

    def test_warning_status_shown(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_warn())
        assert "WARNING" in md

    def test_advisory_footer(self):
        md = generate_maintenance_report(selfcheck=_selfcheck_ok())
        assert "Advisory only" in md


class TestGenerateRetentionSummary:
    def test_returns_string(self):
        md = generate_retention_summary(_retention_result())
        assert isinstance(md, str)

    def test_dry_run_note(self):
        md = generate_retention_summary(_retention_result())
        assert "dry run" in md.lower() or "Dry run" in md

    def test_executed_true_no_dry_run_note(self):
        result = _retention_result()
        result["executed"] = True
        result["message"] = "Deleted 3 snapshot(s)."
        result["deleted_ids"] = [1, 2, 3]
        md = generate_retention_summary(result)
        assert "Deleted" in md or "3" in md


class TestGenerateSchedulerHealthReport:
    def test_returns_string(self):
        md = generate_scheduler_health_report(_scheduler_health())
        assert isinstance(md, str)

    def test_contains_running_status(self):
        md = generate_scheduler_health_report(_scheduler_health())
        assert "yes" in md or "running" in md.lower()

    def test_contains_job_id(self):
        md = generate_scheduler_health_report(_scheduler_health())
        assert "scan_123" in md

    def test_stopped_scheduler_warning(self):
        health = _scheduler_health()
        health["running"] = False
        md = generate_scheduler_health_report(health)
        assert "WARNING" in md or "not running" in md


class TestGenerateStorageGrowthReport:
    def test_returns_string(self):
        md = generate_storage_growth_report(_storage())
        assert isinstance(md, str)

    def test_contains_disk_usage(self):
        md = generate_storage_growth_report(_storage())
        assert "35" in md

    def test_contains_pressure_level(self):
        md = generate_storage_growth_report(_storage())
        assert "OK" in md or "ok" in md.lower()

    def test_growth_section_when_provided(self):
        growth = {
            "db_growth_bytes": 50000,
            "db_growth_human": "50.0 KB",
            "snapshot_growth": 5,
            "window_description": "2026-05-01 → 2026-05-16",
            "observations": ["Database grew by 50.0 KB."],
        }
        md = generate_storage_growth_report(_storage(), growth=growth)
        assert "Growth" in md
        assert "50.0 KB" in md


class TestGenerateDeploymentReadinessReport:
    def test_ready_verdict(self):
        md = generate_deployment_readiness_report(selfcheck=_selfcheck_ok())
        assert "READY" in md

    def test_not_ready_verdict(self):
        md = generate_deployment_readiness_report(selfcheck=_selfcheck_warn())
        assert "NOT READY" in md

    def test_includes_profile_info(self):
        profile = {
            "name": "standard",
            "scan_interval_seconds": 300,
            "retention_days": 30,
            "max_snapshot_count": 200,
            "runtime_scanning_enabled": True,
        }
        md = generate_deployment_readiness_report(
            selfcheck=_selfcheck_ok(), profile_name="standard", profile_info=profile
        )
        assert "standard" in md
        assert "300" in md
