"""Tests for RecurrenceEngine."""

from cognition.recurrence import RecurrenceEngine


def _make_snapshot(snap_id: int, created_at: str, **data_overrides) -> dict:
    data = {
        "recommendations": [],
        "cost_observations": [],
        "scanner_results": {"results": {"runtime_scanner": {}}},
    }
    data.update(data_overrides)
    return {"id": snap_id, "created_at": created_at, "data": data}


def _rec(title: str, category: str = "security", confidence: float = 0.8) -> dict:
    return {"title": title, "category": category, "confidence": confidence, "impact": "high"}


def _cost_obs(observation: str, severity: str = "high") -> dict:
    return {"observation": observation, "severity": severity, "component": "llm"}


class TestRecurrenceEngine:
    def test_empty_snapshots_returns_empty(self):
        assert RecurrenceEngine().detect([]) == []

    def test_single_snapshot_returns_empty(self):
        snap = _make_snapshot(1, "2026-01-01T00:00:00")
        assert RecurrenceEngine().detect([snap]) == []

    def test_repeated_recommendation_detected(self):
        rec = _rec("Rotate API keys", "security")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", recommendations=[rec]),
            _make_snapshot(2, "2026-01-02T00:00:00", recommendations=[rec]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        rec_issues = [i for i in issues if i.kind == "recommendation"]
        assert len(rec_issues) >= 1
        assert rec_issues[0].occurrences == 2

    def test_single_occurrence_not_detected(self):
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", recommendations=[_rec("Only once")]),
            _make_snapshot(2, "2026-01-02T00:00:00", recommendations=[]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        rec_issues = [i for i in issues if i.kind == "recommendation"]
        assert all(i.occurrences >= 2 for i in rec_issues)

    def test_cost_warning_recurrence_detected(self):
        obs = _cost_obs("High token consumption in retry loop", "high")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", cost_observations=[obs]),
            _make_snapshot(2, "2026-01-02T00:00:00", cost_observations=[obs]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        cost_issues = [i for i in issues if i.kind == "cost_warning"]
        assert len(cost_issues) >= 1
        assert cost_issues[0].occurrences == 2

    def test_low_severity_cost_obs_not_detected(self):
        obs = _cost_obs("Minor observation", "low")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", cost_observations=[obs]),
            _make_snapshot(2, "2026-01-02T00:00:00", cost_observations=[obs]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        cost_issues = [i for i in issues if i.kind == "cost_warning"]
        assert len(cost_issues) == 0

    def test_runtime_failure_recurrence_detected(self):
        runtime = {"failed_services": ["nginx.service"]}
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00",
                           scanner_results={"results": {"runtime_scanner": runtime}}),
            _make_snapshot(2, "2026-01-02T00:00:00",
                           scanner_results={"results": {"runtime_scanner": runtime}}),
        ]
        issues = RecurrenceEngine().detect(snaps)
        rt_issues = [i for i in issues if i.kind == "runtime_failure"]
        assert len(rt_issues) >= 1
        assert rt_issues[0].pattern == "Service 'nginx.service' repeatedly failing"
        assert rt_issues[0].occurrences == 2

    def test_runtime_failure_once_not_detected(self):
        runtime = {"failed_services": ["nginx.service"]}
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00",
                           scanner_results={"results": {"runtime_scanner": runtime}}),
            _make_snapshot(2, "2026-01-02T00:00:00",
                           scanner_results={"results": {"runtime_scanner": {}}}),
        ]
        issues = RecurrenceEngine().detect(snaps)
        rt_issues = [i for i in issues if i.kind == "runtime_failure"]
        assert len(rt_issues) == 0

    def test_issues_sorted_by_occurrence_count_descending(self):
        rec_a = _rec("Issue A")
        rec_b = _rec("Issue B")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", recommendations=[rec_a, rec_b]),
            _make_snapshot(2, "2026-01-02T00:00:00", recommendations=[rec_a, rec_b]),
            _make_snapshot(3, "2026-01-03T00:00:00", recommendations=[rec_a]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        occurrences = [i.occurrences for i in issues]
        assert occurrences == sorted(occurrences, reverse=True)

    def test_first_and_last_seen_populated(self):
        rec = _rec("Track dates")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", recommendations=[rec]),
            _make_snapshot(2, "2026-01-02T00:00:00", recommendations=[rec]),
            _make_snapshot(3, "2026-01-03T00:00:00", recommendations=[rec]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        assert issues
        issue = issues[0]
        assert issue.first_seen == "2026-01-01T00:00:00"
        assert issue.last_seen == "2026-01-03T00:00:00"

    def test_severity_hint_high_for_frequent(self):
        rec = _rec("Frequent issue")
        snaps = [_make_snapshot(i, f"2026-01-0{i}T00:00:00", recommendations=[rec]) for i in range(1, 6)]
        issues = RecurrenceEngine().detect(snaps)
        rec_issues = [i for i in issues if i.kind == "recommendation"]
        assert rec_issues[0].severity_hint == "high"

    def test_to_dict_structure(self):
        rec = _rec("Serialize me")
        snaps = [
            _make_snapshot(1, "2026-01-01T00:00:00", recommendations=[rec]),
            _make_snapshot(2, "2026-01-02T00:00:00", recommendations=[rec]),
        ]
        issues = RecurrenceEngine().detect(snaps)
        assert issues
        d = issues[0].to_dict()
        assert "kind" in d
        assert "pattern" in d
        assert "occurrences" in d
        assert "snapshot_ids" in d
        assert "first_seen" in d
        assert "last_seen" in d
        assert "evidence" in d
        assert "severity_hint" in d
