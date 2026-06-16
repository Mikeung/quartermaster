"""Tests for memory/retention.py — LLM event retention engine."""

from __future__ import annotations

import pytest

from memory.retention import (
    LLMEventRetentionEngine,
    LLMEventRetentionPolicy,
)


def _make_policy(**overrides) -> LLMEventRetentionPolicy:
    base = {
        "retention_days": 30,
        "max_event_count": 10_000,
        "min_keep_count": 100,
        "dry_run": True,
    }
    base.update(overrides)
    return LLMEventRetentionPolicy(**base)


class TestLLMEventRetentionPolicy:
    def test_default_policy(self):
        p = LLMEventRetentionPolicy()
        assert p.retention_days == 30
        assert p.max_event_count == 50_000
        assert p.min_keep_count == 1_000
        assert p.dry_run is True

    def test_dry_run_is_safe_default(self):
        p = LLMEventRetentionPolicy()
        assert p.dry_run is True

    def test_invalid_retention_days_rejected(self):
        with pytest.raises(ValueError, match="retention_days"):
            LLMEventRetentionPolicy(retention_days=0)

    def test_max_count_less_than_min_rejected(self):
        with pytest.raises(ValueError, match="max_event_count"):
            LLMEventRetentionPolicy(max_event_count=50, min_keep_count=100)

    def test_min_keep_count_zero_rejected(self):
        with pytest.raises(ValueError, match="min_keep_count"):
            LLMEventRetentionPolicy(min_keep_count=0)


class TestLLMEventRetentionEngine:
    def test_plan_no_deletions_needed(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy()
        plan = engine.plan(total_events=50, oldest_timestamp=None, policy=policy)
        assert plan.total_deletable == 0

    def test_plan_count_exceeds_max(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(max_event_count=100, min_keep_count=10)
        plan = engine.plan(total_events=200, oldest_timestamp=None, policy=policy)
        assert plan.count_deletable > 0
        assert plan.total_deletable > 0

    def test_plan_old_events(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(retention_days=30, min_keep_count=10)
        plan = engine.plan(
            total_events=500,
            oldest_timestamp="2020-01-01T00:00:00Z",
            policy=policy,
        )
        assert plan.age_deletable > 0

    def test_plan_recent_events_no_age_deletion(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(retention_days=30)
        plan = engine.plan(
            total_events=50,
            oldest_timestamp="2026-05-15T00:00:00Z",
            policy=policy,
        )
        assert plan.age_deletable == 0

    def test_dry_run_does_not_call_delete(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(max_event_count=10, min_keep_count=5, dry_run=True)
        plan = engine.plan(total_events=100, oldest_timestamp=None, policy=policy)

        called = []
        result = engine.execute(
            plan,
            delete_by_age_fn=lambda days: called.append("age") or 0,
            delete_by_count_fn=lambda m, k: called.append("count") or 0,
        )
        assert result.executed is False
        assert called == []

    def test_live_run_calls_delete(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(max_event_count=10, min_keep_count=5, dry_run=False)
        plan = engine.plan(total_events=100, oldest_timestamp=None, policy=policy)
        assert plan.count_deletable > 0

        calls = []
        result = engine.execute(
            plan,
            delete_by_age_fn=lambda days: calls.append(("age", days)) or 0,
            delete_by_count_fn=lambda m, k: calls.append(("count", m, k)) or 50,
        )
        assert result.executed is True
        assert any(c[0] == "count" for c in calls)

    def test_dry_run_summary_in_message(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy(max_event_count=10, min_keep_count=5, dry_run=True)
        plan = engine.plan(total_events=100, oldest_timestamp=None, policy=policy)
        result = engine.execute(
            plan,
            delete_by_age_fn=lambda d: 0,
            delete_by_count_fn=lambda m, k: 0,
        )
        assert "Dry run" in result.message

    def test_to_dict_serializable(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy()
        plan = engine.plan(total_events=50, oldest_timestamp=None, policy=policy)
        result = engine.execute(
            plan,
            delete_by_age_fn=lambda d: 0,
            delete_by_count_fn=lambda m, k: 0,
        )
        d = result.to_dict()
        assert "plan" in d
        assert "executed" in d
        assert "advisory" in d

    def test_plan_to_dict(self):
        engine = LLMEventRetentionEngine()
        policy = _make_policy()
        plan = engine.plan(total_events=50, oldest_timestamp=None, policy=policy)
        d = plan.to_dict()
        assert "policy" in d
        assert "total_events" in d
        assert "dry_run" in d
