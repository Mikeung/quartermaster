"""Tests for config/profiles.py — deployment profiles."""

import pytest

from config.profiles import (
    EXTENDED,
    MINIMAL,
    STANDARD,
    get_profile,
    list_profiles,
    profile_names,
)


class TestDeploymentProfile:
    def test_minimal_profile_exists(self):
        assert MINIMAL.name == "minimal"
        assert MINIMAL.scan_interval_seconds == 900
        assert MINIMAL.retention_days == 7
        assert MINIMAL.max_snapshot_count == 50
        assert MINIMAL.min_keep_count == 5
        assert MINIMAL.runtime_scanning_enabled is False

    def test_standard_profile_exists(self):
        assert STANDARD.name == "standard"
        assert STANDARD.scan_interval_seconds == 300
        assert STANDARD.retention_days == 30
        assert STANDARD.max_snapshot_count == 200
        assert STANDARD.min_keep_count == 10
        assert STANDARD.runtime_scanning_enabled is True

    def test_extended_profile_exists(self):
        assert EXTENDED.name == "extended"
        assert EXTENDED.scan_interval_seconds == 120
        assert EXTENDED.retention_days == 90
        assert EXTENDED.max_snapshot_count == 1000
        assert EXTENDED.min_keep_count == 20
        assert EXTENDED.runtime_scanning_enabled is True

    def test_profile_is_frozen(self):
        with pytest.raises(AttributeError):
            STANDARD.scan_interval_seconds = 999  # type: ignore[misc]

    def test_to_dict_keys(self):
        d = STANDARD.to_dict()
        assert "name" in d
        assert "scan_interval_seconds" in d
        assert "retention_days" in d
        assert "max_snapshot_count" in d
        assert "min_keep_count" in d
        assert "runtime_scanning_enabled" in d
        assert "report_formats" in d

    def test_to_dict_report_formats_is_list(self):
        d = STANDARD.to_dict()
        assert isinstance(d["report_formats"], list)

    def test_extended_report_formats(self):
        assert "json" in EXTENDED.report_formats
        assert "markdown" in EXTENDED.report_formats

    def test_min_keep_count_safety_floor(self):
        # min_keep_count must always be ≤ max_snapshot_count
        for profile in [MINIMAL, STANDARD, EXTENDED]:
            assert profile.min_keep_count <= profile.max_snapshot_count

    def test_stale_threshold_multiplier_positive(self):
        for profile in [MINIMAL, STANDARD, EXTENDED]:
            assert profile.stale_threshold_multiplier > 0


class TestGetProfile:
    def test_get_standard(self):
        p = get_profile("standard")
        assert p.name == "standard"

    def test_get_minimal(self):
        p = get_profile("minimal")
        assert p.name == "minimal"

    def test_get_extended(self):
        p = get_profile("extended")
        assert p.name == "extended"

    def test_case_insensitive(self):
        p = get_profile("STANDARD")
        assert p.name == "standard"

    def test_strips_whitespace(self):
        p = get_profile("  standard  ")
        assert p.name == "standard"

    def test_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown deployment profile"):
            get_profile("nonexistent")


class TestListProfiles:
    def test_returns_three_profiles(self):
        profiles = list_profiles()
        assert len(profiles) == 3

    def test_sorted_by_interval_ascending(self):
        profiles = list_profiles()
        # list_profiles sorts by interval reverse=True (minimal first = highest interval)
        intervals = [p.scan_interval_seconds for p in profiles]
        assert intervals == sorted(intervals, reverse=True)

    def test_profile_names(self):
        names = profile_names()
        assert "minimal" in names
        assert "standard" in names
        assert "extended" in names
        assert names == sorted(names)
