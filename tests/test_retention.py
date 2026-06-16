"""Tests for memory/retention.py — snapshot retention management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.retention import RetentionEngine, RetentionPolicy


def _snap(snap_id: int, days_ago: float = 0.0) -> dict:
    ts = datetime.now(UTC) - timedelta(days=days_ago)
    return {"id": snap_id, "created_at": ts.strftime("%Y-%m-%d %H:%M:%S")}


def _snaps(count: int, days_per_step: float = 1.0) -> list[dict]:
    return [_snap(i + 1, days_ago=i * days_per_step) for i in range(count)]


class TestRetentionPolicy:
    def test_defaults(self):
        p = RetentionPolicy()
        assert p.retention_days == 30
        assert p.max_snapshot_count == 200
        assert p.min_keep_count == 10
        assert p.dry_run is True  # safe default

    def test_min_keep_count_validation(self):
        with pytest.raises(ValueError, match="min_keep_count"):
            RetentionPolicy(min_keep_count=0)

    def test_max_lt_min_validation(self):
        with pytest.raises(ValueError, match="max_snapshot_count"):
            RetentionPolicy(max_snapshot_count=5, min_keep_count=10)

    def test_retention_days_validation(self):
        with pytest.raises(ValueError, match="retention_days"):
            RetentionPolicy(retention_days=0)

    def test_from_deployment_profile(self):
        from config.profiles import STANDARD
        policy = RetentionPolicy.from_deployment_profile(STANDARD, dry_run=True)
        assert policy.retention_days == STANDARD.retention_days
        assert policy.max_snapshot_count == STANDARD.max_snapshot_count
        assert policy.min_keep_count == STANDARD.min_keep_count
        assert policy.dry_run is True


class TestRetentionEngine:
    def setup_method(self):
        self.engine = RetentionEngine()

    def test_empty_snapshots_no_candidates(self):
        policy = RetentionPolicy(retention_days=7, max_snapshot_count=50, min_keep_count=5)
        plan = self.engine.plan([], policy)
        assert plan.deletion_count == 0
        assert plan.total_snapshots == 0

    def test_count_rule_identifies_excess(self):
        # 15 snapshots, max=10
        snaps = _snaps(15, days_per_step=0.1)
        policy = RetentionPolicy(
            retention_days=365, max_snapshot_count=10, min_keep_count=5, dry_run=True
        )
        plan = self.engine.plan(snaps, policy)
        assert plan.deletion_count == 5
        assert plan.kept_count == 10

    def test_age_rule_identifies_old(self):
        # 5 recent + 5 old
        recent = [_snap(i, days_ago=1) for i in range(1, 6)]
        old = [_snap(i, days_ago=40) for i in range(6, 11)]
        snaps = recent + old
        policy = RetentionPolicy(
            retention_days=30, max_snapshot_count=1000, min_keep_count=3, dry_run=True
        )
        plan = self.engine.plan(snaps, policy)
        assert plan.deletion_count == 5
        for c in plan.candidates:
            assert c.reason == "too_old"

    def test_min_keep_count_protects_recent(self):
        # Only 3 snapshots, min_keep=5 — nothing can be deleted
        snaps = [_snap(i, days_ago=60) for i in range(1, 4)]
        policy = RetentionPolicy(
            retention_days=7, max_snapshot_count=50, min_keep_count=5, dry_run=True
        )
        plan = self.engine.plan(snaps, policy)
        assert plan.deletion_count == 0
        assert plan.kept_count == 3

    def test_both_reason_label(self):
        # Snapshot is both old AND beyond count limit
        snaps = [_snap(i, days_ago=40) for i in range(1, 12)]  # 11 old snaps
        policy = RetentionPolicy(
            retention_days=7, max_snapshot_count=8, min_keep_count=3, dry_run=True
        )
        plan = self.engine.plan(snaps, policy)
        # some candidates should have reason "both"
        reasons = {c.reason for c in plan.candidates}
        assert "both" in reasons

    def test_dry_run_does_not_call_delete(self):
        called = []

        def delete_fn(ids):
            called.extend(ids)
            return len(ids)

        snaps = _snaps(15, days_per_step=0.1)
        policy = RetentionPolicy(
            retention_days=365, max_snapshot_count=5, min_keep_count=3, dry_run=True
        )
        result = self.engine.plan_and_execute(snaps, policy, delete_fn)
        assert result.executed is False
        assert result.deleted_ids == []
        assert len(called) == 0

    def test_execute_calls_delete_fn(self):
        deleted = []

        def delete_fn(ids):
            deleted.extend(ids)
            return len(ids)

        snaps = _snaps(15, days_per_step=0.1)
        policy = RetentionPolicy(
            retention_days=365, max_snapshot_count=5, min_keep_count=3, dry_run=False
        )
        result = self.engine.plan_and_execute(snaps, policy, delete_fn)
        assert result.executed is True
        assert len(result.deleted_ids) > 0
        assert sorted(result.deleted_ids) == sorted(deleted)

    def test_no_candidates_message(self):
        snaps = _snaps(3, days_per_step=0.1)
        policy = RetentionPolicy(
            retention_days=365, max_snapshot_count=200, min_keep_count=5, dry_run=False
        )
        result = self.engine.plan_and_execute(snaps, policy, lambda ids: len(ids))
        assert result.executed is True
        assert "satisfied" in result.message

    def test_unparseable_timestamp_skipped(self):
        snaps = [
            {"id": 1, "created_at": "not-a-date"},
            _snap(2, days_ago=1),
        ]
        policy = RetentionPolicy(
            retention_days=7, max_snapshot_count=100, min_keep_count=1, dry_run=True
        )
        plan = self.engine.plan(snaps, policy)
        # id=1 should NOT be a candidate (skip unparseable)
        candidate_ids = {c.snapshot_id for c in plan.candidates}
        assert 1 not in candidate_ids

    def test_plan_to_dict_keys(self):
        snaps = _snaps(5)
        policy = RetentionPolicy(dry_run=True)
        plan = self.engine.plan(snaps, policy)
        d = plan.to_dict()
        assert "policy" in d
        assert "total_snapshots" in d
        assert "deletion_count" in d
        assert "kept_count" in d
        assert "dry_run" in d
        assert "candidates" in d

    def test_plan_summary_includes_dry_run_label(self):
        snaps = _snaps(5)
        policy = RetentionPolicy(dry_run=True)
        plan = self.engine.plan(snaps, policy)
        assert "[DRY RUN]" in plan.summary()

    def test_plan_summary_no_dry_run_label_when_false(self):
        snaps = _snaps(5)
        policy = RetentionPolicy(dry_run=False)
        plan = self.engine.plan(snaps, policy)
        assert "[DRY RUN]" not in plan.summary()

    def test_result_to_dict_advisory(self):
        snaps = _snaps(5)
        policy = RetentionPolicy(dry_run=True)
        result = self.engine.plan_and_execute(snaps, policy, lambda ids: len(ids))
        d = result.to_dict()
        assert "advisory" in d
