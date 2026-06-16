"""Tests for tools/maintenance_assistant.py."""


from tools.maintenance_assistant import (
    MaintenanceAssistant,
    MaintenanceChecklist,
)


def _assistant(**kwargs) -> MaintenanceChecklist:
    return MaintenanceAssistant().generate(**kwargs)


class TestEmptyInputs:
    def test_empty_inputs_produces_checklist(self):
        checklist = _assistant()
        assert isinstance(checklist, MaintenanceChecklist)
        assert checklist.total == 0

    def test_empty_checklist_has_no_critical(self):
        checklist = _assistant()
        assert not checklist.requires_immediate_attention

    def test_empty_checklist_has_info_note(self):
        checklist = _assistant()
        assert len(checklist.notes) > 0


class TestSurvivabilityActions:
    def _survivability_report(self, status: str, checks: list[dict]) -> dict:
        return {"overall_status": status, "checks": checks}

    def test_critical_survivability_generates_critical_action(self):
        report = self._survivability_report("critical", [
            {"name": "Retention Backlog", "severity": "critical",
             "message": "Very old data accumulating.", "evidence": []}
        ])
        checklist = _assistant(survivability_report=report)
        assert checklist.critical_count > 0

    def test_warning_survivability_generates_high_action(self):
        report = self._survivability_report("warning", [
            {"name": "Database Growth Rate", "severity": "warning",
             "message": "DB growing fast.", "evidence": ["10 MB/day"]}
        ])
        checklist = _assistant(survivability_report=report)
        assert checklist.high_count > 0 or checklist.critical_count > 0

    def test_ok_checks_produce_no_actions(self):
        report = self._survivability_report("ok", [
            {"name": "Retention Backlog", "severity": "ok", "message": "Fine.", "evidence": []}
        ])
        checklist = _assistant(survivability_report=report)
        assert checklist.total == 0


class TestScalingActions:
    def _scaling_report(self, checks: list[dict]) -> dict:
        return {"checks": checks}

    def test_critical_scaling_produces_critical_action(self):
        report = self._scaling_report([
            {"name": "Snapshot Volume", "severity": "critical",
             "message": "20k snapshots exceeded.", "recommendations": ["Run retention."]}
        ])
        checklist = _assistant(scaling_report=report)
        assert checklist.critical_count > 0

    def test_warning_scaling_produces_medium_action(self):
        report = self._scaling_report([
            {"name": "LLM Event Volume", "severity": "warning",
             "message": "Approaching limit.", "recommendations": []}
        ])
        checklist = _assistant(scaling_report=report)
        assert checklist.medium_count > 0

    def test_ok_scaling_produces_no_actions(self):
        report = self._scaling_report([
            {"name": "Snapshot Volume", "severity": "ok",
             "message": "Fine.", "recommendations": []}
        ])
        checklist = _assistant(scaling_report=report)
        assert checklist.total == 0


class TestQualityActions:
    def test_poor_quality_produces_high_action(self):
        report = {
            "quality_band": "poor",
            "quality_score": 0.25,
            "integration_warnings": ["Missing latency data."],
            "improvement_suggestions": ["Add latency_ms to events."],
        }
        checklist = _assistant(ingestion_quality_report=report)
        assert checklist.high_count > 0

    def test_fair_quality_produces_medium_action(self):
        report = {
            "quality_band": "fair",
            "quality_score": 0.55,
            "integration_warnings": [],
            "improvement_suggestions": ["Use descriptive workflow names."],
        }
        checklist = _assistant(ingestion_quality_report=report)
        assert checklist.medium_count > 0

    def test_good_quality_produces_no_actions(self):
        report = {
            "quality_band": "good",
            "quality_score": 0.80,
            "integration_warnings": [],
            "improvement_suggestions": [],
        }
        checklist = _assistant(ingestion_quality_report=report)
        assert checklist.total == 0


class TestStaleWorkflows:
    def test_stale_workflows_produce_low_actions(self):
        checklist = _assistant(stale_workflows=["test_workflow", "ocr_v1"])
        assert checklist.low_count >= 2

    def test_each_workflow_gets_one_action(self):
        stale = ["wf_a", "wf_b", "wf_c"]
        checklist = _assistant(stale_workflows=stale)
        wf_actions = [a for a in checklist.actions if a.category == "ingestion"
                      and "Stale Workflow" in a.title]
        assert len(wf_actions) == 3


