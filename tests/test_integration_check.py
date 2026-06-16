"""Tests for tools/integration_check.py — integration validation."""

from __future__ import annotations

from tools.integration_check import (
    IntegrationChecker,
    IntegrationCheckItem,
    IntegrationReport,
)


class TestIntegrationCheckItemFormat:
    def test_project_id_valid(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="my-app")
        item = checker._check_project_id_format()
        assert item.passed is True

    def test_project_id_too_short(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="ab")
        item = checker._check_project_id_format()
        assert item.passed is False
        assert item.severity == "error"

    def test_project_id_starts_with_dash(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="-my-app")
        item = checker._check_project_id_format()
        assert item.passed is False

    def test_project_id_ends_with_dash(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="my-app-")
        item = checker._check_project_id_format()
        assert item.passed is False

    def test_project_id_with_uppercase_fails(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="My-App")
        item = checker._check_project_id_format()
        assert item.passed is False

    def test_project_id_dashes_ok(self):
        checker = IntegrationChecker(base_url="http://localhost:8000", project_id="my-rag-app-v2")
        item = checker._check_project_id_format()
        assert item.passed is True


class TestIntegrationReport:
    def _make_report(self, ready: bool = True, passed: int = 8, total: int = 8) -> IntegrationReport:
        items = [{"name": f"Check {i}", "passed": i < passed, "message": "ok", "severity": "info"} for i in range(total)]
        return IntegrationReport(
            base_url="http://localhost:8000",
            project_id="my-app",
            generated_at="2026-05-17T10:00:00Z",
            items=items,
            warnings=["A test warning"],
            passed=passed,
            total=total,
            ready=ready,
        )

    def test_to_dict_serializable(self):
        report = self._make_report()
        d = report.to_dict()
        assert "ready" in d
        assert "passed" in d
        assert "items" in d
        assert "warnings" in d

    def test_markdown_contains_header(self):
        report = self._make_report()
        md = report.markdown()
        assert "# Integration Validation Report" in md

    def test_markdown_shows_ready_status(self):
        report = self._make_report(ready=True)
        md = report.markdown()
        assert "READY" in md

    def test_markdown_shows_not_ready(self):
        report = self._make_report(ready=False, passed=5, total=8)
        md = report.markdown()
        assert "NOT READY" in md

    def test_markdown_includes_warnings(self):
        report = self._make_report()
        md = report.markdown()
        assert "A test warning" in md


class TestIntegrationCheckItem:
    def test_to_dict(self):
        item = IntegrationCheckItem(
            name="Test Check",
            passed=True,
            message="All good",
            severity="info",
        )
        d = item.to_dict()
        assert d["name"] == "Test Check"
        assert d["passed"] is True
        assert d["severity"] == "info"

    def test_failed_item_has_error_severity(self):
        item = IntegrationCheckItem(
            name="Connectivity",
            passed=False,
            message="Cannot connect",
            severity="error",
        )
        assert item.severity == "error"
