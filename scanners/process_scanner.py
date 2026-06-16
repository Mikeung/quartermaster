import logging
import subprocess
from typing import Any

from scanners.base import BaseScanner

logger = logging.getLogger(__name__)


class ProcessScanner(BaseScanner):
    """Scans running processes on the local host.

    Read-only. Does not kill or modify processes.
    """

    name = "process_scanner"

    def _scan(self, target: str = "localhost") -> dict[str, Any]:
        processes = self._get_processes()
        return {
            "target": target,
            "process_count": len(processes),
            "processes": processes,
        }

    def _get_processes(self) -> list[dict[str, str]]:
        try:
            output = subprocess.check_output(
                ["ps", "aux", "--no-headers"],
                text=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            logger.warning("Process scan failed", extra={"error": str(exc)})
            return []

        procs = []
        for line in output.strip().splitlines():
            parts = line.split(None, 10)
            if len(parts) >= 11:
                procs.append({"user": parts[0], "pid": parts[1], "command": parts[10]})
        return procs
