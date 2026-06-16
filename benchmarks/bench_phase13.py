"""
Phase 13 benchmarks — storage optimizer, investigation quality, performance profiler.

Run with:  python benchmarks/bench_phase13.py
Not a pytest file — uses perf_counter with 10-run averaging.
"""

from __future__ import annotations

import random
import string
import time

from cognition.investigation_quality import InvestigationQualityEngine
from tools.performance_profiler import (
    BUDGETS,
    OperationTimer,
    PerformanceProfiler,
    ProfiledOperation,
)
from tools.storage_optimizer import StorageOptimizerEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rand_word(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _make_investigation_result(
    kind: str = "severity_increase",
    evidence_count: int = 5,
    snapshot_count: int = 4,
    confidence: float = 0.70,
) -> dict:
    return {
        "kind": kind,
        "summary": f"Operational concern detected in {_rand_word()} component",
        "confidence": confidence,
        "evidence_chain": [
            f"{_rand_word()} {_rand_word()} anomaly detected in {_rand_word()} subsystem"
            for _ in range(evidence_count)
        ],
        "snapshot_ids_used": list(range(1, snapshot_count + 1)),
        "uncertainty_notes": [
            f"Only {snapshot_count} snapshots available — {_rand_word()} may be incomplete",
            f"Signal may reflect transient {_rand_word()} fluctuation rather than structural issue",
        ],
        "related_recommendations": [f"Recommendation: review {_rand_word()} process"],
        "related_workflows": [],
        "related_runtime_events": [],
    }


def _bench(fn, runs: int = 10) -> float:
    """Return average elapsed ms over N runs."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return sum(times) / len(times)


# ---------------------------------------------------------------------------
# Benchmarks — Storage Optimizer (Phase 13B)
# ---------------------------------------------------------------------------

def bench_storage_optimizer_minimal() -> None:
    engine = StorageOptimizerEngine()
    print("\n=== Storage Optimizer (minimal inputs) ===")
    print(f"{'Run':>6}  {'Avg ms':>8}")
    avg = _bench(lambda: engine.generate(
        snapshot_count=500,
        max_snapshot_count=1000,
        db_size_bytes=50 * 1024 * 1024,
        disk_total_bytes=20 * 1024 * 1024 * 1024,
        disk_used_bytes=8 * 1024 * 1024 * 1024,
    ))
    print(f"{'minimal':>6}  {avg:>8.3f}")


def bench_storage_optimizer_full() -> None:
    engine = StorageOptimizerEngine()
    print("\n=== Storage Optimizer (all inputs) ===")
    print(f"{'Run':>6}  {'Avg ms':>8}")
    avg = _bench(lambda: engine.generate(
        snapshot_count=850,
        max_snapshot_count=1000,
        db_size_bytes=200 * 1024 * 1024,
        disk_total_bytes=20 * 1024 * 1024 * 1024,
        disk_used_bytes=16 * 1024 * 1024 * 1024,
        db_growth_bytes_last_window=10 * 1024 * 1024,
        window_days=7,
        snapshot_growth_last_window=50,
        retention_days=30,
        deletion_count_last_run=8,
        total_count_last_run=900,
        db_page_count=50000,
        db_freelist_count=15000,
        cold_snapshot_count=200,
        oldest_snapshot_days=120,
        oversized_snapshot_count=30,
        oversized_estimated_bytes=60 * 1024 * 1024,
        avg_evidence_tokens_per_snapshot=12500.0,
    ))
    print(f"{'full':>6}  {avg:>8.3f}")


# ---------------------------------------------------------------------------
# Benchmarks — Investigation Quality (Phase 13C)
# ---------------------------------------------------------------------------

def bench_investigation_quality_score() -> None:
    engine = InvestigationQualityEngine()
    kinds = [
        "severity_increase", "recent_changes", "workflow_instability",
        "component_involvement", "recommendation_evidence", "concern_contribution",
    ]
    sizes = [3, 6, 10, 20]
    print("\n=== Investigation Quality Score ===")
    print(f"{'Kind':>28}  {'Evidence':>10}  {'Avg ms':>8}")
    for kind in kinds:
        for n in sizes:
            result = _make_investigation_result(kind=kind, evidence_count=n)
            avg = _bench(lambda r=result: engine.score(r))
            print(f"{kind:>28}  {n:>10}  {avg:>8.4f}")


def bench_investigation_triage() -> None:
    engine = InvestigationQualityEngine()
    kinds = [
        "severity_increase", "recent_changes", "workflow_instability",
    ]
    print("\n=== Investigation Triage ===")
    print(f"{'Kind':>28}  {'Completed':>10}  {'Avg ms':>8}")
    for kind in kinds:
        for completed_count in [0, 2, 4]:
            completed = kinds[:completed_count]
            result = _make_investigation_result(kind=kind)
            avg = _bench(lambda r=result, c=completed: engine.triage(r, completed_kinds=c))
            print(f"{kind:>28}  {completed_count:>10}  {avg:>8.4f}")


def bench_investigation_batch_score() -> None:
    engine = InvestigationQualityEngine()
    sizes = [5, 20, 50, 100]
    print("\n=== Investigation Batch Score ===")
    print(f"{'Batch size':>12}  {'Avg ms':>8}  {'ms/result':>10}")
    for n in sizes:
        results = [
            _make_investigation_result(
                kind=random.choice([
                    "severity_increase", "recent_changes", "component_involvement"
                ]),
                evidence_count=random.randint(2, 8),
            )
            for _ in range(n)
        ]
        avg = _bench(lambda r=results: engine.batch_score(r))
        print(f"{n:>12}  {avg:>8.3f}  {avg/n:>10.5f}")


# ---------------------------------------------------------------------------
# Benchmarks — Performance Profiler (Phase 13D)
# ---------------------------------------------------------------------------

def bench_performance_profiler() -> None:
    profiler = PerformanceProfiler()
    sizes = [5, 20, 50, 200]
    print("\n=== Performance Profiler (analyze) ===")
    print(f"{'Ops':>6}  {'Avg ms':>8}")
    for n in sizes:
        ops = [
            ProfiledOperation(
                name=random.choice(list(BUDGETS.keys())),
                elapsed_ms=random.uniform(1.0, 300.0),
                budget=BUDGETS[random.choice(list(BUDGETS.keys()))],
            )
            for _ in range(n)
        ]
        avg = _bench(lambda o=ops: profiler.analyze(o))
        print(f"{n:>6}  {avg:>8.4f}")


def bench_operation_timer() -> None:
    print("\n=== OperationTimer overhead ===")
    print(f"{'Op':>28}  {'Avg ms':>10}")
    budget = BUDGETS["investigation_quality"]
    avg = _bench(lambda: _timed_noop(budget))
    print(f"{'timer with budget (noop)':>28}  {avg:>10.4f}")
    avg = _bench(lambda: _timed_noop(None))
    print(f"{'timer no budget (noop)':>28}  {avg:>10.4f}")


def _timed_noop(budget) -> ProfiledOperation | None:
    with OperationTimer("noop", budget=budget) as t:
        pass
    return t.result


def bench_report_markdown() -> None:
    profiler = PerformanceProfiler()
    ops = [
        ProfiledOperation(name, random.uniform(1.0, 150.0), BUDGETS[name])
        for name in list(BUDGETS.keys())
    ]
    report = profiler.analyze(ops)
    print("\n=== Performance Report markdown() ===")
    avg = _bench(lambda: report.markdown())
    print(f"{'markdown render':>28}  {avg:>8.4f} ms")


# ---------------------------------------------------------------------------
# VPS budget compliance check — are Phase 13 additions within budget?
# ---------------------------------------------------------------------------

def check_vps_budget_compliance() -> None:
    """Run a single pass through Phase 13 engines and check against budgets."""
    profiler = PerformanceProfiler()
    quality_engine = InvestigationQualityEngine()
    optimizer = StorageOptimizerEngine()
    result = _make_investigation_result(evidence_count=6, snapshot_count=4)

    collected: list[ProfiledOperation] = []

    with OperationTimer("investigation_quality", budget=BUDGETS["investigation_quality"]) as t:
        quality_engine.score(result)
    collected.append(t.result)

    with OperationTimer("investigation_triage", budget=BUDGETS["investigation_triage"]) as t:
        quality_engine.triage(result, completed_kinds=["severity_increase"])
    collected.append(t.result)

    with OperationTimer("storage_optimizer", budget=BUDGETS["storage_optimizer"]) as t:
        optimizer.generate(
            snapshot_count=500,
            max_snapshot_count=1000,
            db_size_bytes=100 * 1024 * 1024,
            disk_total_bytes=20 * 1024 * 1024 * 1024,
            disk_used_bytes=10 * 1024 * 1024 * 1024,
            db_growth_bytes_last_window=5 * 1024 * 1024,
            window_days=7,
        )
    collected.append(t.result)

    report = profiler.analyze(collected)
    print("\n=== VPS Budget Compliance (Phase 13 engines, 1-run) ===")
    print(f"Status: {report.overall_status.upper()}")
    for op in report.operations:
        v = op.check_violation()
        flag = ""
        if v:
            flag = f"  *** {v.limit_type.upper()} VIOLATION: +{v.overage_ms:.1f}ms ***"
        print(f"  {op.name:<30} {op.elapsed_ms:>8.2f} ms{flag}")
    if report.observations:
        print("Observations:")
        for obs in report.observations:
            print(f"  - {obs}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    random.seed(42)
    print("Phase 13 Benchmarks — 10 runs averaged per measurement")
    bench_storage_optimizer_minimal()
    bench_storage_optimizer_full()
    bench_investigation_quality_score()
    bench_investigation_triage()
    bench_investigation_batch_score()
    bench_performance_profiler()
    bench_operation_timer()
    bench_report_markdown()
    check_vps_budget_compliance()
    print("\nDone.")
