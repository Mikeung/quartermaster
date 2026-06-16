from typing import Any

import pytest

from scanners.base import BaseScanner
from scanners.registry import ScannerRegistry


class _DummyScanner(BaseScanner):
    name = "dummy"

    def _scan(self, target: str) -> dict[str, Any]:
        return {"dummy": True, "target": target}


class _FailingScanner(BaseScanner):
    name = "failing"

    def _scan(self, target: str) -> dict[str, Any]:
        raise RuntimeError("Intentional scanner failure")


def test_registry_registers_and_runs() -> None:
    registry = ScannerRegistry()
    registry.register(_DummyScanner())
    assert "dummy" in registry.registered

    result = registry.run_all(".")
    assert result["results"]["dummy"]["dummy"] is True


def test_registry_handles_scanner_failure_gracefully() -> None:
    registry = ScannerRegistry()
    registry.register(_FailingScanner())
    result = registry.run_all(".")
    assert "failing" in result["errors"]
    assert "error" in result["results"]["failing"]


def test_registry_run_one_unknown_raises() -> None:
    registry = ScannerRegistry()
    with pytest.raises(KeyError):
        registry.run_one("nonexistent", ".")


def test_registry_run_one_success() -> None:
    registry = ScannerRegistry()
    registry.register(_DummyScanner())
    out = registry.run_one("dummy", ".")
    assert out["result"]["dummy"] is True
    assert out["error"] is None


def test_registry_multiple_scanners_aggregate() -> None:
    registry = ScannerRegistry()
    registry.register(_DummyScanner())
    registry.register(_FailingScanner())
    result = registry.run_all(".")
    assert len(result["scanners_run"]) == 2
    assert len(result["errors"]) == 1
    assert result["results"]["dummy"]["dummy"] is True
