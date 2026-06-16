"""Tests for tools/scaling_boundaries.py."""


from tools.scaling_boundaries import (
    OperatingEnvelope,
    ScalingBoundaryChecker,
    ScalingBoundaryReport,
)


def _check(**kwargs) -> ScalingBoundaryReport:
    checker = ScalingBoundaryChecker()
    defaults = {
        "snapshot_count": 100,
        "llm_event_count": 500,
        "db_size_bytes": 10 * 1024 * 1024,  # 10 MB
        "avg_query_latency_ms": None,
        "avg_report_latency_ms": None,
        "writes_per_hour_estimate": None,
        "avg_recs_per_snapshot": None,
    }
    defaults.update(kwargs)
    return checker.check(**defaults)


class TestComfortableState:
    def test_all_within_bounds(self):
        report = _check()
        assert report.overall_status == "ok"
        assert report.scaling_outlook == "comfortable"
        assert report.passed == len(report.checks)

    def test_check_count(self):
        report = _check()
        assert len(report.checks) == 7

    def test_to_dict_complete(self):
        report = _check()
        d = report.to_dict()
        assert "overall_status" in d
        assert "scaling_outlook" in d
        assert "checks" in d
        assert "operating_envelope" in d
        assert "observations" in d
        assert "advisory" in d


class TestSnapshotBoundary:
    def test_ok_below_warn(self):
        report = _check(snapshot_count=4999)
        snap = next(c for c in report.checks if "Snapshot" in c.name)
        assert snap.severity == "ok"

    def test_warn_at_threshold(self):
        report = _check(snapshot_count=5000)
        snap = next(c for c in report.checks if "Snapshot" in c.name)
        assert snap.severity == "warning"

    def test_critical_above_threshold(self):
        report = _check(snapshot_count=20001)
        snap = next(c for c in report.checks if "Snapshot" in c.name)
        assert snap.severity == "critical"

    def test_critical_sets_overall_critical(self):
        report = _check(snapshot_count=25000)
        assert report.overall_status == "critical"
        assert report.scaling_outlook == "at_limits"


class TestEventVolumeBoundary:
    def test_ok_below_warn(self):
        report = _check(llm_event_count=49999)
        ev = next(c for c in report.checks if "Event" in c.name)
        assert ev.severity == "ok"

    def test_warn_at_threshold(self):
        report = _check(llm_event_count=50000)
        ev = next(c for c in report.checks if "Event" in c.name)
        assert ev.severity == "warning"

    def test_critical_at_threshold(self):
        report = _check(llm_event_count=200000)
        ev = next(c for c in report.checks if "Event" in c.name)
        assert ev.severity == "critical"


class TestDbSizeBoundary:
    def test_ok_below_warn(self):
        report = _check(db_size_bytes=100 * 1024 * 1024)  # 100 MB
        db = next(c for c in report.checks if "Database File" in c.name)
        assert db.severity == "ok"

    def test_warn_at_200mb(self):
        report = _check(db_size_bytes=200 * 1024 * 1024)
        db = next(c for c in report.checks if "Database File" in c.name)
        assert db.severity == "warning"

    def test_critical_at_1gb(self):
        report = _check(db_size_bytes=1024 * 1024 * 1024)
        db = next(c for c in report.checks if "Database File" in c.name)
        assert db.severity == "critical"


class TestQueryLatency:
    def test_none_produces_ok_with_estimate(self):
        report = _check(avg_query_latency_ms=None, snapshot_count=100)
        lat = next(c for c in report.checks if "Query Latency" in c.name)
        assert lat.severity == "ok"

    def test_measured_ok(self):
        report = _check(avg_query_latency_ms=500.0)  # 0.5s
        lat = next(c for c in report.checks if "Query Latency" in c.name)
        assert lat.severity == "ok"

    def test_measured_warn(self):
        report = _check(avg_query_latency_ms=3000.0)  # 3s
        lat = next(c for c in report.checks if "Query Latency" in c.name)
        assert lat.severity == "warning"

    def test_measured_critical(self):
        report = _check(avg_query_latency_ms=10000.0)  # 10s
        lat = next(c for c in report.checks if "Query Latency" in c.name)
        assert lat.severity == "critical"

    def test_note_measured_vs_estimated(self):
        report_measured = _check(avg_query_latency_ms=500.0)
        report_estimated = _check(avg_query_latency_ms=None, snapshot_count=100)
        lat_m = next(c for c in report_measured.checks if "Query Latency" in c.name)
        lat_e = next(c for c in report_estimated.checks if "Query Latency" in c.name)
        assert "(measured)" in lat_m.unit
        assert "(estimated" in lat_e.unit


