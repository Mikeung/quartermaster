"""
Delivery routing — severity-based routing, quiet hours, duplicate suppression, rate limiting.

Rules:
- CRITICAL → immediate delivery (subject to rate limit and quiet hours)
- WARNING  → digest queue (not immediate)
- INFO     → digest queue only

Quiet hours: no immediate delivery during configured window (UTC).
Duplicate suppression: same alert_type within dedup_window_seconds → suppress.
Rate limiting: max N immediate alerts per hour (default 10).

All state is in-memory. Resets on process restart.
Thread-safe.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_IMMEDIATE_PER_HOUR = 10
_DEFAULT_DEDUP_WINDOW_SECONDS = 3600     # 1 hour


@dataclass(frozen=True)
class RoutingConfig:
    """Immutable delivery routing policy."""
    quiet_hours_start: str = "22:00"      # "HH:MM" UTC
    quiet_hours_end: str = "08:00"        # "HH:MM" UTC
    max_immediate_per_hour: int = _DEFAULT_MAX_IMMEDIATE_PER_HOUR
    dedup_window_seconds: int = _DEFAULT_DEDUP_WINDOW_SECONDS
    quiet_hours_enabled: bool = True


@dataclass
class DeliveryDecision:
    """Result of a routing decision."""
    should_deliver: bool
    routed_to: str          # "immediate" | "digest" | "suppressed"
    suppression_reason: str | None = None  # "quiet_hour" | "duplicate" | "rate_limit" | None
    reason_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_deliver": self.should_deliver,
            "routed_to": self.routed_to,
            "suppression_reason": self.suppression_reason,
            "reason_text": self.reason_text,
        }


class DeliveryRouter:
    """
    Routes delivery decisions based on severity, quiet hours, dedup, and rate limits.

    Thread-safe. No external I/O. State is in-memory only.
    """

    def __init__(self, config: RoutingConfig | None = None) -> None:
        self._config = config or RoutingConfig()
        self._lock = threading.Lock()
        # Timestamps of recent immediate deliveries (for rate limiting)
        self._immediate_timestamps: list[datetime] = []
        # Last delivery time per alert_type (for dedup)
        self._last_delivery: dict[str, datetime] = {}

    def decide(
        self,
        severity: str,
        alert_type: str | None = None,
    ) -> DeliveryDecision:
        """
        Return a routing decision for the given severity and alert type.

        severity: "critical" | "warning" | "info"
        alert_type: optional string key for dedup (e.g. "scheduler_degraded")
        """
        sev = severity.lower()

        # Only explicit "critical" goes immediate — everything else → digest
        if sev != "critical":
            return DeliveryDecision(
                should_deliver=True,
                routed_to="digest",
                reason_text=f"{sev} severity → digest queue",
            )

        # CRITICAL path — check suppression conditions
        with self._lock:
            self._prune_old_timestamps()

            if self._config.quiet_hours_enabled and self._is_quiet_hour():
                logger.debug("Delivery suppressed: quiet hour")
                return DeliveryDecision(
                    should_deliver=False,
                    routed_to="suppressed",
                    suppression_reason="quiet_hour",
                    reason_text="Quiet hours active — deferred to next digest",
                )

            if alert_type and self._is_duplicate(alert_type):
                logger.debug("Delivery suppressed: duplicate", extra={"alert_type": alert_type})
                return DeliveryDecision(
                    should_deliver=False,
                    routed_to="suppressed",
                    suppression_reason="duplicate",
                    reason_text=f"Duplicate alert '{alert_type}' within dedup window",
                )

            if self._is_rate_limited():
                logger.debug("Delivery suppressed: rate limit")
                return DeliveryDecision(
                    should_deliver=False,
                    routed_to="suppressed",
                    suppression_reason="rate_limit",
                    reason_text=(
                        f"Rate limit: max {self._config.max_immediate_per_hour} "
                        "immediate alerts/hour reached"
                    ),
                )

            # Approved — record this delivery
            now = datetime.now(UTC)
            self._immediate_timestamps.append(now)
            if alert_type:
                self._last_delivery[alert_type] = now

        return DeliveryDecision(
            should_deliver=True,
            routed_to="immediate",
            reason_text="critical severity → immediate delivery",
        )

    def get_stats(self) -> dict[str, Any]:
        """Return current routing state for observability."""
        with self._lock:
            self._prune_old_timestamps()
            return {
                "immediate_this_hour": len(self._immediate_timestamps),
                "max_immediate_per_hour": self._config.max_immediate_per_hour,
                "dedup_tracked_types": len(self._last_delivery),
                "quiet_hours_enabled": self._config.quiet_hours_enabled,
                "quiet_hours_start": self._config.quiet_hours_start,
                "quiet_hours_end": self._config.quiet_hours_end,
                "currently_quiet": self._is_quiet_hour() if self._config.quiet_hours_enabled else False,
            }

    # ------------------------------------------------------------------
    # Internal — called under lock
    # ------------------------------------------------------------------

    def _is_quiet_hour(self) -> bool:
        """Return True if the current UTC time is inside the quiet window."""
        now = datetime.now(UTC)
        current = now.hour * 60 + now.minute
        start = _parse_hhmm(self._config.quiet_hours_start)
        end = _parse_hhmm(self._config.quiet_hours_end)

        if start is None or end is None:
            return False

        if start < end:
            # Same-day window (e.g. 08:00–22:00 → quiet during 8am-10pm)
            return start <= current < end
        else:
            # Overnight window (e.g. 22:00–08:00 → quiet from 10pm to 8am)
            return current >= start or current < end

    def _is_duplicate(self, alert_type: str) -> bool:
        """Return True if this alert type was delivered within the dedup window."""
        last = self._last_delivery.get(alert_type)
        if last is None:
            return False
        age_seconds = (datetime.now(UTC) - last).total_seconds()
        return age_seconds < self._config.dedup_window_seconds

    def _is_rate_limited(self) -> bool:
        """Return True if the per-hour immediate delivery limit is reached."""
        return len(self._immediate_timestamps) >= self._config.max_immediate_per_hour

    def _prune_old_timestamps(self) -> None:
        """Remove delivery timestamps older than 1 hour from the rate-limit window."""
        now = datetime.now(UTC)
        cutoff = 3600.0
        self._immediate_timestamps = [
            ts for ts in self._immediate_timestamps
            if (now - ts).total_seconds() < cutoff
        ]
        # Also prune dedup entries older than the dedup window
        dedup_cutoff = float(self._config.dedup_window_seconds)
        stale_keys = [
            k for k, ts in self._last_delivery.items()
            if (now - ts).total_seconds() >= dedup_cutoff
        ]
        for k in stale_keys:
            del self._last_delivery[k]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_hhmm(s: str) -> int | None:
    """Parse "HH:MM" → total minutes since midnight. Returns None on parse error."""
    try:
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m
    except (ValueError, AttributeError):
        return None
