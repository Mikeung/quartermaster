"""
Phase 12 benchmarks — deduplication, evidence compression, and report refinement.

Run with:  python benchmarks/bench_phase12.py
Not a pytest file — uses perf_counter with 10-run averaging.
"""

from __future__ import annotations

import random
import string
import time

from cognition.deduplication import SignalDeduplicationEngine
from cognition.evidence_compression import EvidenceCompressor
from reports.refinement import ReportRefinementEngine

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _rand_word(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _make_recommendations(n: int, duplicate_fraction: float = 0.3) -> list[dict]:
    unique = max(1, int(n * (1 - duplicate_fraction)))
    unique_recs = [
        {
            "title": f"Fix {_rand_word()} issue in {_rand_word()} component",
            "category": random.choice(["cost", "orchestration", "provider", "runtime"]),
            "confidence": round(random.uniform(0.3, 0.95), 2),
            "evidence": [f"{_rand_word()} evidence {i}" for i in range(random.randint(3, 10))],
        }
        for _ in range(unique)
    ]
    recs = list(unique_recs)
    while len(recs) < n:
        base = random.choice(unique_recs)
        recs.append(dict(base))
    return recs[:n]


def _make_evidence_chain(n: int, repeat_fraction: float = 0.4) -> list[str]:
    unique_count = max(1, int(n * (1 - repeat_fraction)))
    unique_ev = [
        f"{_rand_word()} {_rand_word()} event occurred in {_rand_word()} module"
        for _ in range(unique_count)
    ]
    ev = list(unique_ev)
    while len(ev) < n:
        ev.append(random.choice(unique_ev))
    return ev[:n]


def _bench(fn, runs: int = 10) -> float:
    """Return average elapsed ms over N runs."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return sum(times) / len(times)


# -----------------------------------------------------------------------
# Benchmarks
# -----------------------------------------------------------------------

def bench_deduplication() -> None:
    engine = SignalDeduplicationEngine()
    sizes = [50, 200, 500, 1000]
    print("\n=== Signal Deduplication ===")
    print(f"{'Size':>8}  {'Avg ms':>8}  {'ms/rec':>8}")
    for n in sizes:
        recs = _make_recommendations(n, duplicate_fraction=0.3)
        avg = _bench(lambda r=recs: engine.deduplicate(r))
        print(f"{n:>8}  {avg:>8.2f}  {avg/n:>8.4f}")


def bench_evidence_dedup() -> None:
    engine = SignalDeduplicationEngine()
    sizes = [20, 100, 500, 2000]
    print("\n=== Evidence String Deduplication ===")
    print(f"{'Size':>8}  {'Avg ms':>8}")
    for n in sizes:
        ev = _make_evidence_chain(n, repeat_fraction=0.4)
        avg = _bench(lambda e=ev: engine.deduplicate_evidence(e))
        print(f"{n:>8}  {avg:>8.2f}")


def bench_evidence_compression() -> None:
    compressor = EvidenceCompressor()
    sizes = [10, 25, 100, 300]
    print("\n=== Evidence Compression ===")
    print(f"{'Size':>8}  {'Avg ms':>8}  {'Compressed':>12}")
    for n in sizes:
        ev = _make_evidence_chain(n, repeat_fraction=0.5)
        result = compressor.compress(ev)
        avg = _bench(lambda e=ev: compressor.compress(e))
        print(f"{n:>8}  {avg:>8.2f}  {result.compressed_count:>12}")


def bench_compact_recommendations() -> None:
    engine = ReportRefinementEngine()
    sizes = [20, 100, 300, 500]
    print("\n=== Compact Recommendations (dedup + compress) ===")
    print(f"{'Input':>8}  {'Avg ms':>8}  {'Output':>8}  {'DeupRatio':>10}")
    for n in sizes:
        recs = _make_recommendations(n, duplicate_fraction=0.35)
        result = engine.compact_recommendations(recs, max_output=10)
        avg = _bench(lambda r=recs: engine.compact_recommendations(r, max_output=10))
        print(f"{n:>8}  {avg:>8.2f}  {result.output_count:>8}  {result.dedup_ratio:>10.2%}")


def bench_executive_summary() -> None:
    engine = ReportRefinementEngine()
    sizes = [5, 20, 50, 100]
    print("\n=== Executive Summary Generation ===")
    print(f"{'Recs':>8}  {'Avg ms':>8}")
    for n in sizes:
        high_priority = _make_recommendations(n, duplicate_fraction=0.2)
        report = {
            "overall_status": random.choice(["ok", "warning", "critical"]),
            "high_priority": high_priority,
            "runtime_concerns": [{"message": f"Concern {i}"} for i in range(3)],
            "warning_count": n // 3,
            "critical_count": n // 10,
        }
        avg = _bench(lambda r=report: engine.executive_summary(r))
        print(f"{n:>8}  {avg:>8.4f}")


def bench_suppress_low_confidence() -> None:
    engine = ReportRefinementEngine()
    sizes = [100, 1000, 5000]
    print("\n=== Low-Confidence Suppression ===")
    print(f"{'Input':>8}  {'Avg ms':>8}  {'Passed':>8}")
    for n in sizes:
        recs = _make_recommendations(n, duplicate_fraction=0.0)
        passed = engine.suppress_low_confidence(recs, threshold=0.35)
        avg = _bench(lambda r=recs: engine.suppress_low_confidence(r, threshold=0.35))
        print(f"{n:>8}  {avg:>8.3f}  {len(passed):>8}")


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

if __name__ == "__main__":
    random.seed(42)
    print("Phase 12 Benchmarks — 10 runs averaged per measurement")
    bench_deduplication()
    bench_evidence_dedup()
    bench_evidence_compression()
    bench_compact_recommendations()
    bench_executive_summary()
    bench_suppress_low_confidence()
    print("\nDone.")
