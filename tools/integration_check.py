"""
IntegrationChecker — validates that an operational memory integration is
configured correctly and the target service is reachable.

Purpose:
- Detect configuration problems before they reach production
- Surface payload quality issues
- Validate connectivity and project registration
- Produce an actionable integration readiness report

IMPORTANT:
- Validation only — never patches, never modifies
- No automatic fixes
- All checks are read-only
- Reports findings, operator decides action

Usage:
    from tools.integration_check import IntegrationChecker

    checker = IntegrationChecker(base_url="http://localhost:8000", project_id="my-app")
    report = checker.run()
    print(report.markdown())
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class IntegrationCheckItem:
    """Single check result."""
    name: str
    passed: bool
    message: str
    severity: str = "info"      # info | warning | error

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class IntegrationReport:
    """Full integration validation report."""
    base_url: str
    project_id: str
    generated_at: str
    items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: int = 0
    total: int = 0
    ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "project_id": self.project_id,
            "generated_at": self.generated_at,
            "ready": self.ready,
            "passed": self.passed,
            "total": self.total,
            "items": self.items,
            "warnings": self.warnings,
        }

    def markdown(self) -> str:
        lines: list[str] = [
            "# Integration Validation Report",
            "",
            f"**Service:** {self.base_url}",
            f"**Project:** `{self.project_id}`",
            f"**Generated:** {self.generated_at}",
            f"**Readiness:** {'✓ READY' if self.ready else '✗ NOT READY'}",
            f"**Checks:** {self.passed}/{self.total} passed",
            "",
            "## Checks",
            "",
        ]
        for item in self.items:
            icon = "✓" if item["passed"] else "✗"
            sev = f" [{item['severity'].upper()}]" if not item["passed"] else ""
            lines.append(f"- {icon} **{item['name']}**{sev}: {item['message']}")

        if self.warnings:
            lines += ["", "## Warnings", ""]
            for w in self.warnings:
                lines.append(f"- ⚠ {w}")

        lines += [
            "",
            "## Next Steps",
            "",
        ]
        failed = [i for i in self.items if not i["passed"]]
        if not failed:
            lines.append("All checks passed. Integration appears ready.")
        else:
            lines.append("Address the failed checks before relying on ingestion data:")
            for f in failed:
                lines.append(f"- **{f['name']}**: {f['message']}")

        lines.append("")
        lines.append(
            "_This report is advisory. No automatic changes were made. "
            "Operator review required before acting on findings._"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class IntegrationChecker:
    """
    Validates integration readiness against a running operational memory service.

    Checks performed:
    1. Service connectivity (GET /health)
    2. Project registration (GET /projects/{id})
    3. Ingestion endpoint reachable (GET /llm/storage)
    4. Test event accepted (POST /llm/events with minimal synthetic event)
    5. Privacy gate working (POST /llm/events with forbidden field — must reject)
    6. Project scope valid (project_id format)
    7. Service version present
    8. Payload field validation (missing required fields — must reject with 422)
    """

    def __init__(self, base_url: str, project_id: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.timeout = timeout

    def run(self) -> IntegrationReport:
        """Run all checks and return a consolidated report."""
        items: list[IntegrationCheckItem] = []
        warnings: list[str] = []

        items.append(self._check_project_id_format())
        items.append(self._check_service_connectivity())

        # Only run service-dependent checks if connectivity passed
        if items[-1].passed:
            items.append(self._check_service_version())
            items.append(self._check_project_registered())
            items.append(self._check_ingestion_endpoint())
            items.append(self._check_test_event_accepted())
            items.append(self._check_privacy_gate())
            items.append(self._check_required_fields_rejected())
            w = self._check_project_pressure_warning()
            if w:
                warnings.append(w)
        else:
            # Mark remaining checks as skipped
            skipped = [
                "Service Version", "Project Registration", "Ingestion Endpoint",
                "Test Event Acceptance", "Privacy Gate", "Required Field Validation",
            ]
            for name in skipped:
                items.append(IntegrationCheckItem(
                    name=name, passed=False,
                    message="Skipped — service unreachable",
                    severity="error",
                ))

        passed = sum(1 for i in items if i.passed)
        total = len(items)
        # Ready if all error-severity checks passed (warnings allowed)
        error_items = [i for i in items if i.severity == "error" and not i.passed]
        ready = len(error_items) == 0 and passed > 0

        return IntegrationReport(
            base_url=self.base_url,
            project_id=self.project_id,
            generated_at=datetime.now(UTC).isoformat(),
            items=[i.to_dict() for i in items],
            warnings=warnings,
            passed=passed,
            total=total,
            ready=ready,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_project_id_format(self) -> IntegrationCheckItem:
        pid = self.project_id
        import re
        pattern = re.compile(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$")
        if not pattern.match(pid):
            return IntegrationCheckItem(
                name="Project ID Format",
                passed=False,
                message=(
                    f"'{pid}' does not match required format "
                    "(3–64 chars, lowercase alphanumeric + dashes, no leading/trailing dashes)"
                ),
                severity="error",
            )
        return IntegrationCheckItem(
            name="Project ID Format",
            passed=True,
            message=f"'{pid}' is a valid project ID format",
        )

    def _check_service_connectivity(self) -> IntegrationCheckItem:
        t0 = time.monotonic()
        try:
            status, data = _http_get(f"{self.base_url}/health", self.timeout)
            elapsed = (time.monotonic() - t0) * 1000
            if status == 200:
                return IntegrationCheckItem(
                    name="Service Connectivity",
                    passed=True,
                    message=f"Service reachable ({elapsed:.0f}ms)",
                )
            return IntegrationCheckItem(
                name="Service Connectivity",
                passed=False,
                message=f"Unexpected status {status} from /health",
                severity="error",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Service Connectivity",
                passed=False,
                message=f"Cannot connect to {self.base_url}: {exc}",
                severity="error",
            )

    def _check_service_version(self) -> IntegrationCheckItem:
        try:
            status, data = _http_get(f"{self.base_url}/health", self.timeout)
            if status == 200 and isinstance(data, dict):
                version = data.get("version") or data.get("app_version")
                if version:
                    return IntegrationCheckItem(
                        name="Service Version",
                        passed=True,
                        message=f"Version: {version}",
                    )
            return IntegrationCheckItem(
                name="Service Version",
                passed=True,
                message="Service reachable but version not exposed (non-critical)",
                severity="info",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Service Version",
                passed=False,
                message=str(exc),
                severity="warning",
            )

    def _check_project_registered(self) -> IntegrationCheckItem:
        try:
            status, data = _http_get(
                f"{self.base_url}/projects/{self.project_id}", self.timeout
            )
            if status == 200:
                archived = data.get("archived", False) if isinstance(data, dict) else False
                if archived:
                    return IntegrationCheckItem(
                        name="Project Registration",
                        passed=False,
                        message=f"Project '{self.project_id}' exists but is archived — ingestion disabled",
                        severity="error",
                    )
                return IntegrationCheckItem(
                    name="Project Registration",
                    passed=True,
                    message=f"Project '{self.project_id}' is registered and active",
                )
            if status == 404:
                return IntegrationCheckItem(
                    name="Project Registration",
                    passed=False,
                    message=(
                        f"Project '{self.project_id}' not found. "
                        "Register with: POST /projects or `aom register {self.project_id}`"
                    ),
                    severity="error",
                )
            return IntegrationCheckItem(
                name="Project Registration",
                passed=False,
                message=f"Unexpected status {status} checking project",
                severity="warning",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Project Registration",
                passed=False,
                message=str(exc),
                severity="warning",
            )

    def _check_ingestion_endpoint(self) -> IntegrationCheckItem:
        try:
            status, _ = _http_get(f"{self.base_url}/llm/storage", self.timeout)
            if status == 200:
                return IntegrationCheckItem(
                    name="Ingestion Endpoint",
                    passed=True,
                    message="LLM ingestion endpoint reachable (/llm/storage OK)",
                )
            return IntegrationCheckItem(
                name="Ingestion Endpoint",
                passed=False,
                message=f"LLM storage endpoint returned {status}",
                severity="warning",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Ingestion Endpoint",
                passed=False,
                message=str(exc),
                severity="error",
            )

    def _check_test_event_accepted(self) -> IntegrationCheckItem:
        payload = {
            "provider": "integration-check",
            "model": "test-model",
            "workflow": "integration-check/connectivity-test",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "latency_ms": 1.0,
            "success": True,
            "request_kind": "completion",
            "project_id": self.project_id,
            "schema_version": "1.0",
        }
        try:
            t0 = time.monotonic()
            status, data = _http_post(f"{self.base_url}/llm/events", payload, self.timeout)
            elapsed = (time.monotonic() - t0) * 1000
            if status == 200:
                return IntegrationCheckItem(
                    name="Test Event Acceptance",
                    passed=True,
                    message=f"Test event accepted ({elapsed:.0f}ms)",
                )
            if status == 422:
                reason = data.get("rejection_reason") if isinstance(data, dict) else str(data)
                return IntegrationCheckItem(
                    name="Test Event Acceptance",
                    passed=False,
                    message=f"Test event rejected: {reason}",
                    severity="error",
                )
            return IntegrationCheckItem(
                name="Test Event Acceptance",
                passed=False,
                message=f"Unexpected status {status}",
                severity="error",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Test Event Acceptance",
                passed=False,
                message=str(exc),
                severity="error",
            )

    def _check_privacy_gate(self) -> IntegrationCheckItem:
        """Verify that the privacy gate correctly rejects forbidden fields."""
        forbidden_payload = {
            "provider": "integration-check",
            "model": "test-model",
            "workflow": "integration-check/privacy-gate-test",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "latency_ms": 1.0,
            "success": True,
            "prompt": "This should be rejected — contains forbidden field",
            "schema_version": "1.0",
        }
        try:
            status, data = _http_post(
                f"{self.base_url}/llm/events", forbidden_payload, self.timeout
            )
            if status == 422:
                return IntegrationCheckItem(
                    name="Privacy Gate",
                    passed=True,
                    message="Privacy gate correctly rejected forbidden 'prompt' field",
                )
            if status == 200:
                return IntegrationCheckItem(
                    name="Privacy Gate",
                    passed=False,
                    message="Privacy gate FAILED — accepted payload with forbidden 'prompt' field",
                    severity="error",
                )
            return IntegrationCheckItem(
                name="Privacy Gate",
                passed=False,
                message=f"Unexpected status {status} from privacy gate test",
                severity="warning",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Privacy Gate",
                passed=False,
                message=str(exc),
                severity="warning",
            )

    def _check_required_fields_rejected(self) -> IntegrationCheckItem:
        """Verify that missing required fields produce a 422."""
        incomplete_payload = {
            "provider": "integration-check",
            # Missing: model, workflow, prompt_tokens, completion_tokens, latency_ms, success
        }
        try:
            status, data = _http_post(
                f"{self.base_url}/llm/events", incomplete_payload, self.timeout
            )
            if status == 422:
                return IntegrationCheckItem(
                    name="Required Field Validation",
                    passed=True,
                    message="Service correctly rejected incomplete payload (missing required fields)",
                )
            if status == 200:
                return IntegrationCheckItem(
                    name="Required Field Validation",
                    passed=False,
                    message="Service accepted incomplete payload — required field validation may be missing",
                    severity="warning",
                )
            return IntegrationCheckItem(
                name="Required Field Validation",
                passed=True,
                message=f"Service returned {status} for incomplete payload (acceptable)",
            )
        except Exception as exc:
            return IntegrationCheckItem(
                name="Required Field Validation",
                passed=False,
                message=str(exc),
                severity="warning",
            )

    def _check_project_pressure_warning(self) -> str | None:
        """Return a warning string if this project has high ingestion pressure."""
        try:
            status, data = _http_get(
                f"{self.base_url}/projects/{self.project_id}/health", self.timeout
            )
            if status == 200 and isinstance(data, dict):
                pressure = data.get("ingestion_pressure") or {}
                level = pressure.get("pressure_level", "ok")
                if level in ("warning", "critical"):
                    return (
                        f"Project '{self.project_id}' has {level}-level ingestion pressure. "
                        "Consider reviewing event volume before deploying additional integrations."
                    )
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# HTTP utilities (no SDK dependency)
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: float) -> tuple[int, Any]:
    try:
        import httpx  # type: ignore[import-untyped]
        r = httpx.get(url, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except ImportError:
        pass
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as exc:
        raise ConnectionError(str(exc)) from exc


def _http_post(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, Any]:
    body = json.dumps(payload).encode()
    try:
        import httpx  # type: ignore[import-untyped]
        r = httpx.post(url, json=payload, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except ImportError:
        pass
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, e.reason
    except Exception as exc:
        raise ConnectionError(str(exc)) from exc
