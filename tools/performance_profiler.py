"""
Performance Profiler — operational latency budget analysis.

Compares measured operation timings against VPS-realistic budgets.
Advisory only — reports violations, does not modify execution paths.

Design:
- OperationTimer: context manager that measures wall-clock time for an operation
- PerformanceProfiler: stateless analyzer that checks timings against budgets
- BUDGETS: predefined VPS-realistic budgets for cognition pipeline operations
- PerformanceBudgetReport.markdown() produces formatted advisory output

No ML. No async. No DB access. No autonomous action.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OperationBudget:
    """Latency budget for a named cognition pipeline operation."""
    name: str
    soft_limit_ms: float     # warning threshold
    hard_limit_ms: float     # violation threshold
    category: str = "general"  # "cognition" | "storage" | "report" | "general"
    description: str = ""


# VPS-realistic budgets — single-core VPS with SQLite/Postgres.
# Soft = "this is slower than expected, investigate".
# Hard = "this is unacceptable for interactive or scheduled use".
BUDGETS: dict[str, OperationBudget] = {
    "signal_quality": OperationBudget(
        name="signal_quality",
        soft_limit_ms=50.0,
        hard_limit_ms=200.0,
        category="cognition",
        description="Signal quality scoring per snapshot batch",
    ),
    "storage_optimizer": OperationBudget(
        name="storage_optimizer",
        soft_limit_ms=10.0,
        hard_limit_ms=50.0,
        category="storage",
        description="Storage optimization advisory generation",
    ),
    "investigation_quality": OperationBudget(
        name="investigation_quality",
        soft_limit_ms=20.0,
        hard_limit_ms=100.0,
        category="cognition",
        description="Investigation quality scoring",
    ),
    "investigation_triage": OperationBudget(
        name="investigation_triage",
        soft_limit_ms=30.0,
        hard_limit_ms=150.0,
        category="cognition",
        description="Investigation triage and follow-on suggestion generation",
    ),
    "deduplication_small": OperationBudget(
        name="deduplication_small",
        soft_limit_ms=5.0,
        hard_limit_ms=25.0,
        category="cognition",
        description="Signal deduplication for up to 50 recommendations",
    ),
    "deduplication_large": OperationBudget(
        name="deduplication_large",
        soft_limit_ms=100.0,
        hard_limit_ms=500.0,
        category="cognition",
        description="Signal deduplication for up to 1000 recommendations",
    ),
    "snapshot_synthesis": OperationBudget(
        name="snapshot_synthesis",
        soft_limit_ms=200.0,
        hard_limit_ms=1000.0,
        category="cognition",
        description="Full snapshot intelligence synthesis",
    ),
    "report_generation": OperationBudget(
        name="report_generation",
        soft_limit_ms=50.0,
        hard_limit_ms=200.0,
        category="report",
        description="Markdown report generation from structured result",
    ),
    "retention_analysis": OperationBudget(
        name="retention_analysis",
        soft_limit_ms=15.0,
        hard_limit_ms=75.0,
        category="storage",
        description="Retention plan generation and efficiency scoring",
    ),
    "storage_hygiene": OperationBudget(
        name="storage_hygiene",
        soft_limit_ms=20.0,
        hard_limit_ms=100.0,
        category="storage",
        description="Storage hygiene analysis (cold, oversized, density)",
    ),
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PerformanceBudgetViolation:
    """A single budget violation — one operation exceeded soft or hard limit."""
    operation_name: str
    elapsed_ms: float
    budget_ms: float
    limit_type: str          # "soft" | "hard"
    overage_ms: float
    overage_fraction: float  # (elapsed - budget) / budget; 1.0 = 2× over budget

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_name": self.operation_name,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budget_ms": self.budget_ms,
            "limit_type": self.limit_type,
            "overage_ms": round(self.overage_ms, 3),
            "overage_fraction": round(self.overage_fraction, 4),
        }


@dataclass
class ProfiledOperation:
    """A named operation with its measured elapsed time and optional budget."""
    name: str
    elapsed_ms: float
    budget: OperationBudget | None = None

    def check_violation(self) -> PerformanceBudgetViolation | None:
        """Return a violation if this operation exceeded its budget; else None."""
        if self.budget is None:
            return None
        if self.elapsed_ms > self.budget.hard_limit_ms:
            overage = self.elapsed_ms - self.budget.hard_limit_ms
            return PerformanceBudgetViolation(
                operation_name=self.name,
                elapsed_ms=self.elapsed_ms,
                budget_ms=self.budget.hard_limit_ms,
                limit_type="hard",
                overage_ms=overage,
                overage_fraction=overage / self.budget.hard_limit_ms,
            )
        if self.elapsed_ms > self.budget.soft_limit_ms:
            overage = self.elapsed_ms - self.budget.soft_limit_ms
            return PerformanceBudgetViolation(
                operation_name=self.name,
                elapsed_ms=self.elapsed_ms,
                budget_ms=self.budget.soft_limit_ms,
                limit_type="soft",
                overage_ms=overage,
                overage_fraction=overage / self.budget.soft_limit_ms,
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "budget_name": self.budget.name if self.budget else None,
            "soft_limit_ms": self.budget.soft_limit_ms if self.budget else None,
            "hard_limit_ms": self.budget.hard_limit_ms if self.budget else None,
        }


@dataclass
class PerformanceBudgetReport:
    """
    Summary of profiled operations against their latency budgets.

    Produced by PerformanceProfiler.analyze().
    """
    operations: list[ProfiledOperation]
    violations: list[PerformanceBudgetViolation]
    within_budget: list[ProfiledOperation]
    unbudgeted: list[ProfiledOperation]
    hard_violation_count: int
    soft_violation_count: int
    overall_status: str          # "ok" | "warning" | "critical"
    observations: list[str]
    generated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "hard_violation_count": self.hard_violation_count,
            "soft_violation_count": self.soft_violation_count,
            "total_operations": len(self.operations),
            "within_budget_count": len(self.within_budget),
            "unbudgeted_count": len(self.unbudgeted),
            "violations": [v.to_dict() for v in self.violations],
            "observations": self.observations,
            "generated_at": self.generated_at,
        }

    def markdown(self) -> str:
        """Produce an advisory markdown performance report."""
        ts = self.generated_at[:19].replace("T", " ") + " UTC"
        lines: list[str] = [
            "# Performance Budget Report",
            f"**Generated:** {ts}",
            f"**Overall status:** {self.overall_status.upper()}",
            (
                f"**Operations:** {len(self.operations)} | "
                f"**Hard violations:** {self.hard_violation_count} | "
                f"**Soft violations:** {self.soft_violation_count}"
            ),
            "",
        ]

        hard = [v for v in self.violations if v.limit_type == "hard"]
        soft_v = [v for v in self.violations if v.limit_type == "soft"]

        if hard:
            lines += ["## Hard Limit Violations", ""]
            for v in hard:
                lines.append(
                    f"- **{v.operation_name}**: {v.elapsed_ms:.1f} ms "
                    f"(hard budget: {v.budget_ms:.0f} ms, "
                    f"+{v.overage_ms:.1f} ms / +{v.overage_fraction:.0%} over)"
                )
            lines.append("")

        if soft_v:
            lines += ["## Soft Limit Warnings", ""]
            for v in soft_v:
                lines.append(
                    f"- **{v.operation_name}**: {v.elapsed_ms:.1f} ms "
                    f"(soft budget: {v.budget_ms:.0f} ms, +{v.overage_ms:.1f} ms)"
                )
            lines.append("")

        if self.within_budget:
            lines += ["## Within Budget", ""]
            for op in self.within_budget:
                sl = op.budget.soft_limit_ms if op.budget else 0.0
                lines.append(
                    f"- **{op.name}**: {op.elapsed_ms:.1f} ms "
                    f"(soft budget: {sl:.0f} ms)"
                )
            lines.append("")

        if self.unbudgeted:
            lines += ["## Unbudgeted Operations", ""]
            for op in self.unbudgeted:
                lines.append(f"- **{op.name}**: {op.elapsed_ms:.1f} ms (no budget defined)")
            lines.append("")

        if self.observations:
            lines += ["## Observations", ""]
            for obs in self.observations:
                lines.append(f"- {obs}")
            lines.append("")

        lines += [
            "---",
            "*Advisory only — all operational decisions require human review.*",
            "*Generated by Quartermaster — Observe automatically. Decide manually.*",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OperationTimer context manager
# ---------------------------------------------------------------------------

class OperationTimer:
    """
    Measure wall-clock elapsed time for a single operation.

    Usage:
        with OperationTimer("investigation_quality",
                            budget=BUDGETS.get("investigation_quality")) as t:
            result = engine.score(data)
        op = t.result  # ProfiledOperation with elapsed_ms filled in
    """

    def __init__(
        self,
        name: str,
        budget: OperationBudget | None = None,
    ) -> None:
        self.name = name
        self.budget = budget
        self._start: float = 0.0
        self.result: ProfiledOperation | None = None

    def __enter__(self) -> OperationTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1_000.0
        self.result = ProfiledOperation(
            name=self.name,
            elapsed_ms=elapsed_ms,
            budget=self.budget,
        )


# ---------------------------------------------------------------------------
# PerformanceProfiler — stateless analyzer
# ---------------------------------------------------------------------------

class PerformanceProfiler:
    """
    Stateless performance budget analyzer.

    Accepts a list of ProfiledOperation instances and produces a
    PerformanceBudgetReport. Does not modify any external state.
    Same inputs always produce the same output.
    """

    def analyze(
        self,
        operations: list[ProfiledOperation],
    ) -> PerformanceBudgetReport:
        """Check operations against their budgets and return an advisory report."""
        violations: list[PerformanceBudgetViolation] = []
        within_budget: list[ProfiledOperation] = []
        unbudgeted: list[ProfiledOperation] = []

        for op in operations:
            if op.budget is None:
                unbudgeted.append(op)
                continue
            v = op.check_violation()
            if v is not None:
                violations.append(v)
            else:
                within_budget.append(op)

        hard_count = sum(1 for v in violations if v.limit_type == "hard")
        soft_count = len(violations) - hard_count

        if hard_count > 0:
            status = "critical"
        elif soft_count > 0:
            status = "warning"
        else:
            status = "ok"

        observations = _build_observations(operations, violations, unbudgeted)

        logger.info(
            "Performance profile analyzed",
            extra={
                "op_count": len(operations),
                "hard_violations": hard_count,
                "soft_violations": soft_count,
                "status": status,
            },
        )
        return PerformanceBudgetReport(
            operations=operations,
            violations=violations,
            within_budget=within_budget,
            unbudgeted=unbudgeted,
            hard_violation_count=hard_count,
            soft_violation_count=soft_count,
            overall_status=status,
            observations=observations,
        )

    @classmethod
    def from_measurements(
        cls,
        measurements: list[tuple[str, float]],
    ) -> PerformanceProfiler:
        """
        Convenience factory that does nothing — the caller still calls analyze().

        Exists so callers can construct profiled operations inline:
            profiler = PerformanceProfiler()
            ops = [
                ProfiledOperation(name, ms, BUDGETS.get(name))
                for name, ms in measurements
            ]
            report = profiler.analyze(ops)
        """
        return cls()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_observations(
    operations: list[ProfiledOperation],
    violations: list[PerformanceBudgetViolation],
    unbudgeted: list[ProfiledOperation],
) -> list[str]:
    if not operations:
        return ["No operations profiled."]

    budgeted_count = len(operations) - len(unbudgeted)
    obs: list[str] = []

    if budgeted_count == 0:
        obs.append(
            "No operations had budgets assigned — cannot assess latency compliance."
        )
        return obs

    hard_violations = [v for v in violations if v.limit_type == "hard"]
    soft_violations = [v for v in violations if v.limit_type == "soft"]

    if not violations:
        obs.append(
            f"All {budgeted_count} budgeted operation(s) within expected latency."
        )

    if hard_violations:
        worst = max(hard_violations, key=lambda v: v.overage_fraction)
        obs.append(
            f"Worst hard violation: {worst.operation_name} at {worst.elapsed_ms:.1f} ms "
            f"({worst.overage_fraction:.0%} over hard limit)."
        )

    if operations:
        slowest = max(operations, key=lambda op: op.elapsed_ms)
        obs.append(f"Slowest operation: {slowest.name} ({slowest.elapsed_ms:.1f} ms).")

    if soft_violations and budgeted_count > 0:
        soft_frac = len(soft_violations) / budgeted_count
        if soft_frac >= 0.5:
            obs.append(
                f"{soft_frac:.0%} of budgeted operations exceeded their soft limit — "
                "consider reviewing workload input sizes."
            )

    if unbudgeted:
        obs.append(
            f"{len(unbudgeted)} operation(s) have no budget defined — "
            "consider adding them to BUDGETS."
        )

    return obs
