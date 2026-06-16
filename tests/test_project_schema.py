"""Tests for schemas/project_schema.py — project namespace schema."""

from __future__ import annotations

import pytest

from schemas.project_schema import (
    SCHEMA_VERSION,
    Project,
    ProjectValidator,
    normalize_project_id,
)


def _valid_payload(**overrides) -> dict:
    base = {
        "project_id": "my-llm-app",
        "name": "My LLM Application",
        "description": "Production RAG pipeline",
        "tags": ["production", "rag"],
        "retention_profile": "standard",
        "deployment_profile": "standard",
        "ingestion_enabled": True,
        "archived": False,
    }
    base.update(overrides)
    return base


class TestProjectValidator:
    def test_valid_payload_passes(self):
        v = ProjectValidator()
        result = v.validate(_valid_payload())
        assert result.valid
        assert result.violations == []
        assert result.normalized is not None

    def test_missing_project_id_rejected(self):
        v = ProjectValidator()
        payload = _valid_payload()
        del payload["project_id"]
        result = v.validate(payload)
        assert not result.valid
        assert any("project_id" in viol for viol in result.violations)

    def test_missing_name_rejected(self):
        v = ProjectValidator()
        payload = _valid_payload()
        del payload["name"]
        result = v.validate(payload)
        assert not result.valid

    def test_project_id_too_short_rejected(self):
        result = ProjectValidator().validate(_valid_payload(project_id="ab"))
        assert not result.valid

    def test_project_id_invalid_chars_rejected(self):
        result = ProjectValidator().validate(_valid_payload(project_id="My App!"))
        assert not result.valid

    def test_project_id_starts_with_dash_rejected(self):
        result = ProjectValidator().validate(_valid_payload(project_id="-my-app"))
        assert not result.valid

    def test_project_id_ends_with_dash_rejected(self):
        result = ProjectValidator().validate(_valid_payload(project_id="my-app-"))
        assert not result.valid

    def test_valid_project_id_with_dashes(self):
        result = ProjectValidator().validate(_valid_payload(project_id="my-llm-app-v2"))
        assert result.valid

    def test_invalid_retention_profile_rejected(self):
        result = ProjectValidator().validate(_valid_payload(retention_profile="enterprise"))
        assert not result.valid

    def test_invalid_deployment_profile_rejected(self):
        result = ProjectValidator().validate(_valid_payload(deployment_profile="cloud"))
        assert not result.valid

    def test_too_many_tags_rejected(self):
        tags = [f"tag{i}" for i in range(25)]
        result = ProjectValidator().validate(_valid_payload(tags=tags))
        assert not result.valid

    def test_valid_profiles_accepted(self):
        v = ProjectValidator()
        for profile in ("minimal", "standard", "extended"):
            result = v.validate(_valid_payload(retention_profile=profile, deployment_profile=profile))
            assert result.valid, f"Profile '{profile}' should be valid"

    def test_metadata_bounds_enforced(self):
        meta = {f"k{i}": "v" for i in range(15)}
        result = ProjectValidator().validate(_valid_payload(metadata=meta))
        assert not result.valid

    def test_normalize_lowercases_project_id(self):
        v = ProjectValidator()
        result = v.validate(_valid_payload(project_id="my-llm-app"))
        assert result.valid
        assert result.normalized.project_id == "my-llm-app"

    def test_validate_and_raise_on_invalid(self):
        v = ProjectValidator()
        with pytest.raises(ValueError, match="validation failed"):
            v.validate_and_raise(_valid_payload(project_id="X"))

    def test_validate_and_raise_returns_project_on_valid(self):
        v = ProjectValidator()
        project = v.validate_and_raise(_valid_payload())
        assert isinstance(project, Project)
        assert project.project_id == "my-llm-app"

    def test_schema_version_embedded(self):
        v = ProjectValidator()
        result = v.validate(_valid_payload())
        assert result.normalized.schema_version == SCHEMA_VERSION


class TestProject:
    def test_is_active_when_not_archived(self):
        p = Project(project_id="test-app", name="Test", ingestion_enabled=True, archived=False)
        assert p.is_active()

    def test_not_active_when_archived(self):
        p = Project(project_id="test-app", name="Test", archived=True)
        assert not p.is_active()

    def test_not_active_when_ingestion_disabled(self):
        p = Project(project_id="test-app", name="Test", ingestion_enabled=False)
        assert not p.is_active()

    def test_to_dict_round_trip(self):
        p = Project(
            project_id="my-app",
            name="My App",
            description="test",
            tags=["a", "b"],
            metadata={"env": "prod"},
        )
        d = p.to_dict()
        assert d["project_id"] == "my-app"
        assert d["tags"] == ["a", "b"]
        assert d["metadata"]["env"] == "prod"

    def test_from_dict_round_trip(self):
        payload = _valid_payload()
        project = Project.from_dict(payload)
        assert project.project_id == "my-llm-app"
        assert project.name == "My LLM Application"
        assert project.tags == ["production", "rag"]


class TestNormalizeProjectId:
    def test_lowercases(self):
        assert normalize_project_id("MyApp") == "myapp"

    def test_spaces_to_dashes(self):
        assert normalize_project_id("my app") == "my-app"

    def test_strips_leading_trailing_dashes(self):
        result = normalize_project_id("  -my-app-  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_returns_default(self):
        assert normalize_project_id("") == "default"
        assert normalize_project_id("   ") == "default"
