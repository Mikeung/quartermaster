"""
Tests for delivery/formatting.py — Phase 14 Task 4.
"""

from __future__ import annotations

from delivery.formatting import (
    _escape,
    _finalize,
    _status_icon,
    format_critical_alert,
    format_daily_digest,
    format_storage_pressure_warning,
    format_survivability_warning,
    format_weekly_digest,
)

# ---------------------------------------------------------------------------
# _escape
# ---------------------------------------------------------------------------

class TestEscape:
    def test_plain_text(self):
        assert _escape("hello") == "hello"

    def test_amp(self):
        assert _escape("a & b") == "a &amp; b"

    def test_lt_gt(self):
        assert _escape("<x>") == "&lt;x&gt;"


# ---------------------------------------------------------------------------
# _status_icon
# ---------------------------------------------------------------------------

class TestStatusIcon:
    def test_ok(self):
        assert _status_icon("ok") == "✅"

    def test_warning(self):
        assert _status_icon("warning") == "⚠️"

    def test_critical(self):
        assert _status_icon("critical") == "🚨"

    def test_unknown(self):
        assert _status_icon("unknown") == "ℹ️"

    def test_case_insensitive(self):
        assert _status_icon("OK") == "✅"


# ---------------------------------------------------------------------------
# _finalize
# ---------------------------------------------------------------------------

class TestFinalize:
    def test_short_message_unchanged(self):
        text = "hello world"
        assert _finalize(text) == text

    def test_long_message_truncated(self):
        text = "x" * 5000
        result = _finalize(text)
        assert len(result) <= 4096
        assert "truncated" in result


# ---------------------------------------------------------------------------
# format_daily_digest
# ---------------------------------------------------------------------------

class TestFormatDailyDigest:
    def _digest(self, **kwargs) -> str:
        defaults = {
            "system_status": "ok",
            "scan_count": 24,
            "snapshot_count": 142,
            "max_snapshot_count": 200,
        }
        defaults.update(kwargs)
        return format_daily_digest(**defaults)

    def test_contains_title(self):
        assert "Daily Operational Digest" in self._digest()

    def test_contains_system_status(self):
        assert "OK" in self._digest(system_status="ok")

    def test_contains_scan_count(self):
        assert "24" in self._digest()

    def test_contains_snapshot_fraction(self):
        assert "142/200" in self._digest()

    def test_snapshot_percentage(self):
        result = self._digest(snapshot_count=100, max_snapshot_count=200)
        assert "50%" in result

    def test_with_recommendations(self):
        result = self._digest(
            top_recommendations=["Fix OCR cost", "Review multi-agent config"],
            active_recommendation_count=5,
        )
        assert "Fix OCR cost" in result

    def test_recommendations_capped_at_3(self):
        recs = [f"Rec {i}" for i in range(10)]
        result = self._digest(top_recommendations=recs, active_recommendation_count=10)
        assert "Rec 0" in result
        assert "Rec 3" not in result

    def test_storage_info_present(self):
        result = self._digest(storage_status="warning", disk_pct=75.0)
        assert "75%" in result

    def test_fits_telegram_limit(self):
        result = self._digest(
            top_recommendations=["Rec 1", "Rec 2", "Rec 3"],
            active_recommendation_count=10,
        )
        assert len(result) <= 4096

    def test_html_tags_present(self):
        result = self._digest()
        assert "<b>" in result

    def test_critical_status_icon(self):
        result = self._digest(system_status="critical")
        assert "🚨" in result

    def test_generated_at_used(self):
        result = format_daily_digest(
            system_status="ok",
            scan_count=5,
            snapshot_count=10,
            max_snapshot_count=100,
            generated_at="2026-01-15 08:00 UTC",
        )
        assert "2026-01-15" in result


# ---------------------------------------------------------------------------
# format_critical_alert
# ---------------------------------------------------------------------------