class TestReportLatency:
    def test_none_produces_estimate(self):
        report = _check(avg_report_latency_ms=None, snapshot_count=100)
        rep_lat = next(c for c in report.checks if "Report Generation" in c.name)
        assert rep_lat.severity == "ok"

    def test_warn_at_15s(self):
        report = _check(avg_report_latency_ms=16000.0)
        rep_lat = next(c for c in report.checks if "Report Generation" in c.name)
        assert rep_lat.severity == "warning"

    def test_critical_at_45s(self):
        report = _check(avg_report_latency_ms=50000.0)
        rep_lat = next(c for c in report.checks if "Report Generation" in c.name)
        assert rep_lat.severity == "critical"


class TestWritePressure:
    def test_none_returns_ok_with_note(self):
        report = _check(writes_per_hour_estimate=None)
        wp = next(c for c in report.checks if "Write Pressure" in c.name)
        assert wp.severity == "ok"
        assert wp.recommendations

    def test_ok_below_warn(self):
        report = _check(writes_per_hour_estimate=4000)
        wp = next(c for c in report.checks if "Write Pressure" in c.name)
        assert wp.severity == "ok"

    def test_warn_at_threshold(self):
        report = _check(writes_per_hour_estimate=5000)
        wp = next(c for c in report.checks if "Write Pressure" in c.name)
        assert wp.severity == "warning"

    def test_critical_at_threshold(self):
        report = _check(writes_per_hour_estimate=36001)
        wp = next(c for c in report.checks if "Write Pressure" in c.name)
        assert wp.severity == "critical"


class TestCognitionVolume:
    def test_none_returns_ok(self):
        report = _check(avg_recs_per_snapshot=None)
        cog = next(c for c in report.checks if "Cognition" in c.name)
        assert cog.severity == "ok"

    def test_ok_below_warn(self):
        report = _check(avg_recs_per_snapshot=100.0)
        cog = next(c for c in report.checks if "Cognition" in c.name)
        assert cog.severity == "ok"

    def test_warn_at_threshold(self):
        report = _check(avg_recs_per_snapshot=150.0)
        cog = next(c for c in report.checks if "Cognition" in c.name)
        assert cog.severity == "warning"

    def test_critical_at_threshold(self):
        report = _check(avg_recs_per_snapshot=401.0)
        cog = next(c for c in report.checks if "Cognition" in c.name)
        assert cog.severity == "critical"


class TestOperatingEnvelope:
    def test_envelope_present(self):
        report = _check()
        assert isinstance(report.operating_envelope, OperatingEnvelope)

    def test_envelope_values_positive(self):
        env = _check().operating_envelope
        assert env.snapshot_comfortable_max > 0
        assert env.event_comfortable_max > 0
        assert env.db_size_comfortable_max_mb > 0
        assert env.writes_per_hour_comfortable_max > 0
        assert env.recs_per_snapshot_comfortable_max > 0

    def test_envelope_notes_present(self):
        env = _check().operating_envelope
        assert len(env.notes) > 0


class TestScalingOutlook:
    def test_comfortable_when_all_ok(self):
        assert _check().scaling_outlook == "comfortable"

    def test_approaching_on_warning(self):
        report = _check(snapshot_count=6000)
        assert report.scaling_outlook == "approaching_limits"

    def test_at_limits_on_critical(self):
        report = _check(snapshot_count=25000)
        assert report.scaling_outlook == "at_limits"


class TestMarkdown:
    def test_markdown_has_required_sections(self):
        md = _check().markdown()
        assert "# Scaling Boundary Report" in md
        assert "## Boundary Checks" in md
        assert "## Recommended Operating Envelope" in md

    def test_markdown_has_advisory(self):
        md = _check().markdown()
        assert "Advisory only" in md
