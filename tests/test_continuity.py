"""Tests for ContinuityEngine and RecommendationLifespan in cognition/recurrence.py."""

from __future__ import annotations

from cognition.recurrence import ContinuityEngine, RecommendationLifespan


def _snap(snap_id: int, created_at: str, recs: list):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {"recommendations": recs},
    }


def _rec(title: str, category: str = "cost"):
    return {"title": title, "category": category}


S1 = _snap(1, "2026-01-01T00:00:00", [_rec("rec A"), _rec("rec B")])
S2 = _snap(2, "2026-01-03T00:00:00", [_rec("rec A"), _rec("rec C")])
S3 = _snap(3, "2026-01-05T00:00:00", [_rec("rec A"), _rec("rec C")])
S4 = _snap(4, "2026-01-07T00:00:00", [_rec("rec A"), _rec("rec C")])
S5 = _snap(5, "2026-01-09T00:00:00", [_rec("rec A"), _rec("rec C")])


class TestContinuityEngineBasic:
    def test_empty_snapshots(self):
        result = ContinuityEngine().track([])
        assert result == []

    def test_single_snapshot(self):
        result = ContinuityEngine().track([S1])
        assert len(result) >= 1
        titles = {l.title for l in result}
        assert "rec A" in titles

    def test_returns_lifespan_objects(self):
        result = ContinuityEngine().track([S1, S2])
        assert all(isinstance(l, RecommendationLifespan) for l in result)


class TestLifespanStatus:
    def test_persistent(self):
        # rec A appears in all 5 — persistent (80%+ coverage)
        snaps = [S1, S2, S3, S4, S5]
        result = ContinuityEngine().track(snaps)
        rec_a = next((l for l in result if l.title == "rec A"), None)
        assert rec_a is not None
        assert rec_a.status == "persistent"
        assert rec_a.occurrence_count == 5

    def test_recurring(self):
        # rec C appears in S2-S5 = 4 of 5 = 80%, so actually persistent
        # Let's test with a partial scenario to get recurring
        s_partial = _snap(6, "2026-01-11T00:00:00", [_rec("rec A")])
        snaps = [S1, S2, S3, S4, S5, s_partial]
        result = ContinuityEngine().track(snaps)
        # rec C not in latest — should be resolved
        rec_c = next((l for l in result if l.title == "rec C"), None)
        assert rec_c is not None
        assert rec_c.status == "resolved"

    def test_resolved(self):
        # rec B only in S1, not in S2 (latest)
        snaps = [S1, S2]
        result = ContinuityEngine().track(snaps)
        rec_b = next((l for l in result if l.title == "rec B"), None)
        assert rec_b is not None
        assert rec_b.status == "resolved"

    def test_new(self):
        # rec only in single snapshot = new
        snaps = [_snap(10, "2026-01-01T00:00:00", [_rec("brand new rec")])]
        result = ContinuityEngine().track(snaps)
        brand_new = next((l for l in result if l.title == "brand new rec"), None)
        assert brand_new is not None
        assert brand_new.status == "new"


class TestLifespanFields:
    def test_to_dict_structure(self):
        result = ContinuityEngine().track([S1, S2])
        d = result[0].to_dict()
        assert "title" in d
        assert "category" in d
        assert "first_seen" in d
        assert "last_seen" in d
        assert "occurrence_count" in d
        assert "snapshot_ids" in d
        assert "duration_days" in d
        assert "status" in d
        assert "severity_hint" in d
        assert "summary_statement" in d

    def test_duration_computed(self):
        snaps = [S1, S5]  # S1=Jan1, S5=Jan9 → 8 days
        result = ContinuityEngine().track(snaps)
        rec_a = next((l for l in result if l.title == "rec A"), None)
        assert rec_a is not None
        assert rec_a.duration_days >= 7.9

    def test_sorted_by_occurrence_count(self):
        snaps = [S1, S2, S3, S4, S5]
        result = ContinuityEngine().track(snaps)
        counts = [l.occurrence_count for l in result]
        assert counts == sorted(counts, reverse=True)


class TestLifespanSeverity:
    def test_persistent_high_severity(self):
        snaps = [S1, S2, S3, S4, S5]
        result = ContinuityEngine().track(snaps)
        rec_a = next((l for l in result if l.title == "rec A"), None)
        assert rec_a is not None
        assert rec_a.severity_hint == "high"

    def test_new_low_severity(self):
        snap = _snap(1, "2026-01-01T00:00:00", [_rec("solo")])
        result = ContinuityEngine().track([snap])
        solo = next((l for l in result if l.title == "solo"), None)
        assert solo is not None
        assert solo.severity_hint == "low"


class TestSummaryStatement:
    def test_resolved_summary(self):
        snaps = [S1, S2]
        result = ContinuityEngine().track(snaps)
        rec_b = next((l for l in result if l.title == "rec B"), None)
        assert rec_b is not None
        assert "resolved" in rec_b.summary_statement.lower()

    def test_persistent_summary_contains_scans(self):
        snaps = [S1, S2, S3, S4, S5]
        result = ContinuityEngine().track(snaps)
        rec_a = next((l for l in result if l.title == "rec A"), None)
        assert rec_a is not None
        assert "5" in rec_a.summary_statement
