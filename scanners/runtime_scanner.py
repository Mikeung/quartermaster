"""
Runtime state scanner — lightweight, bounded, Linux-native.

Reads current system resource state using psutil and platform tools.
Read-only. Never modifies any system state.

Designed for VPS-first use: bounded timeouts, graceful fallbacks,
no streaming, no continuous monitoring.
"""

import logging
import subprocess
import time
from typing import Any

from scanners.base import BaseScanner

logger = logging.getLogger(__name__)


class RuntimeScanner(BaseScanner):
    """Scans host runtime state: CPU, memory, disk, load, zombies, failed services.

    Uses psutil for cross-platform resource readings where available.
    Falls back to /proc and subprocess for Linux-specific data.
    """

    name = "runtime_scanner"

    def _scan(self, target: str = "localhost") -> dict[str, Any]:
        try:
            import psutil
            _psutil = psutil
        except ImportError:
            logger.warning("psutil not available — runtime scan degraded")
            _psutil = None

        result: dict[str, Any] = {
            "target": target,
            "scanned_at": _iso_now(),
        }

        result.update(self._cpu(_psutil))
        result.update(self._memory(_psutil))
        result.update(self._disk(_psutil))
        result.update(self._load(_psutil))
        result.update(self._uptime(_psutil))
        result.update(self._process_stats(_psutil))
        result["failed_services"] = self._failed_services()
        result["docker_restart_stats"] = self._docker_restart_stats()

        logger.info(
            "Runtime scan complete",
            extra={
                "cpu_percent": result.get("cpu_percent"),
                "memory_percent": result.get("memory_percent"),
                "failed_service_count": len(result.get("failed_services", [])),
            },
        )
        return result

    def _cpu(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"cpu_percent": None, "cpu_count": None}
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            return {"cpu_percent": round(cpu, 1), "cpu_count": psutil.cpu_count(logical=True)}
        except Exception as e:
            logger.debug("CPU read failed", extra={"error": str(e)})
            return {"cpu_percent": None, "cpu_count": None}

    def _memory(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"memory_percent": None, "memory_used_gb": None, "memory_total_gb": None, "swap_percent": None}
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            return {
                "memory_percent": round(mem.percent, 1),
                "memory_used_gb": round(mem.used / 1e9, 2),
                "memory_total_gb": round(mem.total / 1e9, 2),
                "swap_percent": round(swap.percent, 1),
            }
        except Exception as e:
            logger.debug("Memory read failed", extra={"error": str(e)})
            return {"memory_percent": None, "memory_used_gb": None, "memory_total_gb": None, "swap_percent": None}

    def _disk(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"disk_percent": None, "disk_free_gb": None}
        try:
            disk = psutil.disk_usage("/")
            return {
                "disk_percent": round(disk.percent, 1),
                "disk_free_gb": round(disk.free / 1e9, 2),
            }
        except Exception as e:
            logger.debug("Disk read failed", extra={"error": str(e)})
            return {"disk_percent": None, "disk_free_gb": None}

    def _load(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"load_avg_1m": None, "load_avg_5m": None, "load_avg_15m": None}
        try:
            load = psutil.getloadavg()
            return {
                "load_avg_1m": round(load[0], 2),
                "load_avg_5m": round(load[1], 2),
                "load_avg_15m": round(load[2], 2),
            }
        except Exception as e:
            logger.debug("Load avg read failed", extra={"error": str(e)})
            return {"load_avg_1m": None, "load_avg_5m": None, "load_avg_15m": None}

    def _uptime(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"uptime_hours": None}
        try:
            boot = psutil.boot_time()
            uptime_s = time.time() - boot
            return {"uptime_hours": round(uptime_s / 3600, 1)}
        except Exception as e:
            logger.debug("Uptime read failed", extra={"error": str(e)})
            return {"uptime_hours": None}

    def _process_stats(self, psutil: Any) -> dict[str, Any]:
        if not psutil:
            return {"process_count": None, "zombie_count": 0}
        try:
            procs = list(psutil.process_iter(["status"]))
            count = len(procs)
            zombies = sum(1 for p in procs if p.info.get("status") == psutil.STATUS_ZOMBIE)
            return {"process_count": count, "zombie_count": zombies}
        except Exception as e:
            logger.debug("Process stats failed", extra={"error": str(e)})
            return {"process_count": None, "zombie_count": 0}

    def _failed_services(self) -> list[str]:
        try:
            out = subprocess.check_output(
                ["systemctl", "--failed", "--no-legend", "--no-pager"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            services = []
            for line in out.strip().splitlines():
                parts = line.split()
                if parts:
                    services.append(parts[0].strip("●").strip())
            return [s for s in services if s]
        except Exception:
            return []

    def _docker_restart_stats(self) -> list[dict[str, Any]]:
        try:
            out = subprocess.check_output(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.RestartCount}}"],
                text=True,
                timeout=8,
                stderr=subprocess.DEVNULL,
            )
            stats = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    try:
                        restarts = int(parts[2])
                    except ValueError:
                        restarts = 0
                    stats.append({
                        "name": parts[0],
                        "status": parts[1],
                        "restart_count": restarts,
                    })
            return stats
        except Exception:
            return []


def _iso_now() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()
