"""
Benchmark: snapshot operations at scale.

Measures report generation and audit performance as snapshot count grows.
Standalone script — not a pytest test.

Run: python -m benchmarks.bench_snapshot_scale
"""

from __future__ import annotations

import time
from typing import Any

from cognition.systemic_drift import SystemicDriftEngine
from tools.snapshot_audit import SnapshotAuditor


def _make_snapshot(i: int) -> dict[str, Any]:
    return {
        "id": i,
        "created_at": f"2026-01-{min(i, 28):02d}T{i % 24:02d}:00:00",
        "data": {
            "recommendations": [
                {"title": f"rec_{j}", "category": "cost", "impact": "high",
                 "confidence": 0.8, "urgency": "review", "evidence": [f"evidence {j}"]}
                for j in range(3)
            ],
            "cost_observations": [],
            "runtime_health": {"health_score": 0.8, "overall_status": "healthy",
                                "instability_signals": []},
            "llm_detections": [{"provider": "openai"}],
            "scanner_results": {"results": {"repo_scanner": {"packages": ["langchain"]}}},
            "workflows": [],
            "drift_events": [],
        },
    }


def bench_drift_by_snapshot_count() -> None:
    engine = SystemicDriftEngine()
    counts = [2, 5, 10, 25, 50]
    print("\n=== Drift Analysis Benchmark: snapshot count ===")
    print(f"{'Snapshots':>12} {'Time (ms)':>12}")
    print("-" * 26)
    for n in counts:
        snaps = [_make_snapshot(i) for i in range(1, n + 1)]
        t0 = time.perf_counter()
        for _ in range(10):
            engine.analyze(snaps)
        elapsed = (time.perf_counter() - t0) / 10 * 1000
        print(f"{n:>12} {elapsed:>11.2f}ms")


def bench_audit_by_snapshot_count() -> None:
    auditor = SnapshotAuditor()
    counts = [5, 10, 25, 50, 100]
    print("\n=== Snapshot Audit Benchmark: snapshot count ===")
    print(f"{'Snapshots':>12} {'Time (ms)':>12}")
    print("-" * 26)
    for n in counts:
        snaps = [_make_snapshot(i) for i in range(1, n + 1)]
        t0 = time.perf_counter()
        for _ in range(10):
            auditor.audit(snaps)
        elapsed = (time.perf_counter() - t0) / 10 * 1000
        print(f"{n:>12} {elapsed:>11.2f}ms")


if __name__ == "__main__":
    bench_drift_by_snapshot_count()
    bench_audit_by_snapshot_count()
    print("\nBenchmark complete.")
