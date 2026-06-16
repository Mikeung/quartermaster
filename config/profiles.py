"""
Deployment profiles — lightweight configuration bundles for different deployment contexts.

Three profiles:
- minimal:  low-resource VPS, infrequent scans, minimal retention
- standard: typical production VPS, regular scans, standard retention (DEFAULT)
- extended: comprehensive monitoring, frequent scans, long retention

Profiles are starting points, not constraints.
Individual .env settings override profile defaults at runtime.

No dynamic auto-tuning. Deterministic. Explicit.

Usage:
    from config.profiles import get_profile, STANDARD
    profile = get_profile("standard")
    print(profile.scan_interval_seconds)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeploymentProfile:
    """
    A named deployment configuration bundle.

    All values are overridable via environment variables / .env.
    Profiles provide safe defaults; they do not constrain operators.
    """
    name: str
    description: str

    # Scanning
    scan_interval_seconds: int       # how often to run a full scan
    scan_targets: str                # comma-separated scan targets

    # Retention
    retention_days: int              # keep snapshots newer than this
    max_snapshot_count: int          # hard cap on stored snapshots
    min_keep_count: int              # always keep at least this many (safety floor)

    # Runtime scanning
    runtime_scanning_enabled: bool   # enable psutil-based runtime scanner
    runtime_scan_depth: str          # "basic" | "standard" | "deep"

    # Report generation
    report_generation_enabled: bool  # auto-generate reports after scan
    report_formats: tuple[str, ...]  # ("markdown",) or ("markdown", "json")

    # Audit and benchmarks
    audit_on_startup: bool           # run snapshot audit at startup
    benchmark_enabled: bool          # include benchmark tooling in runtime

    # History and logging
    history_depth: int               # snapshots to include in temporal analysis
    log_level: str                   # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    log_format: str                  # "json" | "text"

    # Scheduler
    scheduler_grace_seconds: int     # misfire grace time for APScheduler
    stale_threshold_multiplier: float  # N x interval = "stale" threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "scan_interval_seconds": self.scan_interval_seconds,
            "scan_targets": self.scan_targets,
            "retention_days": self.retention_days,
            "max_snapshot_count": self.max_snapshot_count,
            "min_keep_count": self.min_keep_count,
            "runtime_scanning_enabled": self.runtime_scanning_enabled,
            "runtime_scan_depth": self.runtime_scan_depth,
            "report_generation_enabled": self.report_generation_enabled,
            "report_formats": list(self.report_formats),
            "audit_on_startup": self.audit_on_startup,
            "benchmark_enabled": self.benchmark_enabled,
            "history_depth": self.history_depth,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "scheduler_grace_seconds": self.scheduler_grace_seconds,
            "stale_threshold_multiplier": self.stale_threshold_multiplier,
        }


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

MINIMAL = DeploymentProfile(
    name="minimal",
    description=(
        "Low-resource VPS. Infrequent scans. Minimal retention. "
        "Suitable for small repos or low-priority monitoring."
    ),
    scan_interval_seconds=900,           # every 15 minutes
    scan_targets=".",
    retention_days=7,
    max_snapshot_count=50,
    min_keep_count=5,
    runtime_scanning_enabled=False,      # skip psutil to reduce overhead
    runtime_scan_depth="basic",
    report_generation_enabled=False,     # manual report generation only
    report_formats=("markdown",),
    audit_on_startup=False,
    benchmark_enabled=False,
    history_depth=10,
    log_level="WARNING",
    log_format="json",
    scheduler_grace_seconds=30,
    stale_threshold_multiplier=3.0,
)

STANDARD = DeploymentProfile(
    name="standard",
    description=(
        "Standard production VPS. Regular scans. 30-day retention. "
        "Recommended default for most deployments."
    ),
    scan_interval_seconds=300,           # every 5 minutes
    scan_targets=".",
    retention_days=30,
    max_snapshot_count=200,
    min_keep_count=10,
    runtime_scanning_enabled=True,
    runtime_scan_depth="standard",
    report_generation_enabled=True,
    report_formats=("markdown",),
    audit_on_startup=True,
    benchmark_enabled=False,
    history_depth=25,
    log_level="INFO",
    log_format="json",
    scheduler_grace_seconds=60,
    stale_threshold_multiplier=3.0,
)

EXTENDED = DeploymentProfile(
    name="extended",
    description=(
        "Comprehensive monitoring. Frequent scans. 90-day retention. "
        "For high-activity repos requiring deep operational visibility."
    ),
    scan_interval_seconds=120,           # every 2 minutes
    scan_targets=".",
    retention_days=90,
    max_snapshot_count=1000,
    min_keep_count=20,
    runtime_scanning_enabled=True,
    runtime_scan_depth="deep",
    report_generation_enabled=True,
    report_formats=("markdown", "json"),
    audit_on_startup=True,
    benchmark_enabled=True,
    history_depth=50,
    log_level="INFO",
    log_format="json",
    scheduler_grace_seconds=120,
    stale_threshold_multiplier=2.0,
)

_PROFILES: dict[str, DeploymentProfile] = {
    "minimal": MINIMAL,
    "standard": STANDARD,
    "extended": EXTENDED,
}

# ---------------------------------------------------------------------------
# Access helpers
# ---------------------------------------------------------------------------

def get_profile(name: str) -> DeploymentProfile:
    """Return a deployment profile by name. Raises ValueError for unknown names."""
    name = name.lower().strip()
    if name not in _PROFILES:
        valid = ", ".join(sorted(_PROFILES.keys()))
        raise ValueError(f"Unknown deployment profile '{name}'. Valid: {valid}")
    return _PROFILES[name]


def list_profiles() -> list[DeploymentProfile]:
    """Return all profiles sorted by scan interval (minimal first)."""
    return sorted(_PROFILES.values(), key=lambda p: p.scan_interval_seconds, reverse=True)


def profile_names() -> list[str]:
    """Return all valid profile names."""
    return sorted(_PROFILES.keys())
