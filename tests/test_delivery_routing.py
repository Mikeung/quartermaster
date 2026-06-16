"""
Tests for delivery/routing.py — Phase 14 Task 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from delivery.routing import (
    DeliveryRouter,
    RoutingConfig,
    _parse_hhmm,
)

# ---------------------------------------------------------------------------
# _parse_hhmm helper
# ---------------------------------------------------------------------------

class TestParseHhMm:
    def test_valid(self):
        assert _parse_hhmm("08:00") == 8 * 60
        assert _parse_hhmm("22:30") == 22 * 60 + 30
        assert _parse_hhmm("00:00") == 0

    def test_invalid_format(self):
        assert _parse_hhmm("8") is None
        assert _parse_hhmm("2300") is None
        assert _parse_hhmm("") is None

    def test_out_of_range(self):
        assert _parse_hhmm("25:00") is None
        assert _parse_hhmm("08:60") is None

    def test_whitespace_stripped(self):
        assert _parse_hhmm(" 08:00 ") == 8 * 60


# ---------------------------------------------------------------------------
# Severity routing
# ---------------------------------------------------------------------------

class TestSeverityRouting:
    def _router(self) -> DeliveryRouter:
        cfg = RoutingConfig(quiet_hours_enabled=False)
        return DeliveryRouter(cfg)

    def test_info_routes_to_digest(self):
        decision = self._router().decide("info")
        assert decision.routed_to == "digest"
        assert decision.should_deliver is True

    def test_warning_routes_to_digest(self):
        decision = self._router().decide("warning")
        assert decision.routed_to == "digest"
        assert decision.should_deliver is True

    def test_critical_routes_immediate(self):
        decision = self._router().decide("critical")
        assert decision.routed_to == "immediate"
        assert decision.should_deliver is True

    def test_unknown_severity_routes_to_digest(self):
        decision = self._router().decide("unknown")
        assert decision.routed_to == "digest"

    def test_case_insensitive(self):
        decision = self._router().decide("CRITICAL")
        assert decision.routed_to == "immediate"


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

class TestQuietHours:
    def _router_with_quiet(self, start="22:00", end="08:00") -> DeliveryRouter:
        cfg = RoutingConfig(
            quiet_hours_start=start,
            quiet_hours_end=end,
            quiet_hours_enabled=True,
        )
        return DeliveryRouter(cfg)

    def _at_hour(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 1, 15, hour, minute, tzinfo=UTC)

    def test_during_quiet_window_overnight(self):
        router = self._router_with_quiet("22:00", "08:00")
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(23, 30)
            decision = router.decide("critical")
        assert decision.routed_to == "suppressed"
        assert decision.suppression_reason == "quiet_hour"

    def test_during_quiet_window_early_morning(self):
        router = self._router_with_quiet("22:00", "08:00")
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(3, 0)
            decision = router.decide("critical")
        assert decision.suppression_reason == "quiet_hour"

    def test_outside_quiet_window_delivers(self):
        router = self._router_with_quiet("22:00", "08:00")
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(12, 0)
            decision = router.decide("critical")
        assert decision.routed_to == "immediate"
        assert decision.should_deliver is True

    def test_quiet_hours_disabled_ignores_window(self):
        cfg = RoutingConfig(
            quiet_hours_start="22:00",
            quiet_hours_end="08:00",
            quiet_hours_enabled=False,
        )
        router = DeliveryRouter(cfg)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(23, 0)
            decision = router.decide("critical")
        assert decision.routed_to == "immediate"

    def test_same_day_quiet_window(self):
        # 08:00–22:00 → quiet DURING business hours
        router = self._router_with_quiet("08:00", "22:00")
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(14, 0)
            decision = router.decide("critical")
        assert decision.suppression_reason == "quiet_hour"

    def test_same_day_quiet_window_outside(self):
        router = self._router_with_quiet("08:00", "22:00")
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(23, 0)
            decision = router.decide("critical")
        assert decision.routed_to == "immediate"

    def test_warning_not_affected_by_quiet(self):
        router = self._router_with_quiet()
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(23, 0)
            decision = router.decide("warning")
        # warnings always → digest, not affected by quiet hours
        assert decision.routed_to == "digest"


# ---------------------------------------------------------------------------
# Duplicate suppression
# ---------------------------------------------------------------------------

class TestDuplicateSuppression:
    def _router(self) -> DeliveryRouter:
        cfg = RoutingConfig(
            quiet_hours_enabled=False,
            dedup_window_seconds=3600,
        )
        return DeliveryRouter(cfg)

    def _at_hour(self, hour: int) -> datetime:
        return datetime(2026, 1, 15, hour, 0, tzinfo=UTC)

    def test_first_alert_passes(self):
        router = self._router()
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(12)
            decision = router.decide("critical", alert_type="scheduler_degraded")
        assert decision.routed_to == "immediate"

    def test_same_type_within_window_suppressed(self):
        router = self._router()
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            router.decide("critical", alert_type="scheduler_degraded")
            # 30 min later — still in window
            mock_dt.now.return_value = base + timedelta(minutes=30)
            decision = router.decide("critical", alert_type="scheduler_degraded")
        assert decision.suppression_reason == "duplicate"

    def test_different_type_passes(self):
        router = self._router()
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            router.decide("critical", alert_type="scheduler_degraded")
            mock_dt.now.return_value = base + timedelta(minutes=5)
            decision = router.decide("critical", alert_type="storage_pressure")
        assert decision.routed_to == "immediate"

    def test_same_type_after_window_passes(self):
        router = self._router()
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            router.decide("critical", alert_type="my_alert")
            # 2 hours later — outside dedup window
            mock_dt.now.return_value = base + timedelta(hours=2)
            decision = router.decide("critical", alert_type="my_alert")
        assert decision.routed_to == "immediate"

    def test_no_alert_type_no_dedup(self):
        router = self._router()
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            router.decide("critical")
            mock_dt.now.return_value = base + timedelta(minutes=5)
            decision = router.decide("critical")
        # No alert_type → no dedup check
        assert decision.suppression_reason != "duplicate"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def _router(self, max_per_hour: int = 3) -> DeliveryRouter:
        cfg = RoutingConfig(
            quiet_hours_enabled=False,
            max_immediate_per_hour=max_per_hour,
        )
        return DeliveryRouter(cfg)

    def _at_hour(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 1, 15, hour, minute, tzinfo=UTC)

    def test_under_limit_passes(self):
        router = self._router(max_per_hour=5)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = self._at_hour(12)
            for _ in range(4):
                decision = router.decide("critical")
            assert decision.routed_to == "immediate"

    def test_at_limit_suppressed(self):
        router = self._router(max_per_hour=3)
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            for _ in range(3):
                router.decide("critical")
            # 4th should be suppressed
            decision = router.decide("critical")
        assert decision.suppression_reason == "rate_limit"

    def test_rate_limit_resets_after_hour(self):
        router = self._router(max_per_hour=2)
        base = self._at_hour(12)
        with patch("delivery.routing.datetime") as mock_dt:
            mock_dt.now.return_value = base
            for _ in range(2):
                router.decide("critical")
            # 1+ hour later
            mock_dt.now.return_value = base + timedelta(hours=1, minutes=1)
            decision = router.decide("critical")
        assert decision.routed_to == "immediate"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_stats_structure(self):
        router = DeliveryRouter()
        stats = router.get_stats()
        assert "immediate_this_hour" in stats
        assert "max_immediate_per_hour" in stats
        assert "quiet_hours_enabled" in stats
        assert "currently_quiet" in stats

    def test_initial_state(self):
        router = DeliveryRouter()
        stats = router.get_stats()
        assert stats["immediate_this_hour"] == 0
