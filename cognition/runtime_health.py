"""
Runtime health intelligence — interpret runtime state into health indicators.

Applies deterministic thresholds to produce:
- per-resource health indicators
- overall health status
- instability signals
- resource pressure descriptions

All thresholds are VPS-appropriate heuristics.
No outage prediction. No speculative root-cause analysis.
Advisory output only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# VPS-appropriate thresholds
_CPU_WARN = 80.0
_CPU_CRIT = 95.0
_MEM_WARN = 85.0
_MEM_CRIT = 95.0
_SWAP_WARN = 25.0
_SWAP_CRIT = 60.0
_DISK_WARN = 85.0
_DISK_CRIT = 95.0
_ZOMBIE_WARN = 5

_STATUS_WEIGHTS = {"ok": 1.0, "degraded": 0.6, "stressed": 0.3, "critical": 0.0}


@dataclass
class HealthIndicator:
    """A single assessed resource health indicator."""
    name: str
    status: str        # "ok", "degraded", "stressed", "critical"
    value: str         # human-readable current value
    threshold: str     # human-readable threshold that triggered the status
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "threshold": self.threshold,
            "evidence": self.evidence,
        }


@dataclass
class RuntimeHealthReport:
    """Interpreted runtime health from a single RuntimeScanner output."""
    overall_status: str   # "healthy", "degraded", "stressed", "critical"
    health_score: float   # 0.0 (critical) → 1.0 (healthy)
    indicators: list[HealthIndicator]
    instability_signals: list[str]
    resource_pressure: list[str]
    failed_services: list[str]
    docker_restart_details: list[str]
    has_docker_restarts: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "health_score": round(self.health_score, 3),
            "indicators": [i.to_dict() for i in self.indicators],
            "instability_signals": self.instability_signals,
            "resource_pressure": self.resource_pressure,
            "failed_services": self.failed_services,
            "docker_restart_details": self.docker_restart_details,
            "has_docker_restarts": self.has_docker_restarts,
        }


class RuntimeHealthIntelligence:
    """Applies deterministic thresholds to runtime state.

    No ML. No speculation. Evidence-backed health indicators only.
    """

    def assess(self, runtime_state: dict[str, Any]) -> RuntimeHealthReport:
        if not runtime_state or "error" in runtime_state:
            return self._unavailable_report()

        indicators: list[HealthIndicator] = []
        resource_pressure: list[str] = []
        instability_signals: list[str] = []

        cpu = runtime_state.get("cpu_percent")
        if cpu is not None:
            ind = _assess_percent(
                name="CPU",
                value=cpu,
                warn=_CPU_WARN,
                crit=_CPU_CRIT,
                unit="%",
            )
            indicators.append(ind)
            if ind.status != "ok":
                resource_pressure.append(f"CPU at {cpu}%")

        mem = runtime_state.get("memory_percent")
        if mem is not None:
            ind = _assess_percent(
                name="Memory",
                value=mem,
                warn=_MEM_WARN,
                crit=_MEM_CRIT,
                unit="%",
            )
            indicators.append(ind)
            if ind.status != "ok":
                resource_pressure.append(f"Memory at {mem}%")

        swap = runtime_state.get("swap_percent")
        if swap is not None:
            ind = _assess_percent(
                name="Swap",
                value=swap,
                warn=_SWAP_WARN,
                crit=_SWAP_CRIT,
                unit="%",
                context="Swap usage indicates memory pressure; LLM workloads may experience latency",
            )
            indicators.append(ind)
            if ind.status != "ok":
                resource_pressure.append(f"Swap at {swap}%")

        disk = runtime_state.get("disk_percent")
        if disk is not None:
            free_gb = runtime_state.get("disk_free_gb", "?")
            ind = _assess_percent(
                name="Disk",
                value=disk,
                warn=_DISK_WARN,
                crit=_DISK_CRIT,
                unit="%",
                context=f"{free_gb} GB free",
            )
            indicators.append(ind)
            if ind.status != "ok":
                resource_pressure.append(f"Disk at {disk}% ({free_gb} GB free)")

        cpu_count = runtime_state.get("cpu_count") or 1
        load_1m = runtime_state.get("load_avg_1m")
        if load_1m is not None:
            load_status = "ok"
            if load_1m > cpu_count * 2:
                load_status = "critical"
            elif load_1m > cpu_count * 1.5:
                load_status = "stressed"
            elif load_1m > cpu_count:
                load_status = "degraded"
            indicators.append(HealthIndicator(
                name="Load Average (1m)",
                status=load_status,
                value=f"{load_1m} (cores: {cpu_count})",
                threshold=f">1× cores ({cpu_count})",
                evidence=[
                    f"Load avg 1m: {load_1m}, 5m: {runtime_state.get('load_avg_5m')}, "
                    f"15m: {runtime_state.get('load_avg_15m')}",
                ],
            ))
            if load_status != "ok":
                resource_pressure.append(f"Load avg {load_1m} exceeds {cpu_count} cores")

        zombies = runtime_state.get("zombie_count", 0)
        if zombies >= _ZOMBIE_WARN:
            indicators.append(HealthIndicator(
                name="Zombie Processes",
                status="degraded",
                value=str(zombies),
                threshold=f"≥{_ZOMBIE_WARN}",
                evidence=[f"{zombies} zombie processes detected — possible unreaped child process leak"],
            ))
            instability_signals.append(f"{zombies} zombie processes — possible subprocess cleanup failure")
        else:
            indicators.append(HealthIndicator(
                name="Zombie Processes",
                status="ok",
                value=str(zombies),
                threshold=f"<{_ZOMBIE_WARN}",
                evidence=[],
            ))

        failed_services = runtime_state.get("failed_services", [])
        if failed_services:
            indicators.append(HealthIndicator(
                name="Systemd Services",
                status="degraded",
                value=f"{len(failed_services)} failed",
                threshold="0 failed",
                evidence=[f"Failed: {', '.join(failed_services)}"],
            ))
            instability_signals.append(f"Failed services: {', '.join(failed_services)}")

        # Docker restarts
        docker_stats = runtime_state.get("docker_restart_stats", [])
        high_restart = [c for c in docker_stats if c.get("restart_count", 0) >= 3]
        docker_restart_details: list[str] = []
        has_docker_restarts = bool(high_restart)
        for c in high_restart:
            detail = f"Container '{c['name']}': {c['restart_count']} restarts ({c.get('status', '?')})"
            docker_restart_details.append(detail)
            instability_signals.append(f"Container restart loop: {c['name']} ({c['restart_count']}×)")

        overall = _overall_status(indicators)
        score = _health_score(indicators)

        logger.info(
            "Runtime health assessment complete",
            extra={
                "overall_status": overall,
                "health_score": round(score, 3),
                "failed_services": len(failed_services),
                "resource_pressure_count": len(resource_pressure),
            },
        )

        return RuntimeHealthReport(
            overall_status=overall,
            health_score=score,
            indicators=indicators,
            instability_signals=instability_signals,
            resource_pressure=resource_pressure,
            failed_services=failed_services,
            docker_restart_details=docker_restart_details,
            has_docker_restarts=has_docker_restarts,
        )

    def _unavailable_report(self) -> RuntimeHealthReport:
        return RuntimeHealthReport(
            overall_status="unknown",
            health_score=0.5,
            indicators=[],
            instability_signals=["Runtime state unavailable — scanner did not return data"],
            resource_pressure=[],
            failed_services=[],
            docker_restart_details=[],
            has_docker_restarts=False,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assess_percent(
    name: str,
    value: float,
    warn: float,
    crit: float,
    unit: str = "%",
    context: str = "",
) -> HealthIndicator:
    if value >= crit:
        status = "critical"
        threshold = f"≥{crit}{unit}"
    elif value >= warn:
        status = "stressed"
        threshold = f"≥{warn}{unit}"
    elif value >= warn * 0.75:
        status = "degraded"
        threshold = f"≥{warn * 0.75:.0f}{unit}"
    else:
        status = "ok"
        threshold = f"<{warn}{unit}"

    evidence = [f"{name}: {value}{unit}"]
    if context:
        evidence.append(context)

    return HealthIndicator(
        name=name,
        status=status,
        value=f"{value}{unit}",
        threshold=threshold,
        evidence=evidence,
    )


def _overall_status(indicators: list[HealthIndicator]) -> str:
    statuses = {i.status for i in indicators}
    if "critical" in statuses:
        return "critical"
    if "stressed" in statuses:
        return "stressed"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def _health_score(indicators: list[HealthIndicator]) -> float:
    if not indicators:
        return 1.0
    weights = [_STATUS_WEIGHTS.get(i.status, 0.5) for i in indicators]
    return round(sum(weights) / len(weights), 3)
