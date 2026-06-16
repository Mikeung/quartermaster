"""
Project Namespace Schema — lightweight project isolation model.

A Project is a named namespace that scopes snapshots, LLM events, and
cognition outputs. Projects prevent operational cross-contamination when
multiple AI ecosystems are tracked on a single VPS.

Design rules:
- project_id is a slug: lowercase, alphanumeric + dashes, 3–64 chars
- No RBAC, no auth, no tenant complexity
- SQLite-friendly: all fields are scalars or short JSON strings
- Backward compatible: all existing data has project_id = NULL (unscoped)
- Archival is soft — archived projects are queryable but excluded from
  active analysis by default
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0"

_PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")
_MAX_NAME_LENGTH = 128
_MAX_DESCRIPTION_LENGTH = 512
_MAX_TAG_LENGTH = 64
_MAX_TAGS = 20
_MAX_METADATA_KEYS = 10
_MAX_METADATA_VALUE_LENGTH = 256

_VALID_RETENTION_PROFILES = frozenset({"minimal", "standard", "extended"})
_VALID_DEPLOYMENT_PROFILES = frozenset({"minimal", "standard", "extended"})


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """
    Operational project namespace.

    project_id is the primary key and namespace boundary.
    All other fields are metadata for operator ergonomics.
    """

    project_id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    retention_profile: str = "standard"
    deployment_profile: str = "standard"
    ingestion_enabled: bool = True
    archived: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "created_at": self.created_at,
            "retention_profile": self.retention_profile,
            "deployment_profile": self.deployment_profile,
            "ingestion_enabled": self.ingestion_enabled,
            "archived": self.archived,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        return cls(
            project_id=str(data.get("project_id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            tags=_coerce_tags(data.get("tags", [])),
            created_at=str(data.get("created_at", datetime.now(UTC).isoformat())),
            retention_profile=str(data.get("retention_profile", "standard")),
            deployment_profile=str(data.get("deployment_profile", "standard")),
            ingestion_enabled=bool(data.get("ingestion_enabled", True)),
            archived=bool(data.get("archived", False)),
            metadata=_coerce_metadata(data.get("metadata", {})),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )

    def is_active(self) -> bool:
        return not self.archived and self.ingestion_enabled


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ProjectValidationResult:
    valid: bool
    violations: list[str] = field(default_factory=list)
    normalized: Project | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "violations": self.violations,
        }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ProjectValidator:
    """
    Validates and normalizes project namespace payloads.

    project_id is normalized to a slug. name is stripped and truncated.
    """

    def validate(self, data: dict[str, Any]) -> ProjectValidationResult:
        violations: list[str] = []

        violations.extend(_check_project_id(data.get("project_id", "")))
        violations.extend(_check_name(data.get("name", "")))
        violations.extend(_check_description(data.get("description", "")))
        violations.extend(_check_tags(data.get("tags", [])))
        violations.extend(_check_profiles(data))
        violations.extend(_check_metadata_bounds(data.get("metadata", {})))

        if violations:
            return ProjectValidationResult(valid=False, violations=violations)

        normalized = _normalize(data)
        return ProjectValidationResult(valid=True, violations=[], normalized=normalized)

    def validate_and_raise(self, data: dict[str, Any]) -> Project:
        result = self.validate(data)
        if not result.valid:
            raise ValueError(f"Project validation failed: {result.violations}")
        assert result.normalized is not None
        return result.normalized


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _check_project_id(raw: Any) -> list[str]:
    if not raw:
        return ["project_id is required"]
    s = str(raw).strip().lower()
    if len(s) < 3:
        return [f"project_id '{s}' is too short (min 3 chars)"]
    if len(s) > 64:
        return ["project_id is too long (max 64 chars)"]
    if not _PROJECT_ID_PATTERN.match(s):
        return [
            f"project_id '{s}' is invalid. "
            "Use lowercase alphanumeric chars and dashes only. "
            "Must start and end with alphanumeric char."
        ]
    return []


def _check_name(raw: Any) -> list[str]:
    if not raw:
        return ["name is required"]
    if len(str(raw).strip()) > _MAX_NAME_LENGTH:
        return [f"name exceeds max length {_MAX_NAME_LENGTH}"]
    return []


def _check_description(raw: Any) -> list[str]:
    if raw and len(str(raw)) > _MAX_DESCRIPTION_LENGTH:
        return [f"description exceeds max length {_MAX_DESCRIPTION_LENGTH}"]
    return []


def _check_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["tags must be a list"]
    if len(raw) > _MAX_TAGS:
        return [f"tags list has {len(raw)} entries — max is {_MAX_TAGS}"]
    for t in raw:
        if not isinstance(t, str):
            return [f"tag '{t}' must be a string"]
        if len(t) > _MAX_TAG_LENGTH:
            return [f"tag '{t}' exceeds max length {_MAX_TAG_LENGTH}"]
    return []


def _check_profiles(data: dict[str, Any]) -> list[str]:
    violations = []
    rp = str(data.get("retention_profile", "standard"))
    dp = str(data.get("deployment_profile", "standard"))
    if rp not in _VALID_RETENTION_PROFILES:
        violations.append(
            f"retention_profile '{rp}' is invalid. "
            f"Valid: {sorted(_VALID_RETENTION_PROFILES)}"
        )
    if dp not in _VALID_DEPLOYMENT_PROFILES:
        violations.append(
            f"deployment_profile '{dp}' is invalid. "
            f"Valid: {sorted(_VALID_DEPLOYMENT_PROFILES)}"
        )
    return violations


def _check_metadata_bounds(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return ["metadata must be a dict"]
    if len(metadata) > _MAX_METADATA_KEYS:
        return [f"metadata has {len(metadata)} keys — max is {_MAX_METADATA_KEYS}"]
    for k, v in metadata.items():
        if not isinstance(k, str) or not isinstance(v, str):
            return ["metadata keys and values must be strings"]
        if len(v) > _MAX_METADATA_VALUE_LENGTH:
            return [f"metadata value for '{k}' exceeds {_MAX_METADATA_VALUE_LENGTH} chars"]
    return []


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(data: dict[str, Any]) -> Project:
    project_id = re.sub(r"[^a-z0-9\-]", "-", str(data["project_id"]).strip().lower())
    project_id = re.sub(r"-+", "-", project_id).strip("-")

    return Project(
        project_id=project_id,
        name=str(data.get("name", "")).strip()[:_MAX_NAME_LENGTH],
        description=str(data.get("description", "")).strip()[:_MAX_DESCRIPTION_LENGTH],
        tags=_coerce_tags(data.get("tags", [])),
        created_at=str(data.get("created_at", datetime.now(UTC).isoformat())),
        retention_profile=str(data.get("retention_profile", "standard")),
        deployment_profile=str(data.get("deployment_profile", "standard")),
        ingestion_enabled=bool(data.get("ingestion_enabled", True)),
        archived=bool(data.get("archived", False)),
        metadata=_coerce_metadata(data.get("metadata", {})),
        schema_version=SCHEMA_VERSION,
    )


def _coerce_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    result = []
    for t in raw:
        if isinstance(t, str):
            result.append(t.strip()[:_MAX_TAG_LENGTH])
    return result[:_MAX_TAGS]


def _coerce_metadata(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    result = {}
    for k, v in list(raw.items())[:_MAX_METADATA_KEYS]:
        if isinstance(k, str) and isinstance(v, str):
            result[k] = v[:_MAX_METADATA_VALUE_LENGTH]
    return result


def normalize_project_id(raw: str) -> str:
    """Normalize a raw string to a valid project_id slug."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9\-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "default"
