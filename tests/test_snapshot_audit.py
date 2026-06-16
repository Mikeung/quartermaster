"""Tests for tools/snapshot_audit.py — SnapshotAuditor."""

from __future__ import annotations

from tools.snapshot_audit import AuditFinding, AuditReport, SnapshotAuditor


def _snap(snap_id=1, created_at="2026-01-01T00:00:00", recs=None, include_scanner=True):
    data: dict = {}
    if recs is not None:
        data["recommendations"] = recs
    else:
        data["recommendations"] = []
    if include_scanner:
        data["scanner_results"] = {"results": {}}
    return {"id": snap_id, "created_at": created_at, "data": data}


def _rec(title="test rec", category="cost", impact="high", confidence=0.8, evidence=None):
    return {
        "title": title,
        "category": category,
        "impact": impact,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else ["signal"],
    }


class TestSnapshotAuditorBasic:
    def test_empty_snapshots_returns_report(self):
        report = SnapshotAuditor().audit([])
        assert isinstance(report, AuditReport)
        assert report.total_snapshots == 0

    def test_clean_snapshot_no_findings(self):
        report = SnapshotAuditor().audit([_snap()])
        assert report.error_count == 0

    def test_total_snapshots_counted(self):
        snaps = [_snap(1), _snap(2), _snap(3)]
        report = SnapshotAuditor().audit(snaps)
        assert report.total_snapshots == 3

    def test_clean_snapshots_counted(self):
        snaps = [_snap(1), _snap(2)]
        report = SnapshotAuditor().audit(snaps)
        assert report.clean_snapshots == 2

    def test_to_dict_structure(self):
        report = SnapshotAuditor().audit([_snap()])
        d = report.to_dict()
        assert "total_snapshots" in d
        assert "clean_snapshots" in d
        assert "findings" in d
        assert "error_count" in d
        assert "warning_count" in d
        assert "audited_at" in d

    def test_markdown_returns_string(self):
        report = SnapshotAuditor().audit([_snap()])
        md = report.markdown()
        assert isinstance(md, str)
        assert "Snapshot Audit" in md

    def test_markdown_advisory_footer(self):
        report = SnapshotAuditor().audit([])
        md = report.markdown()
        assert "Advisory" in md or "advisory" in md


class TestAuditFinding:
    def test_to_dict(self):
        f = AuditFinding(
            snapshot_id=1, category="schema", message="test",
            severity="warning", field="data.recommendations"
        )
        d = f.to_dict()
        assert "snapshot_id" in d
        assert "category" in d
        assert "message" in d
        assert "severity" in d
        assert "field" in d


class TestSchemaChecks:
    def test_missing_id_produces_finding(self):
        snap = {"created_at": "2026-01-01T00:00:00", "data": {"recommendations": [], "scanner_results": {}}}
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "schema" for f in findings)

    def test_missing_created_at_produces_finding(self):
        snap = {"id": 1, "data": {"recommendations": [], "scanner_results": {}}}
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "schema" for f in findings)

    def test_missing_data_produces_finding(self):
        snap = {"id": 1, "created_at": "2026-01-01T00:00:00"}
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "schema" for f in findings)

    def test_missing_scanner_results_produces_finding(self):
        snap = _snap(include_scanner=False)
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "schema" for f in findings)

    def test_recommendations_wrong_type_produces_finding(self):
        snap = _snap()
        snap["data"]["recommendations"] = "not a list"
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "schema" for f in findings)


class TestEvidenceChainChecks:
    def test_empty_evidence_produces_warning(self):
        rec = _rec(evidence=[])
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "evidence" for f in findings)

    def test_non_empty_evidence_no_warning(self):
        rec = _rec(evidence=["signal A"])
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        evidence_findings = [f for f in findings if f.category == "evidence"]
        assert len(evidence_findings) == 0


class TestConfidenceRangeChecks:
    def test_confidence_too_high_produces_finding(self):
        rec = _rec(confidence=1.5)
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "confidence" for f in findings)

    def test_confidence_negative_produces_finding(self):
        rec = _rec(confidence=-0.1)
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "confidence" for f in findings)

    def test_valid_confidence_no_finding(self):
        rec = _rec(confidence=0.8)
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        confidence_findings = [f for f in findings if f.category == "confidence"]
        assert len(confidence_findings) == 0


class TestOrphanedRecChecks:
    def test_missing_title_produces_error(self):
        rec = {"category": "cost", "impact": "high", "confidence": 0.8, "evidence": ["x"]}
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "orphan" and f.severity == "error" for f in findings)

    def test_missing_category_produces_warning(self):
        rec = {"title": "test", "impact": "high", "confidence": 0.8, "evidence": ["x"]}
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "orphan" for f in findings)

    def test_complete_rec_no_orphan_finding(self):
        rec = _rec()
        snap = _snap(recs=[rec])
        findings = SnapshotAuditor().audit_single(snap)
        orphan_findings = [f for f in findings if f.category == "orphan"]
        assert len(orphan_findings) == 0


class TestVolumeChecks:
    def test_empty_recommendations_produces_info(self):
        snap = _snap(recs=[])
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "volume" for f in findings)

    def test_normal_volume_no_info(self):
        recs = [_rec(f"rec {i}") for i in range(5)]
        snap = _snap(recs=recs)
        findings = SnapshotAuditor().audit_single(snap)
        volume_findings = [f for f in findings if f.category == "volume" and f.severity != "info"]
        assert len(volume_findings) == 0


class TestTimestampChecks:
    def test_out_of_order_timestamps_produce_warning(self):
        snaps = [
            _snap(1, "2026-01-08T00:00:00"),
            _snap(2, "2026-01-01T00:00:00"),  # older than first — wrong order
        ]
        report = SnapshotAuditor().audit(snaps)
        timestamp_findings = [f for f in report.findings if f.category == "timestamp"]
        assert len(timestamp_findings) > 0

    def test_valid_order_no_timestamp_warning(self):
        snaps = [
            _snap(1, "2026-01-01T00:00:00"),
            _snap(2, "2026-01-08T00:00:00"),
        ]
        report = SnapshotAuditor().audit(snaps)
        timestamp_findings = [f for f in report.findings if f.category == "timestamp"]
        assert len(timestamp_findings) == 0

    def test_invalid_timestamp_format_produces_finding(self):
        snap = {"id": 1, "created_at": "not-a-date", "data": {"recommendations": [], "scanner_results": {}}}
        findings = SnapshotAuditor().audit_single(snap)
        assert any(f.category == "timestamp" for f in findings)


class TestFindingSeverityCounts:
    def test_error_count_correct(self):
        snap = {"id": 1, "data": {"recommendations": [], "scanner_results": {}}}  # missing created_at
        report = SnapshotAuditor().audit([snap])
        computed_errors = sum(1 for f in report.findings if f.severity == "error")
        assert report.error_count == computed_errors

    def test_warning_count_correct(self):
        snap = _snap(recs=[_rec(evidence=[])])  # empty evidence = warning
        report = SnapshotAuditor().audit([snap])
        computed_warnings = sum(1 for f in report.findings if f.severity == "warning")
        assert report.warning_count == computed_warnings
