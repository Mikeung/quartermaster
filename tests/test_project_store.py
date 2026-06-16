"""Tests for memory/project_store.py — project namespace store."""

from __future__ import annotations

import pytest

from memory.project_store import ProjectStore
from schemas.project_schema import Project


def _make_project(**overrides) -> Project:
    base = Project(
        project_id="test-project",
        name="Test Project",
        description="A test project",
        tags=["test"],
        retention_profile="standard",
        deployment_profile="standard",
        ingestion_enabled=True,
        archived=False,
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


class TestCreateProject:
    def test_create_returns_true(self, store):
        project = _make_project()
        assert store.create_project(project) is True

    def test_duplicate_create_returns_false(self, store):
        project = _make_project()
        store.create_project(project)
        assert store.create_project(project) is False

    def test_created_project_is_retrievable(self, store):
        project = _make_project()
        store.create_project(project)
        retrieved = store.get_project("test-project")
        assert retrieved is not None
        assert retrieved.project_id == "test-project"
        assert retrieved.name == "Test Project"

    def test_tags_persisted(self, store):
        project = _make_project(tags=["prod", "rag"])
        store.create_project(project)
        retrieved = store.get_project("test-project")
        assert retrieved.tags == ["prod", "rag"]

    def test_metadata_persisted(self, store):
        project = _make_project()
        project.metadata["env"] = "production"
        store.create_project(project)
        retrieved = store.get_project("test-project")
        assert retrieved.metadata.get("env") == "production"


class TestGetProject:
    def test_get_nonexistent_returns_none(self, store):
        assert store.get_project("does-not-exist") is None

    def test_get_returns_correct_project(self, store):
        store.create_project(_make_project(project_id="proj-a", name="A"))
        store.create_project(_make_project(project_id="proj-b", name="B"))
        result = store.get_project("proj-a")
        assert result.name == "A"


class TestListProjects:
    def test_list_empty_store(self, store):
        assert store.list_projects() == []

    def test_list_returns_all_active(self, store):
        store.create_project(_make_project(project_id="p1", name="P1"))
        store.create_project(_make_project(project_id="p2", name="P2"))
        projects = store.list_projects()
        assert len(projects) == 2

    def test_archived_excluded_by_default(self, store):
        store.create_project(_make_project(project_id="active", name="Active"))
        store.create_project(_make_project(project_id="archived", name="Archived", archived=True))
        projects = store.list_projects(include_archived=False)
        assert len(projects) == 1
        assert projects[0].project_id == "active"

    def test_archived_included_when_requested(self, store):
        store.create_project(_make_project(project_id="active", name="Active"))
        store.create_project(_make_project(project_id="archived", name="Archived", archived=True))
        projects = store.list_projects(include_archived=True)
        assert len(projects) == 2


class TestUpdateProject:
    def test_update_name(self, store):
        store.create_project(_make_project())
        store.update_project("test-project", {"name": "Updated Name"})
        retrieved = store.get_project("test-project")
        assert retrieved.name == "Updated Name"

    def test_update_nonexistent_returns_false(self, store):
        result = store.update_project("nope", {"name": "X"})
        assert result is False

    def test_project_id_immutable(self, store):
        store.create_project(_make_project())
        store.update_project("test-project", {"project_id": "hacked", "name": "OK"})
        assert store.get_project("hacked") is None
        assert store.get_project("test-project") is not None

    def test_update_tags(self, store):
        store.create_project(_make_project(tags=["a"]))
        store.update_project("test-project", {"tags": ["b", "c"]})
        retrieved = store.get_project("test-project")
        assert "b" in retrieved.tags


class TestArchiveProject:
    def test_archive_sets_archived_flag(self, store):
        store.create_project(_make_project())
        store.archive_project("test-project")
        retrieved = store.get_project("test-project")
        assert retrieved.archived is True
        assert retrieved.ingestion_enabled is False

    def test_archive_nonexistent_returns_false(self, store):
        assert store.archive_project("nope") is False

    def test_unarchive_restores_active(self, store):
        store.create_project(_make_project())
        store.archive_project("test-project")
        store.unarchive_project("test-project")
        retrieved = store.get_project("test-project")
        assert retrieved.archived is False
        assert retrieved.ingestion_enabled is True


class TestProjectExists:
    def test_exists_for_created(self, store):
        store.create_project(_make_project())
        assert store.project_exists("test-project") is True

    def test_not_exists_for_unknown(self, store):
        assert store.project_exists("unknown") is False


class TestListActiveProjectIds:
    def test_returns_only_active_ids(self, store):
        store.create_project(_make_project(project_id="active-1", name="A1"))
        store.create_project(_make_project(project_id="active-2", name="A2"))
        store.create_project(_make_project(project_id="archived", name="AR", archived=True))
        ids = store.list_active_project_ids()
        assert "active-1" in ids
        assert "active-2" in ids
        assert "archived" not in ids

    def test_empty_when_no_active(self, store):
        store.create_project(_make_project(archived=True))
        ids = store.list_active_project_ids()
        assert ids == []


class TestProjectSummary:
    def test_summary_for_existing_project(self, store):
        store.create_project(_make_project())
        summary = store.project_summary(
            "test-project",
            snapshot_count=10,
            llm_event_count=500,
            latest_snapshot_at="2026-05-17T10:00:00Z",
        )
        assert summary["project"]["project_id"] == "test-project"
        assert summary["statistics"]["snapshot_count"] == 10
        assert summary["statistics"]["llm_event_count"] == 500
        assert summary["status"]["active"] is True

    def test_summary_for_nonexistent_returns_error(self, store):
        result = store.project_summary("nope")
        assert "error" in result

    def test_summary_archived_shows_inactive(self, store):
        store.create_project(_make_project())
        store.archive_project("test-project")
        summary = store.project_summary("test-project")
        assert summary["status"]["active"] is False
        assert summary["status"]["archived"] is True
