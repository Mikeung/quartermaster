"""
Delivery health tracking — thread-safe in-memory metrics for Telegram delivery.

Tracks: successes, failures, suppressions (quiet-hour / duplicate / rate-limit),
latency samples, and last-seen timestamps.

Used by: TelegramDeliveryClient, DeliveryRouter, selfcheck, maintenance report.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_MAX_LATENCY_SAMPLES = 50   # cap ring buffer


@dataclass
class DeliveryHealthSummary:
    """Point-in-time snapshot of delivery metrics."""
    telegram_enabled: bool
    success_count: int
    failure_count: int
    quiet_hour_suppression_count: int
    duplicate_suppression_count: int
    rate_limit_suppression_count: int
    total_suppression_count: int
    avg_latency_ms: float | None
    last_success_at: str | None
    last_failure_at: str | None
    last_failure_error: str | None
    generated_at: str

    @property
    def error_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.failure_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegram_enabled": self.telegram_enabled,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "quiet_hour_suppression_count": self.quiet_hour_suppression_count,
            "duplicate_suppression_count": self.duplicate_suppression_count,
            "rate_limit_suppression_count": self.rate_limit_suppression_count,
            "total_suppression_count": self.total_suppression_count,
            "avg_latency_ms": self.avg_latency_ms,
            "error_rate": round(self.error_rate, 4),
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_failure_error": self.last_failure_error,
            "generated_at": self.generated_at,
        }


class DeliveryHealthTracker:
    """
    Thread-safe in-memory tracker for Telegram delivery metrics.

    Intentionally unbounded in error/success counts (resets on restart).
    Latency ring buffer is capped at _MAX_LATENCY_SAMPLES.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._success_count: int = 0
        self._failure_count: int = 0
        self._quiet_hour_count: int = 0
        self._duplicate_count: int = 0
        self._rate_limit_count: int = 0
        self._latency_samples: list[float] = []
        self._last_success_at: str | None = None
        self._last_failure_at: str | None = None
        self._last_failure_error: str | None = None

    def record_success(self, latency_ms: float) -> None:
        with self._lock:
            self._success_count += 1
            self._last_success_at = datetime.now(UTC).isoformat()
            self._latency_samples.append(latency_ms)
            if len(self._latency_samples) > _MAX_LATENCY_SAMPLES:
                self._latency_samples.pop(0)

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_at = datetime.now(UTC).isoformat()
            # Truncate error for storage — never store full traceback
            self._last_failure_error = str(error)[:200]

    def record_suppression(self, reason: str) -> None:
        """reason: "quiet_hour" | "duplicate" | "rate_limit" """
        with self._lock:
            if reason == "quiet_hour":
                self._quiet_hour_count += 1
            elif reason == "duplicate":
                self._duplicate_count += 1
            elif reason == "rate_limit":
                self._rate_limit_count += 1

    def get_summary(self, telegram_enabled: bool = True) -> DeliveryHealthSummary:
        with self._lock:
            avg = (
                sum(self._latency_samples) / len(self._latency_samples)
                if self._latency_samples
                else None
            )
            return DeliveryHealthSummary(
                telegram_enabled=telegram_enabled,
                success_count=self._success_count,
                failure_count=self._failure_count,
                quiet_hour_suppression_count=self._quiet_hour_count,
                duplicate_suppression_count=self._duplicate_count,
                rate_limit_suppression_count=self._rate_limit_count,
                total_suppression_count=(
                    self._quiet_hour_count
                    + self._duplicate_count
                    + self._rate_limit_count
                ),
                avg_latency_ms=round(avg, 1) if avg is not None else None,
                last_success_at=self._last_success_at,
                last_failure_at=self._last_failure_at,
                last_failure_error=self._last_failure_error,
                generated_at=datetime.now(UTC).isoformat(),
            )


# Module-level singleton — accessible throughout the process lifetime
_global_tracker = DeliveryHealthTracker()


def get_tracker() -> DeliveryHealthTracker:
    """Return the process-wide delivery health tracker."""
    return _global_tracker
