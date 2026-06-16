"""
Snapshot retention management — lifecycle pruning for operational memory.

Retention is advisory-first:
- dry_run mode previews deletions without executing them (SAFE DEFAULT)
- All deletion operations generate a RetentionResult report
- min_keep_count is always enforced as a safety floor
- Never silently deletes snapshots

Three retention axes:
- Age:   delete snapshots older than retention_days
- Count: keep only the max_snapshot_count most recent
- Both:  candidates that violate both rules are labelled "both"
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetentionPolicy:
    """Immutable configuration bundle for a retention run."""

    retention_days: int = 30
    max_snapshot_count: int = 200
    min_keep_count: int = 10
    dry_run: bool = True  # safe default — never deletes without explicit opt-in

    def __post_init__(self) -> None:
        if self.min_keep_count < 1:
            raise ValueError("min_keep_count must be at least 1")
        if self.max_snapshot_count < self.min_keep_count:
            raise ValueError("max_snapshot_count must be >= min_keep_count")
        if self.retention_days < 1:
            raise ValueError("retention_days must be at least 1")

    @classmethod
    def from_deployment_profile(cls, profile: Any, *, dry_run: bool = True) -> RetentionPolicy:
        """Build a RetentionPolicy from a DeploymentProfile."""
        return cls(
            retention_days=profile.retention_days,
            max_snapshot_count=profile.max_snapshot_count,
            min_keep_count=profile.min_keep_count,
            dry_run=dry_run,
        )


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@dataclass
class RetentionCandidate:
    snapshot_id: int
    created_at: str
    reason: str  # "too_old" | "exceeds_count" | "both"


@dataclass
class RetentionPlan:
    """Read-only description of what a retention run would do."""

    policy: RetentionPolicy
    total_snapshots: int
    candidates: list[RetentionCandidate]
    kept_count: int
    dry_run: bool
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def deletion_count(self) -> int:
        return len(self.candidates)

    def summary(self) -> str:
        prefix = "[DRY RUN] " if self.dry_run else ""
        return (
            f"{prefix}Retention plan: {self.total_snapshots} total, "
            f"{self.deletion_count} to delete, {self.kept_count} to keep. "
            f"Policy: {self.policy.retention_days}d age / "
            f"{self.policy.max_snapshot_count} max count."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": {
                "retention_days": self.policy.retention_days,
                "max_snapshot_count": self.policy.max_snapshot_count,
                "min_keep_count": self.policy.min_keep_count,
                "dry_run": self.policy.dry_run,
            },
            "total_snapshots": self.total_snapshots,
            "deletion_count": self.deletion_count,
            "kept_count": self.kept_count,
            "dry_run": self.dry_run,
            "candidates": [
                {
                    "id": c.snapshot_id,
                    "created_at": c.created_at,
                    "reason": c.reason,
                }
                for c in self.candidates
            ],
            "generated_at": self.generated_at,
        }


@dataclass
class RetentionResult:
    """Outcome of a retention execution (or dry-run preview)."""

    plan: RetentionPlan
    deleted_ids: list[int]
    executed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "deleted_ids": self.deleted_ids,
            "executed": self.executed,
            "message": self.message,
            "advisory": "All retention operations require explicit operator approval.",
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RetentionEngine:
    """
    Plans and optionally executes snapshot retention pruning.

    dry_run=True (the safe default on RetentionPolicy) generates a plan
    without touching storage. dry_run=False executes deletions after planning.

    The engine itself holds no state — all decisions are derived from the
    snapshots list and the policy passed in.
    """

    def plan(
        self,
        snapshots: list[dict[str, Any]],
        policy: RetentionPolicy,
    ) -> RetentionPlan:
        """Compute which snapshots should be deleted. Does NOT modify storage."""
        sorted_snaps = sorted(
            snapshots,
            key=lambda s: s.get("created_at", ""),
            reverse=True,  # newest first
        )
        total = len(sorted_snaps)
        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)

        # Safety floor: always protect the N most recent
        protected_ids = {s["id"] for s in sorted_snaps[: policy.min_keep_count]}

        candidates: dict[int, RetentionCandidate] = {}

        # Age rule
        for snap in sorted_snaps:
            snap_id = snap.get("id")
            if snap_id is None or snap_id in protected_ids:
                continue
            ts_str = snap.get("created_at", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace(" ", "T"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    if snap_id in candidates:
                        candidates[snap_id].reason = "both"
                    else:
                        candidates[snap_id] = RetentionCandidate(
                            snapshot_id=snap_id,
                            created_at=ts_str,
                            reason="too_old",
                        )
            except (ValueError, AttributeError):
                pass  # unparseable timestamp — skip, never delete speculatively

        # Count rule
        if total > policy.max_snapshot_count:
            for snap in sorted_snaps[policy.max_snapshot_count :]:
                snap_id = snap.get("id")
                if snap_id is None or snap_id in protected_ids:
                    continue
                if snap_id in candidates:
                    candidates[snap_id].reason = "both"
                else:
                    candidates[snap_id] = RetentionCandidate(
                        snapshot_id=snap_id,
                        created_at=snap.get("created_at", ""),
                        reason="exceeds_count",
                    )

        candidate_list = list(candidates.values())
        kept_count = total - len(candidate_list)

        logger.info(
            "Retention plan computed",
            extra={
                "total": total,
                "candidates": len(candidate_list),
                "kept": kept_count,
                "dry_run": policy.dry_run,
            },
        )
        return RetentionPlan(
            policy=policy,
            total_snapshots=total,
            candidates=candidate_list,
            kept_count=kept_count,
            dry_run=policy.dry_run,
        )

    def execute(
        self,
        plan: RetentionPlan,
        delete_fn: Callable[[list[int]], int],
    ) -> RetentionResult:
        """
        Execute a retention plan.

        delete_fn must accept list[int] of snapshot IDs and return deleted count.
        If plan.dry_run is True, reports the plan without deleting anything.
        """
        if plan.dry_run:
            logger.info(
                "Retention dry run — no deletions performed",
                extra={"candidates": plan.deletion_count},
            )
            return RetentionResult(
                plan=plan,
                deleted_ids=[],
                executed=False,
                message=(
                    f"Dry run: {plan.deletion_count} snapshot(s) identified for deletion. "
                    "Set dry_run=False on the RetentionPolicy to execute."
                ),
            )

        if not plan.candidates:
            return RetentionResult(
                plan=plan,
                deleted_ids=[],
                executed=True,
                message="No snapshots to delete — retention policy already satisfied.",
            )

        ids_to_delete = [c.snapshot_id for c in plan.candidates]
        deleted_count = delete_fn(ids_to_delete)
        logger.info(
            "Retention executed",
            extra={"deleted": deleted_count, "ids": ids_to_delete},
        )
        return RetentionResult(
            plan=plan,
            deleted_ids=ids_to_delete,
            executed=True,
            message=(
                f"Deleted {deleted_count} snapshot(s). "
                f"{plan.kept_count} snapshot(s) retained."
            ),
        )

    def plan_and_execute(
        self,
        snapshots: list[dict[str, Any]],
        policy: RetentionPolicy,
        delete_fn: Callable[[list[int]], int],
    ) -> RetentionResult:
        """Convenience: plan then execute in one call."""
        retention_plan = self.plan(snapshots, policy)
        return self.execute(retention_plan, delete_fn)


# ---------------------------------------------------------------------------
# LLM Event Retention
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMEventRetentionPolicy:
    """Retention policy for LLM operational events."""

    retention_days: int = 30
    max_event_count: int = 50_000
    min_keep_count: int = 1_000
    dry_run: bool = True  # safe default

    def __post_init__(self) -> None:
        if self.retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        if self.max_event_count < self.min_keep_count:
            raise ValueError("max_event_count must be >= min_keep_count")
        if self.min_keep_count < 1:
            raise ValueError("min_keep_count must be at least 1")


@dataclass
class LLMEventRetentionPlan:
    policy: LLMEventRetentionPolicy
    total_events: int
    age_deletable: int
    count_deletable: int
    total_deletable: int
    dry_run: bool
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def summary(self) -> str:
        prefix = "[DRY RUN] " if self.dry_run else ""
        return (
            f"{prefix}LLM event retention plan: {self.total_events} total, "
            f"{self.total_deletable} to delete. "
            f"Policy: {self.policy.retention_days}d age / "
            f"{self.policy.max_event_count} max count."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": {
                "retention_days": self.policy.retention_days,
                "max_event_count": self.policy.max_event_count,
                "min_keep_count": self.policy.min_keep_count,
                "dry_run": self.policy.dry_run,
            },
            "total_events": self.total_events,
            "age_deletable": self.age_deletable,
            "count_deletable": self.count_deletable,
            "total_deletable": self.total_deletable,
            "dry_run": self.dry_run,
            "generated_at": self.generated_at,
        }


@dataclass
class LLMEventRetentionResult:
    plan: LLMEventRetentionPlan
    deleted_by_age: int
    deleted_by_count: int
    executed: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "deleted_by_age": self.deleted_by_age,
            "deleted_by_count": self.deleted_by_count,
            "total_deleted": self.deleted_by_age + self.deleted_by_count,
            "executed": self.executed,
            "message": self.message,
            "advisory": "All LLM event retention operations require explicit operator approval.",
        }


class LLMEventRetentionEngine:
    """
    Plans and optionally executes LLM event retention pruning.

    dry_run=True (safe default) previews without deleting.
    dry_run=False executes after planning.

    Uses two-pass pruning:
    1. Age: remove events older than retention_days
    2. Count: remove oldest events if total exceeds max_event_count
    """

    def plan(
        self,
        total_events: int,
        oldest_timestamp: str | None,
        policy: LLMEventRetentionPolicy,
    ) -> LLMEventRetentionPlan:
        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)

        age_deletable = 0
        if oldest_timestamp:
            try:
                ts = datetime.fromisoformat(oldest_timestamp.replace(" ", "T"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    age_deletable = max(0, total_events - policy.min_keep_count)
            except (ValueError, AttributeError):
                pass

        count_deletable = 0
        if total_events > policy.max_event_count:
            count_deletable = min(
                total_events - policy.max_event_count,
                total_events - policy.min_keep_count,
            )
            count_deletable = max(count_deletable, 0)

        total_deletable = max(age_deletable, count_deletable)

        logger.info(
            "LLM event retention plan computed",
            extra={
                "total": total_events,
                "age_deletable": age_deletable,
                "count_deletable": count_deletable,
                "total_deletable": total_deletable,
                "dry_run": policy.dry_run,
            },
        )
        return LLMEventRetentionPlan(
            policy=policy,
            total_events=total_events,
            age_deletable=age_deletable,
            count_deletable=count_deletable,
            total_deletable=total_deletable,
            dry_run=policy.dry_run,
        )

    def execute(
        self,
        plan: LLMEventRetentionPlan,
        delete_by_age_fn: Callable[[int], int],
        delete_by_count_fn: Callable[[int, int], int],
    ) -> LLMEventRetentionResult:
        if plan.dry_run:
            logger.info(
                "LLM event retention dry run — no deletions performed",
                extra={"total_deletable": plan.total_deletable},
            )
            return LLMEventRetentionResult(
                plan=plan,
                deleted_by_age=0,
                deleted_by_count=0,
                executed=False,
                message=(
                    f"Dry run: up to {plan.total_deletable} event(s) identified for deletion. "
                    "Set dry_run=False on LLMEventRetentionPolicy to execute."
                ),
            )

        if plan.total_deletable == 0:
            return LLMEventRetentionResult(
                plan=plan,
                deleted_by_age=0,
                deleted_by_count=0,
                executed=True,
                message="No LLM events to delete — retention policy already satisfied.",
            )

        deleted_age = 0
        deleted_count = 0

        if plan.age_deletable > 0:
            deleted_age = delete_by_age_fn(plan.policy.retention_days)

        if plan.count_deletable > 0:
            deleted_count = delete_by_count_fn(
                plan.policy.max_event_count, plan.policy.min_keep_count
            )

        logger.info(
            "LLM event retention executed",
            extra={"deleted_age": deleted_age, "deleted_count": deleted_count},
        )
        return LLMEventRetentionResult(
            plan=plan,
            deleted_by_age=deleted_age,
            deleted_by_count=deleted_count,
            executed=True,
            message=(
                f"Deleted {deleted_age} events by age, {deleted_count} by count. "
                f"Total deleted: {deleted_age + deleted_count}."
            ),
        )


# ---------------------------------------------------------------------------
# Phase 13B: Retention efficiency scoring
# ---------------------------------------------------------------------------

@dataclass
class RetentionEfficiencyScore:
    """
    Advisory score for how well a retention policy fits the current dataset.

    score 0.0–1.0: 1.0 = well-calibrated, 0.0 = severely mis-calibrated.
    Bands:
      optimal    (>0.75)  — deletion rate in healthy 5–30% range
      adequate   (0.50–0.75) — above ideal but not alarming
      lenient    (<0.50, low deletion) — rarely pruning; policy may be too permissive
      aggressive (<0.50, high deletion) — pruning too much; history may be lost
    """

    score: float
    band: str        # "optimal" | "adequate" | "lenient" | "aggressive"
    total_snapshots: int
    eligible_for_deletion: int
    deletion_rate: float
    policy_days: int
    policy_max_count: int
    observations: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "band": self.band,
            "total_snapshots": self.total_snapshots,
            "eligible_for_deletion": self.eligible_for_deletion,
            "deletion_rate": round(self.deletion_rate, 3),
            "deletion_percent": round(self.deletion_rate * 100, 1),
            "policy_days": self.policy_days,
            "policy_max_count": self.policy_max_count,
            "observations": self.observations,
            "generated_at": self.generated_at,
            "advisory": (
                "Efficiency scoring is advisory. "
                "Policy changes require operator decision."
            ),
        }


# Healthy deletion-rate range thresholds
_EFFICIENCY_IDEAL_LOW = 0.05
_EFFICIENCY_IDEAL_HIGH = 0.30
_EFFICIENCY_AGGRESSIVE = 0.50


def score_retention_efficiency(plan: RetentionPlan) -> RetentionEfficiencyScore:
    """
    Score how well a snapshot retention plan's policy fits the data.

    A plan that consistently marks 5–30% of snapshots for deletion is
    considered well-calibrated. Outside that range the policy is either
    too lenient (rarely pruning) or too aggressive (pruning too much).
    """
    total = plan.total_snapshots
    eligible = plan.deletion_count

    if total == 0:
        return RetentionEfficiencyScore(
            score=1.0,
            band="optimal",
            total_snapshots=0,
            eligible_for_deletion=0,
            deletion_rate=0.0,
            policy_days=plan.policy.retention_days,
            policy_max_count=plan.policy.max_snapshot_count,
            observations=[
                "No snapshots in dataset — retention policy has nothing to evaluate."
            ],
        )

    deletion_rate = eligible / total
    observations: list[str] = []

    if deletion_rate < _EFFICIENCY_IDEAL_LOW:
        band = "lenient"
        # Score decays toward 0.40 as deletion_rate → 0
        decay = ((_EFFICIENCY_IDEAL_LOW - deletion_rate) / _EFFICIENCY_IDEAL_LOW) * 0.35
        score = max(0.40, 0.75 - decay)
        observations.append(
            f"Retention policy appears lenient: only {deletion_rate:.1%} of snapshots "
            f"({eligible}/{total}) are eligible for deletion."
        )
        observations.append(
            f"Consider reducing retention_days (currently {plan.policy.retention_days}) "
            "to prune data more actively."
        )
    elif deletion_rate > _EFFICIENCY_AGGRESSIVE:
        band = "aggressive"
        overage = (deletion_rate - _EFFICIENCY_AGGRESSIVE) / (1.0 - _EFFICIENCY_AGGRESSIVE)
        score = max(0.30, 0.75 - overage * 0.45)
        observations.append(
            f"Retention policy appears aggressive: {deletion_rate:.1%} of snapshots "
            f"({eligible}/{total}) are eligible for deletion."
        )
        observations.append(
            "Consider increasing retention_days to preserve more operational history."
        )
    elif deletion_rate > _EFFICIENCY_IDEAL_HIGH:
        band = "adequate"
        overage = (deletion_rate - _EFFICIENCY_IDEAL_HIGH) / (
            _EFFICIENCY_AGGRESSIVE - _EFFICIENCY_IDEAL_HIGH
        )
        score = 0.75 - overage * 0.15
        observations.append(
            f"Retention rate {deletion_rate:.1%} is above the ideal range "
            "but still acceptable."
        )
    else:
        band = "optimal"
        center = (_EFFICIENCY_IDEAL_LOW + _EFFICIENCY_IDEAL_HIGH) / 2
        half_range = (_EFFICIENCY_IDEAL_HIGH - _EFFICIENCY_IDEAL_LOW) / 2
        distance = abs(deletion_rate - center) / max(half_range, 1e-9)
        score = 1.0 - distance * 0.15
        observations.append(
            f"Retention policy appears well-calibrated: {deletion_rate:.1%} of "
            "snapshots eligible for deletion is within the healthy range."
        )

    score = max(0.0, min(1.0, score))
    observations.append(
        f"Policy: retention_days={plan.policy.retention_days}, "
        f"max_snapshot_count={plan.policy.max_snapshot_count}, "
        f"min_keep_count={plan.policy.min_keep_count}."
    )

    logger.debug(
        "Retention efficiency scored",
        extra={"score": score, "band": band, "deletion_rate": deletion_rate},
    )
    return RetentionEfficiencyScore(
        score=score,
        band=band,
        total_snapshots=total,
        eligible_for_deletion=eligible,
        deletion_rate=deletion_rate,
        policy_days=plan.policy.retention_days,
        policy_max_count=plan.policy.max_snapshot_count,
        observations=observations,
    )
