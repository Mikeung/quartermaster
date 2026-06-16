"""
Benchmark: ecosystem synthesis performance.

Measures time to synthesize ecosystem summaries at varying input sizes.
Standalone script — not a pytest test.

Run: python -m benchmarks.bench_synthesis
"""

from __future__ import annotations

import time
from typing import Any

from cognition.synthesis import EcosystemSynthesisEngine


def _make_snapshot(i: int, pkg_count: int = 3, provider_count: int = 1) -> dict[str, Any]:
    """Create a minimal synthetic snapshot for benchmarking."""
    return {
        "id": i,
        "created_at": f"2026-01-{i:02d}T00:00:00",
        "data": {
            "recommendations": [
                {"title": f"rec_{j}", "category": "cost", "impact": "high",
                 "confidence": 0.8, "urgency": "review", "evidence": ["signal"]}
                for j in range(5)
            ],
            "cost_observations": [],
            "runtime_health": {"health_score": 0.7, "overall_status": "healthy",
                                "instability_signals": [], "failed_services": []},
            "llm_detections": [{"provider": f"p{k}"} for k in range(provider_count)],
            "scanner_results": {"results": {
                "repo_scanner": {"packages": [f"pkg{k}" for k in range(pkg_count)]}
            }},
            "workflows": [],
        },
    }


def bench_synthesis_by_snapshot_count() -> None:
    engine = EcosystemSynthesisEngine()
    counts = [1, 5, 10, 25, 50]
    print("\n=== Synthesis Benchmark: snapshot count ===")
    print(f"{'Snapshots':>12} {'Time (ms)':>12}")
    print("-" * 26)
    for n in counts:
        snaps = [_make_snapshot(i) for i in range(1, n + 1)]
        t0 = time.perf_counter()
        for _ in range(10):
            engine.synthesize(snaps)
        elapsed = (time.perf_counter() - t0) / 10 * 1000
        print(f"{n:>12} {elapsed:>11.2f}ms")


def bench_synthesis_by_pattern_count() -> None:
    engine = EcosystemSynthesisEngine()
    snaps = [_make_snapshot(i) for i in range(1, 11)]
    pattern_counts = [0, 2, 5, 9]
    _pattern_names = [
        "retry_amplification", "ocr_token_amplification", "cost_blind_rag",
        "framework_stacking", "orchestration_sprawl", "single_provider_dependency",
        "volatile_provider_switching", "unstable_worker_pattern", "compound_rag_agent_amplification",
    ]
    print("\n=== Synthesis Benchmark: pattern count ===")
    print(f"{'Patterns':>10} {'Time (ms)':>12}")
    print("-" * 24)
    for n in pattern_counts:
        patterns = [{"name": _pattern_names[i], "matched": True} for i in range(n)]
        t0 = time.perf_counter()
        for _ in range(10):
            engine.synthesize(snaps, patterns=patterns)
        elapsed = (time.perf_counter() - t0) / 10 * 1000
        print(f"{n:>10} {elapsed:>11.2f}ms")


if __name__ == "__main__":
    bench_synthesis_by_snapshot_count()
    bench_synthesis_by_pattern_count()
    print("\nBenchmark complete.")
