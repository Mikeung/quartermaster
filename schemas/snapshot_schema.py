"""
Snapshot schema stabilization — canonical schema definition, validation, normalization.

Purpose:
- Define what a valid snapshot looks like across all schema versions.
- Detect missing or malformed sections before cognition layers consume them.
- Normalize snapshots to fill missing optional fields with safe defaults.
- Support backward compatibility as new sections are added in later phases.

IMPORTANT:
- Schema validation is read-only. It never modifies stored snapshots.
- normalize() returns a NEW dict — originals are unchanged.
- Compatibility warnings are surfaced to callers, not silently suppressed.
- Schema version is tracked for audit and migration tooling.

Advisory only. Deterministic. Read-safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

# Required top-level fields
_REQUIRED_TOP_LEVEL: frozenset[str] = frozenset({"id", "created_at", "data"})

# Required sections inside snapshot["data"] — always expected
_CORE_SECTIONS: frozenset[str] = frozenset({"recommendations", "scanner_results"})

# Optional sections added in later phases — may be absent in older snapshots
_OPTIONAL_SECTIONS: frozenset[str] = frozenset({
    "cost_observations",
    "runtime_health",
    "llm_detections",
    "topology",
    "workflows",
    "drift_events",
})

# All known data sections
_ALL_SECTIONS: frozenset[str] = _CORE_SECTIONS | _OPTIONAL_SECTIONS

# Expected type for each section
_SECTION_TYPES: dict[str, type] = {
    "recommendations": list,
    "cost_observations": list,
    "runtime_health": dict,
    "llm_detections": list,
    "scanner_results": dict,
    "topology": dict,
    "workflows": list,
    "drift_events": list,
}

# Safe defaults for missing sections
_SECTION_DEFAULTS: dict[str, Any] = {
    "recommendations": [],
    "cost_observations": [],
    "runtime_health": {},
    "llm_detections": [],
    "scanner_results": {"results": {}},
    "topology": {},
    "workflows": [],
    "drift_events": [],
}


@dataclass
class SchemaViolation:
    """A single schema violation found during validation."""
    field: str
    message: str
    severity: str  # "error" | "warning" | "info"
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
            "code": self.code,
        }


@dataclass
class SchemaValidationResult:
    """Result of validating one snapshot against the canonical schema."""
    valid: bool
    snapshot_id: int | None
    schema_version: str
    violations: list[SchemaViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    compatibility_notes: list[str] = field(default_factory=list)
    missing_optional_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "snapshot_id": self.snapshot_id,
            "schema_version": self.schema_version,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "compatibility_notes": self.compatibility_notes,
            "missing_optional_sections": self.missing_optional_sections,
        }


class SnapshotValidator:
    """
    Validates and normalizes snapshots against the canonical schema.

    validate() — checks structure and types, returns violations without modifying.
    normalize() — returns a new dict with missing optional sections filled in.
    """

    def validate(self, snapshot: dict[str, Any]) -> SchemaValidationResult:
        """Validate one snapshot. Returns result with violations list."""
        snap_id = snapshot.get("id")
        violations: list[SchemaViolation] = []
        warnings: list[str] = []
        compat_notes: list[str] = []
        missing_optional: list[str] = []

        # Check required top-level fields
        for f in _REQUIRED_TOP_LEVEL:
            if f not in snapshot:
                violations.append(SchemaViolation(
                    field=f,
                    message=f"Required field '{f}' is missing",
                    severity="error",
                    code="MISSING_REQUIRED_FIELD",
                ))

        data = snapshot.get("data")
        if data is None:
            # Can't check sections without data
            return SchemaValidationResult(
                valid=False,
                snapshot_id=snap_id,
                schema_version=SCHEMA_VERSION,
                violations=violations,
                warnings=warnings,
                compatibility_notes=compat_notes,
                missing_optional_sections=missing_optional,
            )

        if not isinstance(data, dict):
            violations.append(SchemaViolation(
                field="data",
                message="'data' must be a dict",
                severity="error",
                code="WRONG_TYPE",
            ))
            return SchemaValidationResult(
                valid=False,
                snapshot_id=snap_id,
                schema_version=SCHEMA_VERSION,
                violations=violations,
                warnings=warnings,
                compatibility_notes=compat_notes,
                missing_optional_sections=missing_optional,
            )

        # Check core sections
        for section in _CORE_SECTIONS:
            if section not in data:
                violations.append(SchemaViolation(
                    field=f"data.{section}",
                    message=f"Core section '{section}' is missing",
                    severity="error",
                    code="MISSING_CORE_SECTION",
                ))
            elif not isinstance(data[section], _SECTION_TYPES[section]):
                expected = _SECTION_TYPES[section].__name__
                actual = type(data[section]).__name__
                violations.append(SchemaViolation(
                    field=f"data.{section}",
                    message=f"Section '{section}' must be {expected}, got {actual}",
                    severity="error",
                    code="WRONG_TYPE",
                ))

        # Check optional sections
        for section in _OPTIONAL_SECTIONS:
            if section not in data:
                missing_optional.append(section)
                compat_notes.append(
                    f"Optional section '{section}' absent — may be an older snapshot; "
                    f"normalize() will fill with default."
                )
            elif not isinstance(data[section], _SECTION_TYPES[section]):
                expected = _SECTION_TYPES[section].__name__
                actual = type(data[section]).__name__
                violations.append(SchemaViolation(
                    field=f"data.{section}",
                    message=f"Section '{section}' must be {expected}, got {actual}",
                    severity="warning",
                    code="WRONG_TYPE",
                ))

        # Check created_at parseability
        created_at = snapshot.get("created_at", "")
        if created_at:
            try:
                datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                violations.append(SchemaViolation(
                    field="created_at",
                    message=f"created_at is not a valid ISO datetime: {created_at!r}",
                    severity="warning",
                    code="INVALID_TIMESTAMP",
                ))

        # Schema version check
        stored_version = snapshot.get("schema_version")
        if stored_version and stored_version != SCHEMA_VERSION:
            warnings.append(
                f"Snapshot schema_version '{stored_version}' differs from current '{SCHEMA_VERSION}'."
            )

        errors = [v for v in violations if v.severity == "error"]
        return SchemaValidationResult(
            valid=len(errors) == 0,
            snapshot_id=snap_id,
            schema_version=SCHEMA_VERSION,
            violations=violations,
            warnings=warnings,
            compatibility_notes=compat_notes,
            missing_optional_sections=missing_optional,
        )

    def normalize(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """
        Return a new snapshot dict with missing optional sections filled with safe defaults.

        Does NOT modify the input snapshot.
        Does NOT add schema_version to stored data — that is handled separately.
        """
        import copy
        result = copy.deepcopy(snapshot)
        data = result.setdefault("data", {})
        for section, default in _SECTION_DEFAULTS.items():
            if section not in data:
                import copy as _copy
                data[section] = _copy.deepcopy(default)
        return result

    def add_schema_version(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Return a new snapshot dict with schema_version field set."""
        import copy
        result = copy.deepcopy(snapshot)
        result["schema_version"] = SCHEMA_VERSION
        return result

    def validate_batch(
        self, snapshots: list[dict[str, Any]]
    ) -> list[SchemaValidationResult]:
        """Validate a list of snapshots. Returns one result per snapshot."""
        return [self.validate(s) for s in snapshots]

    def batch_summary(
        self, results: list[SchemaValidationResult]
    ) -> dict[str, Any]:
        """Summarize batch validation results."""
        total = len(results)
        valid = sum(1 for r in results if r.valid)
        error_count = sum(
            sum(1 for v in r.violations if v.severity == "error") for r in results
        )
        warning_count = sum(
            sum(1 for v in r.violations if v.severity == "warning") for r in results
        )
        return {
            "total_snapshots": total,
            "valid_snapshots": valid,
            "invalid_snapshots": total - valid,
            "total_errors": error_count,
            "total_warnings": warning_count,
            "schema_version": SCHEMA_VERSION,
            "validated_at": datetime.now(UTC).isoformat(),
        }
