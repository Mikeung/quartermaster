"""
Observation layer — facts emitted by scanners.

Observations are the boundary between raw scanner output and the cognition layer.
They represent what was directly seen, not what was inferred from it.

Rules:
- Observations are factual only. No interpretation here.
- Every observation references the scanner that produced it.
- Observations are serializable and immutable.

The inference layer (topology builder, workflow inference, cost intelligence)
consumes observations and produces inferences. Observations never produce inferences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ObservationKind(str, Enum):
    DETECTED_PACKAGE = "detected_package"
    DETECTED_PORT = "detected_port"
    DETECTED_IMPORT = "detected_import"
    DETECTED_COMPOSE_FILE = "detected_compose_file"
    DETECTED_PROCESS = "detected_process"
    DETECTED_ENV_FILE = "detected_env_file"
    DETECTED_CI_CONFIG = "detected_ci_config"
    DETECTED_FRAMEWORK = "detected_framework"
    DETECTED_LLM_SDK = "detected_llm_sdk"
    DETECTED_PROCESS_MANAGER = "detected_process_manager"


@dataclass(frozen=True)
class Observation:
    """A single factual observation emitted by a scanner.

    Immutable. Contains only what was directly detected, not what it means.
    """
    kind: ObservationKind
    scanner: str
    target: str
    value: str
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "scanner": self.scanner,
            "target": self.target,
            "value": self.value,
            "metadata": self.metadata,
            "observed_at": self.observed_at.isoformat(),
        }


def observations_from_scan(scan_payload: dict[str, Any]) -> list[Observation]:
    """Normalize a raw scan payload into a flat list of typed observations.

    This is the entry point from scan output into the observation layer.
    Facts only — no inference, no scoring, no relationships.
    """
    observations: list[Observation] = []
    target = scan_payload.get("target", "unknown")
    results = scan_payload.get("scanner_results", {}).get("results", {})

    repo = results.get("repo_scanner", {})
    if repo and "error" not in repo:
        observations.extend(_repo_observations(repo, target))

    service = results.get("service_scanner", {})
    if service and "error" not in service:
        observations.extend(_service_observations(service, target))

    process = results.get("process_scanner", {})
    if process and "error" not in process:
        observations.extend(_process_observations(process, target))

    for det in scan_payload.get("llm_detections", []):
        observations.append(Observation(
            kind=ObservationKind.DETECTED_IMPORT,
            scanner="llm_detector",
            target=target,
            value=det.get("provider", "unknown"),
            metadata={
                "confidence": det.get("confidence"),
                "evidence": det.get("evidence", []),
            },
        ))

    return observations


def _repo_observations(repo: dict[str, Any], target: str) -> list[Observation]:
    obs: list[Observation] = []

    for pkg in repo.get("llm_sdks", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_LLM_SDK,
            scanner="repo_scanner",
            target=target,
            value=pkg,
            metadata={"source": "package_manifest"},
        ))

    for fw in repo.get("frameworks", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_FRAMEWORK,
            scanner="repo_scanner",
            target=target,
            value=fw,
            metadata={"source": "package_manifest"},
        ))

    for pm in repo.get("process_managers", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_PROCESS_MANAGER,
            scanner="repo_scanner",
            target=target,
            value=pm,
            metadata={"source": "filesystem"},
        ))

    docker = repo.get("docker", {})
    if docker.get("present"):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_COMPOSE_FILE,
            scanner="repo_scanner",
            target=target,
            value="docker",
            metadata={"indicators": docker.get("indicators", [])},
        ))

    for env_file in repo.get("env_files", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_ENV_FILE,
            scanner="repo_scanner",
            target=target,
            value=env_file,
        ))

    for ci in repo.get("ci_cd", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_CI_CONFIG,
            scanner="repo_scanner",
            target=target,
            value=ci,
        ))

    return obs


def _service_observations(service: dict[str, Any], target: str) -> list[Observation]:
    obs: list[Observation] = []
    for port_info in service.get("listening_ports", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_PORT,
            scanner="service_scanner",
            target=target,
            value=str(port_info.get("port", "unknown")),
            metadata={
                "service_hint": port_info.get("service"),
                "process": port_info.get("process"),
                "address": port_info.get("address"),
            },
        ))
    return obs


def _process_observations(process: dict[str, Any], target: str) -> list[Observation]:
    obs: list[Observation] = []
    for proc in process.get("running_processes", []):
        obs.append(Observation(
            kind=ObservationKind.DETECTED_PROCESS,
            scanner="process_scanner",
            target=target,
            value=proc.get("name", "unknown"),
            metadata={
                "pid": proc.get("pid"),
                "command": proc.get("command"),
            },
        ))
    return obs