class TestNoisyProjects:
    def test_noisy_projects_produce_medium_actions(self):
        checklist = _assistant(noisy_projects=["proj_alpha"])
        noisy = [a for a in checklist.actions if "Noisy Project" in a.title]
        assert len(noisy) == 1
        assert noisy[0].priority == "medium"


class TestStaleArchives:
    def test_stale_archives_produce_low_actions(self):
        checklist = _assistant(
            archived_project_ids=["old-proj"],
            archived_project_last_activity_days={"old-proj": 200},
        )
        arch = [a for a in checklist.actions if "Stale Archive" in a.title]
        assert len(arch) == 1
        assert arch[0].priority == "low"

    def test_recent_archive_produces_no_action(self):
        checklist = _assistant(
            archived_project_ids=["recent-proj"],
            archived_project_last_activity_days={"recent-proj": 30},
        )
        arch = [a for a in checklist.actions if "Stale Archive" in a.title]
        assert len(arch) == 0


class TestRetentionOverdue:
    def test_overdue_14d_produces_medium_action(self):
        checklist = _assistant(retention_last_run_days=15)
        ret = [a for a in checklist.actions if "Retention Not Run" in a.title]
        assert len(ret) == 1
        assert ret[0].priority in ("medium", "high")

    def test_overdue_31d_produces_high_action(self):
        checklist = _assistant(retention_last_run_days=35)
        ret = [a for a in checklist.actions if "Retention Not Run" in a.title]
        assert len(ret) == 1
        assert ret[0].priority == "high"

    def test_not_overdue_produces_no_action(self):
        checklist = _assistant(retention_last_run_days=5)
        ret = [a for a in checklist.actions if "Retention Not Run" in a.title]
        assert len(ret) == 0


class TestSchedulerDegraded:
    def test_degraded_scheduler_produces_high_action(self):
        checklist = _assistant(scheduler_degraded_jobs=["scan_job", "report_job"])
        sched = [a for a in checklist.actions if "Scheduler Degradation" in a.title]
        assert len(sched) == 1
        assert sched[0].priority == "high"


class TestDbSize:
    def test_large_db_produces_medium_action(self):
        checklist = _assistant(db_size_bytes=150 * 1024 * 1024)  # 150 MB
        db = [a for a in checklist.actions if "Database Size" in a.title]
        assert len(db) == 1

    def test_very_large_db_produces_high_action(self):
        checklist = _assistant(db_size_bytes=600 * 1024 * 1024)  # 600 MB
        db = [a for a in checklist.actions if "Database Size" in a.title]
        assert len(db) == 1
        assert db[0].priority == "high"

    def test_small_db_no_action(self):
        checklist = _assistant(db_size_bytes=50 * 1024 * 1024)
        db = [a for a in checklist.actions if "Database Size" in a.title]
        assert len(db) == 0


class TestSorting:
    def test_actions_sorted_by_priority(self):
        from tools.maintenance_assistant import _PRIORITY_ORDER
        checklist = _assistant(
            stale_workflows=["wf"],
            retention_last_run_days=35,
        )
        priorities = [_PRIORITY_ORDER.get(a.priority, 99) for a in checklist.actions]
        assert priorities == sorted(priorities)


class TestToDict:
    def test_to_dict_structure(self):
        checklist = _assistant(retention_last_run_days=20)
        d = checklist.to_dict()
        assert "actions" in d
        assert "critical_count" in d
        assert "high_count" in d
        assert "total" in d
        assert "advisory" in d

    def test_action_to_dict(self):
        checklist = _assistant(retention_last_run_days=20)
        action = checklist.actions[0].to_dict()
        assert "action_id" in action
        assert "priority" in action
        assert "category" in action
        assert "title" in action
        assert "description" in action


class TestMarkdown:
    def test_markdown_has_header(self):
        checklist = _assistant(retention_last_run_days=20)
        md = checklist.markdown()
        assert "# Maintenance Checklist" in md

    def test_markdown_has_advisory(self):
        checklist = _assistant()
        md = checklist.markdown()
        assert "Advisory only" in md

    def test_markdown_for_empty_checklist(self):
        checklist = _assistant()
        md = checklist.markdown()
        assert "No maintenance actions" in md

    def test_markdown_groups_by_priority(self):
        checklist = _assistant(
            scheduler_degraded_jobs=["job1"],  # high
            stale_workflows=["wf1"],           # low
        )
        md = checklist.markdown()
        high_pos = md.find("## HIGH Priority")
        low_pos = md.find("## LOW Priority")
        assert high_pos < low_pos
