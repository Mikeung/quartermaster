"""
Run all benchmarks.

Run: python -m benchmarks.run_all
"""

from __future__ import annotations

from benchmarks.bench_snapshot_scale import (
    bench_audit_by_snapshot_count,
    bench_drift_by_snapshot_count,
)
from benchmarks.bench_synthesis import (
    bench_synthesis_by_pattern_count,
    bench_synthesis_by_snapshot_count,
)


def main() -> None:
    print("quartermaster benchmarks")
    print("=" * 40)
    bench_synthesis_by_snapshot_count()
    bench_synthesis_by_pattern_count()
    bench_drift_by_snapshot_count()
    bench_audit_by_snapshot_count()
    print("\n" + "=" * 40)
    print("All benchmarks complete.")


if __name__ == "__main__":
    main()