class TestFormatCriticalAlert:
    def _alert(self, **kwargs) -> str:
        defaults = {
            "kind": "Scheduler Degraded",
            "summary": "scan_12345 failed 5 consecutive times",
        }
        defaults.update(kwargs)
        return format_critical_alert(**defaults)

    def test_contains_critical_icon(self):
        assert "🚨" in self._alert()

    def test_contains_kind(self):
        assert "Scheduler Degraded" in self._alert()

    def test_contains_summary(self):
        assert "scan_12345" in self._alert()

    def test_confidence_shown(self):
        result = self._alert(confidence=0.95)
        assert "95%" in result

    def test_no_confidence_when_zero(self):
        result = self._alert(confidence=0.0)
        assert "Confidence" not in result

    def test_evidence_shown(self):
        result = self._alert(evidence=["Job failed at 12:00", "Job failed at 12:05"])
        assert "12:00" in result

    def test_evidence_capped_at_3(self):
        result = self._alert(evidence=[f"ev{i}" for i in range(10)])
        assert "ev0" in result
        assert "ev3" not in result

    def test_action_message_present(self):
        assert "Action required" in self._alert()

    def test_html_entities_escaped(self):
        result = format_critical_alert(
            kind="Test <b> kind",
            summary="a & b > c",
        )
        assert "&lt;b&gt;" in result
        assert "&amp;" in result

    def test_fits_telegram_limit(self):
        result = self._alert(
            evidence=[f"long evidence string {i}" * 20 for i in range(10)]
        )
        assert len(result) <= 4096


# ---------------------------------------------------------------------------
# format_weekly_digest
# ---------------------------------------------------------------------------

class TestFormatWeeklyDigest:
    def _weekly(self, **kwargs) -> str:
        defaults = {
            "scan_count_7d": 168,
            "active_concern_count": 5,
            "resolved_count": 2,
            "new_count": 1,
        }
        defaults.update(kwargs)
        return format_weekly_digest(**defaults)

    def test_contains_title(self):
        assert "Weekly" in self._weekly()

    def test_contains_scan_count(self):
        assert "168" in self._weekly()

    def test_contains_concern_counts(self):
        result = self._weekly()
        assert "5" in result  # active

    def test_with_top_concerns(self):
        result = self._weekly(top_concerns=["Cost issue", "Stability concern"])
        assert "Cost issue" in result

    def test_concerns_capped_at_4(self):
        result = self._weekly(top_concerns=[f"Concern {i}" for i in range(10)])
        assert "Concern 3" in result
        assert "Concern 4" not in result

    def test_advisory_footer(self):
        assert "Advisory" in self._weekly()

    def test_fits_telegram_limit(self):
        assert len(self._weekly()) <= 4096


# ---------------------------------------------------------------------------
# format_survivability_warning
# ---------------------------------------------------------------------------

class TestFormatSurvivabilityWarning:
    def _warning(self, **kwargs) -> str:
        defaults = {
            "outlook": "attention_needed",
            "warning_checks": ["DB growth accelerating", "Old snapshots accumulating"],
        }
        defaults.update(kwargs)
        return format_survivability_warning(**defaults)

    def test_contains_warning_icon(self):
        assert "⚠️" in self._warning()

    def test_critical_shows_critical_icon(self):
        result = self._warning(critical_checks=["Disk full"])
        assert "🚨" in result

    def test_contains_outlook(self):
        assert "attention needed" in self._warning()

    def test_contains_warnings(self):
        result = self._warning()
        assert "DB growth" in result

    def test_critical_checks_shown(self):
        result = self._warning(critical_checks=["Catastrophic failure"])
        assert "Catastrophic failure" in result

    def test_fits_telegram_limit(self):
        assert len(self._warning()) <= 4096


# ---------------------------------------------------------------------------
# format_storage_pressure_warning
# ---------------------------------------------------------------------------

class TestFormatStoragePressureWarning:
    def _storage(self, **kwargs) -> str:
        defaults = {
            "pressure_level": "warning",
            "disk_pct": 78.5,
            "db_size_human": "45 MB",
        }
        defaults.update(kwargs)
        return format_storage_pressure_warning(**defaults)

    def test_contains_icon(self):
        assert "⚠️" in self._storage()

    def test_critical_has_critical_icon(self):
        assert "🚨" in self._storage(pressure_level="critical")

    def test_contains_pressure_level(self):
        assert "WARNING" in self._storage()

    def test_contains_disk_pct(self):
        result = self._storage(disk_pct=78.5)
        assert "78%" in result or "79%" in result  # rounded

    def test_contains_db_size(self):
        assert "45 MB" in self._storage()

    def test_snapshot_counts_shown(self):
        result = self._storage(snapshot_count=180, max_snapshot_count=200)
        assert "180/200" in result

    def test_observations_shown(self):
        result = self._storage(observations=["Fragmentation detected"])
        assert "Fragmentation" in result

    def test_observations_capped_at_3(self):
        obs = [f"Obs {i}" for i in range(10)]
        result = self._storage(observations=obs)
        assert "Obs 2" in result
        assert "Obs 3" not in result

    def test_fits_telegram_limit(self):
        assert len(self._storage()) <= 4096
