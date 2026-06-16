import logging
import time
from typing import Any

from scanners.base import BaseScanner

logger = logging.getLogger(__name__)


class ScannerRegistry:
    """Runs registered read-only scanners against a target and aggregates results."""

    def __init__(self) -> None:
        self._scanners: dict[str, BaseScanner] = {}

    def register(self, scanner: BaseScanner) -> None:
        self._scanners[scanner.name] = scanner
        logger.info("Scanner registered", extra={"scanner": scanner.name})

    def run_all(self, target: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        timings: dict[str, float] = {}

        logger.info(
            "Registry scan starting",
            extra={"scanners": list(self._scanners.keys()), "target": target},
        )

        for name, scanner in self._scanners.items():
            t0 = time.monotonic()
            try:
                results[name] = scanner.run(target)
            except Exception as exc:
                logger.error(
                    "Scanner raised exception",
                    extra={"scanner": name, "error": str(exc)},
                )
                errors[name] = str(exc)
                results[name] = {"error": str(exc), "scanner": name}
            timings[name] = round(time.monotonic() - t0, 3)
            logger.info(
                "Scanner finished",
                extra={
                    "scanner": name,
                    "elapsed_s": timings[name],
                    "error": errors.get(name),
                },
            )

        logger.info(
            "Registry scan complete",
            extra={"scanners": list(self._scanners.keys()), "error_count": len(errors)},
        )

        return {
            "target": target,
            "scanners_run": list(self._scanners.keys()),
            "results": results,
            "errors": errors,
            "timings_s": timings,
        }

    def run_one(self, name: str, target: str) -> dict[str, Any]:
        if name not in self._scanners:
            raise KeyError(f"Scanner '{name}' not registered. Available: {list(self._scanners)}")
        t0 = time.monotonic()
        error: str | None = None
        try:
            result = self._scanners[name].run(target)
        except Exception as exc:
            logger.error("Scanner raised exception", extra={"scanner": name, "error": str(exc)})
            result = {"error": str(exc)}
            error = str(exc)
        return {
            "scanner": name,
            "target": target,
            "result": result,
            "elapsed_s": round(time.monotonic() - t0, 3),
            "error": error,
        }

    @property
    def registered(self) -> list[str]:
        return list(self._scanners.keys())
