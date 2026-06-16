"""Tests for schemas/snapshot_schema.py — SnapshotValidator."""

from __future__ import annotations

from schemas.snapshot_schema import SCHEMA_VERSION, SchemaValidationResult, SnapshotValidator


def _snap(include_data=True, include_id=True, include_created_at=True):
    snap = {}
    if include_id:
        snap["id"] = 1
    if include_created_at:
        snap["created_at"] = "2026-01-01T00:00:00"
    if include_data:
        snap["data"] = {
            "recommendations": [],
            "scanner_results": {"results": {}},
        }
    return snap


class TestSnapshotValidatorBasic:
    def test_valid_minimal_snapshot(self):
        result = SnapshotValidator().validate(_snap())
        assert isinstance(result, SchemaValidationResult)
        assert result.valid is True

    def test_missing_id_is_error(self):
        result = SnapshotValidator().validate(_snap(include_id=False))
        codes = {v.code for v in result.violations}
        assert "MISSING_REQUIRED_FIELD" in codes
        assert result.valid is False

    def test_missing_created_at_is_error(self):
        result = SnapshotValidator().validate(_snap(include_created_at=False))
        codes = {v.code for v in result.violations}
        assert "MISSING_REQUIRED_FIELD" in codes

    def test_missing_data_is_error(self):
        result = SnapshotValidator().validate(_snap(include_data=False))
        assert result.valid is False

    def test_missing_recommendations_section_is_error(self):
        snap = _snap()
        del snap["data"]["recommendations"]
        result = SnapshotValidator().validate(snap)
        assert result.valid is False
        codes = {v.code for v in result.violations}
        assert "MISSING_CORE_SECTION" in codes

    def test_missing_scanner_results_is_error(self):
        snap = _snap()
        del snap["data"]["scanner_results"]
        result = SnapshotValidator().validate(snap)
        assert result.valid is False

    def test_wrong_type_recommendations(self):
        snap = _snap()
        snap["data"]["recommendations"] = "not a list"
        result = SnapshotValidator().validate(snap)
        assert result.valid is False
        codes = {v.code for v in result.violations}
        assert "WRONG_TYPE" in codes

    def test_schema_version_returned(self):
        result = SnapshotValidator().validate(_snap())
        assert result.schema_version == SCHEMA_VERSION

    def test_to_dict_structure(self):
        result = SnapshotValidator().validate(_snap())
        d = result.to_dict()
        assert "valid" in d
        assert "violations" in d
        assert "schema_version" in d
        assert "missing_optional_sections" in d


class TestOptionalSections:
    def test_missing_optional_sections_reported(self):
        result = SnapshotValidator().validate(_snap())
        # Should note missing optional sections (runtime_health, workflows, etc.)
        assert len(result.missing_optional_sections) > 0

    def test_full_snapshot_no_missing_optional(self):
        snap = _snap()
        snap["data"].update({
            "cost_observations": [],
            "runtime_health": {},
            "llm_detections": [],
            "topology": {},
            "workflows": [],
            "drift_events": [],
        })
        result = SnapshotValidator().validate(snap)
        assert result.valid is True
        assert len(result.missing_optional_sections) == 0

    def test_wrong_type_optional_section_is_warning(self):
        snap = _snap()
        snap["data"]["runtime_health"] = "not a dict"
        result = SnapshotValidator().validate(snap)
        # Optional section wrong type = warning (not error)
        warn_violations = [v for v in result.violations if v.severity == "warning"]
        assert any("runtime_health" in v.field for v in warn_violations)


class TestTimestampValidation:
    def test_invalid_timestamp_produces_warning(self):
        snap = _snap()
        snap["created_at"] = "not-a-date"
        result = SnapshotValidator().validate(snap)
        codes = {v.code for v in result.violations}
        assert "INVALID_TIMESTAMP" in codes

    def test_valid_z_timestamp(self):
        snap = _snap()
        snap["created_at"] = "2026-01-01T00:00:00Z"
        result = SnapshotValidator().validate(snap)
        assert result.valid is True


class TestNormalize:
    def test_normalize_fills_missing_optional(self):
        snap = _snap()
        normalized = SnapshotValidator().normalize(snap)
        assert "runtime_health" in normalized["data"]
        assert "workflows" in normalized["data"]
        assert "cost_observations" in normalized["data"]

    def test_normalize_does_not_modify_original(self):
        snap = _snap()
        original_keys = set(snap["data"].keys())
        SnapshotValidator().normalize(snap)
        assert set(snap["data"].keys()) == original_keys

    def test_normalize_returns_new_dict(self):
        snap = _snap()
        result = SnapshotValidator().normalize(snap)
        assert result is not snap

    def test_normalize_preserves_existing_data(self):
        snap = _snap()
        snap["data"]["recommendations"] = [{"title": "test"}]
        result = SnapshotValidator().normalize(snap)
        assert result["data"]["recommendations"] == [{"title": "test"}]


class TestBatchValidation:
    def test_validate_batch_returns_list(self):
        snaps = [_snap(), _snap()]
        results = SnapshotValidator().validate_batch(snaps)
        assert len(results) == 2

    def test_batch_summary_structure(self):
        snaps = [_snap(), _snap()]
        results = SnapshotValidator().validate_batch(snaps)
        summary = SnapshotValidator().batch_summary(results)
        assert "total_snapshots" in summary
        assert "valid_snapshots" in summary
        assert "total_errors" in summary
        assert "schema_version" in summary

    def test_batch_summary_counts_correctly(self):
        valid = _snap()
        invalid = _snap(include_id=False)
        results = SnapshotValidator().validate_batch([valid, invalid])
        summary = SnapshotValidator().batch_summary(results)
        assert summary["valid_snapshots"] == 1
        assert summary["invalid_snapshots"] == 1

    def test_add_schema_version(self):
        snap = _snap()
        result = SnapshotValidator().add_schema_version(snap)
        assert result["schema_version"] == SCHEMA_VERSION
        assert "schema_version" not in snap  # original unchanged
