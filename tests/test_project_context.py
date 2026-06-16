"""Tests for config/project_context.py resolution logic (data-agnostic).

The OSS build ships empty registries; these tests inject a small demo registry
and verify the deterministic resolution behaviour rather than any shipped data.
"""

from __future__ import annotations

import pytest

from config import project_context as pc
from config.project_context import (
    NOT_REGISTERED,
    Ownership,
    ProjectContext,
    canonical_project_id,
    resolve_project_context,
)


@pytest.fixture
def demo_registry(monkeypatch):
    monkeypatch.setattr(pc, "PROJECT_CONTEXT_REGISTRY", {
        "demo-app": ProjectContext(
            project="Demo App", purpose="example", runtime="python",
            subsystems={"worker": "the worker"},
            services={"demo-worker": "drains the queue"},
        ),
    })
    monkeypatch.setattr(pc, "_PROJECT_ALIASES", {"demo": "demo-app"})
    monkeypatch.setattr(pc, "SERVICE_OWNERSHIP", {
        "demo-worker": Ownership(project_id="demo-app", subsystem="worker",
                                 service="demo-worker"),
    })
    monkeypatch.setattr(pc, "PORT_OWNERSHIP", {
        9000: Ownership(project_id="demo-app", subsystem="api", service="port:9000"),
    })
    monkeypatch.setattr(pc, "PROJECT_PATH_ROOTS", {"/srv/demo-app": "demo-app"})


class TestCanonical:
    def test_alias_resolves(self, demo_registry):
        assert canonical_project_id("demo") == "demo-app"

    def test_unknown_is_none(self, demo_registry):
        assert canonical_project_id("nope") is None


class TestResolution:
    def test_service_name_attributes_to_project(self, demo_registry):
        ctx = resolve_project_context({"target_id": "vps", "resource": "demo-worker"})
        assert ctx.registered is True
        assert ctx.project == "Demo App"
        assert ctx.service_purpose == "drains the queue"

    def test_path_attributes_by_directory(self, demo_registry):
        ctx = resolve_project_context({"target_id": "vps", "resource": "/srv/demo-app/.env"})
        assert ctx.registered is True
        assert ctx.project == "Demo App"

    def test_port_attributes_to_project(self, demo_registry):
        ctx = resolve_project_context({"target_id": "vps", "resource": "port:9000"})
        assert ctx.registered is True
        assert ctx.project == "Demo App"

    def test_unregistered_yields_explicit_gap(self, demo_registry):
        ctx = resolve_project_context({"target_id": "vps", "resource": "mystery-svc"})
        assert ctx.registered is False
        assert ctx.project_purpose == NOT_REGISTERED

    def test_empty_registry_is_safe(self, monkeypatch):
        # Default OSS state: no projects declared → explicit gap, never a crash.
        monkeypatch.setattr(pc, "PROJECT_CONTEXT_REGISTRY", {})
        monkeypatch.setattr(pc, "SERVICE_OWNERSHIP", {})
        ctx = resolve_project_context({"target_id": "vps", "resource": "anything"})
        assert ctx.registered is False
