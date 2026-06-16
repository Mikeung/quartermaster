"""Tests for memory/storage_hygiene.py — storage pressure engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from memory.storage_hygiene import StorageHygieneEngine, _human_bytes


class TestHumanBytes:
    def test_bytes(self):
        assert _human_bytes(500) == "500.0 B"

    def test_kilobytes(self):
        result = _human_bytes(2048)
        assert "KB" in result or "MB" in result  # depends on rounding

    def test_megabytes(self):
        result = _human_bytes(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        result = _human_bytes(2 * 1024 * 1024 * 1024)
        assert "GB" in result


class TestStorageHygieneEngine:
    def setup_method(self):
        self.engine = StorageHygieneEngine()

    def test_estimate_with_real_file(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 1024)  # 1 KB
            db_path = f.name

        est = self.engine.estimate(db_path=db_path, snapshot_count=5, max_snapshot_count=200)
        assert est.db_size_bytes > 0
        assert est.disk_total_bytes > 0
        assert est.snapshot_count == 5
        assert est.max_snapshot_count == 200
        assert est.pressure_level in ("ok", "warning", "critical")
        assert isinstance(est.observations, list)
        assert len(est.observations) > 0

    def test_estimate_missing_file(self):
        est = self.engine.estimate(
            db_path="/tmp/does_not_exist_xyzabc.db",
            snapshot_count=0,
            max_snapshot_count=100,
        )
        assert est.db_size_bytes == 0

    def test_estimate_count_fraction(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        est = self.engine.estimate(db_path=db_path, snapshot_count=160, max_snapshot_count=200)
        assert est.snapshot_count_fraction == pytest.approx(0.8, abs=0.01)

    def test_warning_at_80_percent_count(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        est = self.engine.estimate(db_path=db_path, snapshot_count=180, max_snapshot_count=200)
        assert est.pressure_level in ("warning", "critical")

    def test_critical_at_95_percent_count(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        est = self.engine.estimate(db_path=db_path, snapshot_count=192, max_snapshot_count=200)
        assert est.pressure_level == "critical"

    def test_to_dict_keys(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        est = self.engine.estimate(db_path=db_path, snapshot_count=10, max_snapshot_count=200)
        d = est.to_dict()
        assert "db_size_bytes" in d
        assert "db_size_human" in d
        assert "disk_usage_percent" in d
        assert "pressure_level" in d
        assert "observations" in d
        assert "snapshot_count" in d

    def test_compare_growth(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        earlier = self.engine.estimate(db_path=db_path, snapshot_count=10, max_snapshot_count=200)
        # Simulate growth
        Path(db_path).write_bytes(b"x" * 2000)
        later = self.engine.estimate(db_path=db_path, snapshot_count=20, max_snapshot_count=200)

        growth = self.engine.compare(earlier, later)
        assert growth.db_growth_bytes > 0
        assert growth.snapshot_growth == 10
        assert len(growth.observations) > 0

    def test_compare_no_change(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * 100)
            db_path = f.name

        est1 = self.engine.estimate(db_path=db_path, snapshot_count=10, max_snapshot_count=200)
        est2 = self.engine.estimate(db_path=db_path, snapshot_count=10, max_snapshot_count=200)

        growth = self.engine.compare(est1, est2)
        assert "No significant" in growth.observations[0]
