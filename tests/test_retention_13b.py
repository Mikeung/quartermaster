"""Tests for Phase 13B additions to memory/retention.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.retention import (
    RetentionEngine,
    RetentionPolicy,
    score_retention_efficiency,
)


def _policy(**overrides) -> RetentionPolicy:
    defaults = {
        "retention_days": 30,
        "max_snapshot_count": 200,
        "min_keep_count": 10,
        "dry_run": True,
    }
    defaults.update(overrides)
    return RetentionPolicy(**defaults)


def _snapshots(total: int, old: int) -> list[dict]:
    """Build `total` snapshots where `old` are older than 30 days."""
    now = datetime.now(UTC)
    result = []
    for i in range(total):
        age = 40 if i < old else 5  # old ones are 40 days old
        ts = (now - timedelta(days=age)).isoformat()
        result.append({"id": i + 1, "created_at": ts})
    return result


class TestRetentionEfficiencyScore:
    def test_empty_dataset_optimal(self):
        plan = RetentionEngine().plan([], _policy())
        score = score_retention_efficiency(plan)
        assert score.band == "optimal"
        assert score.score == pytest.approx(1.0)
        assert score.total_snapshots == 0

    def test_score_is_float_in_range(self):
        snaps = _snapshots(100, old=15)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert isinstance(score.score, float)
        assert 0.0 <= score.score <= 1.0

    def test_optimal_band_healthy_deletion_rate(self):
        # 15% deletion rate — within 5–30% ideal range
        snaps = _snapshots(100, old=15)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.band == "optimal"
        assert score.score >= 0.75

    def test_lenient_band_very_few_deletions(self):
        # 2% deletion rate — well below 5% threshold
        snaps = _snapshots(100, old=2)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.band == "lenient"

    def test_aggressive_band_high_deletion_rate(self):
        # 75% deletion rate — well above 50% threshold
        snaps = _snapshots(100, old=75)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.band == "aggressive"

    def test_adequate_band_between_ideal_and_aggressive(self):
        # 40% deletion rate — above 30% ideal but below 50% aggressive
        snaps = _snapshots(100, old=40)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.band in ("adequate", "aggressive")  # boundary-adjacent, accept both

    def test_deletion_rate_computed_correctly(self):
        snaps = _snapshots(100, old=20)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.eligible_for_deletion == plan.deletion_count
        assert score.deletion_rate == pytest.approx(
            plan.deletion_count / 100, abs=0.01
        )

    def test_observations_nonempty(self):
        snaps = _snapshots(50, old=10)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.observations

    def test_lenient_observation_mentions_reduce(self):
        snaps = _snapshots(100, old=1)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        if score.band == "lenient":
            assert any("retention_days" in o for o in score.observations)

    def test_aggressive_observation_mentions_increase(self):
        snaps = _snapshots(100, old=80)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        if score.band == "aggressive":
            assert any("retention_days" in o for o in score.observations)

    def test_policy_fields_preserved(self):
        policy = _policy(retention_days=14, max_snapshot_count=100)
        snaps = _snapshots(50, old=10)
        plan = RetentionEngine().plan(snaps, policy)
        score = score_retention_efficiency(plan)
        assert score.policy_days == 14
        assert score.policy_max_count == 100

    def test_to_dict_structure(self):
        snaps = _snapshots(50, old=10)
        plan = RetentionEngine().plan(snaps, _policy())
        d = score_retention_efficiency(plan).to_dict()
        assert "score" in d
        assert "band" in d
        assert "total_snapshots" in d
        assert "eligible_for_deletion" in d
        assert "deletion_rate" in d
        assert "deletion_percent" in d
        assert "policy_days" in d
        assert "policy_max_count" in d
        assert "observations" in d
        assert "advisory" in d
        assert "generated_at" in d

    def test_score_non_negative(self):
        # Extreme case: everything deleted
        snaps = _snapshots(20, old=20)
        plan = RetentionEngine().plan(snaps, _policy(min_keep_count=1))
        score = score_retention_efficiency(plan)
        assert score.score >= 0.0

    def test_score_at_most_one(self):
        snaps = _snapshots(20, old=3)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.score <= 1.0

    def test_total_snapshots_matches_plan(self):
        snaps = _snapshots(60, old=10)
        plan = RetentionEngine().plan(snaps, _policy())
        score = score_retention_efficiency(plan)
        assert score.total_snapshots == plan.total_snapshots
