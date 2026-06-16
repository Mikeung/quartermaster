import logging
import os
import re
import subprocess
from typing import Any

from scanners.base import BaseScanner

logger = logging.getLogger(__name__)

PORT_SERVICE_MAP: dict[int, str] = {
    22: "ssh",
    80: "http",
    443: "https",
    3000: "node/react-dev",
    3306: "mysql",
    5000: "flask/generic",
    5432: "postgresql",
    5672: "rabbitmq",
    6333: "qdrant",
    6334: "qdrant-grpc",
    6379: "redis",
    7700: "meilisearch",
    8000: "fastapi/uvicorn",
    8001: "api-alt",
    8080: "http-alt",
    8088: "api-gateway",
    8200: "vault",
    8500: "consul",
    8888: "jupyter",
    9200: "elasticsearch",
    9300: "elasticsearch-cluster",
    11434: "ollama",
    19530: "milvus",
    27017: "mongodb",
    50051: "grpc",
}


class ServiceScanner(BaseScanner):
    """Scans for active network listeners and compose-declared ports.

    Read-only. Advisory output only. Does not modify any network state.
    """

    name = "service_scanner"

    def _scan(self, target: str) -> dict[str, Any]:
        listening_ports = _get_listening_ports()
        compose_ports = _get_compose_ports(target)

        seen_ports: set[int] = {p["port"] for p in listening_ports}
        for cp in compose_ports:
            if cp["port"] not in seen_ports:
                listening_ports.append(cp)
                seen_ports.add(cp["port"])

        logger.info(
            "Service scan complete",
            extra={
                "target": target,
                "port_count": len(listening_ports),
                "compose_ports": len(compose_ports),
            },
        )
        return {
            "target": target,
            "listening_ports": listening_ports,
            "compose_ports_declared": compose_ports,
        }


def _get_listening_ports() -> list[dict[str, Any]]:
    ports = _try_ss()
    if not ports:
        ports = _try_netstat()
    return ports


def _try_ss() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        return _parse_ss_output(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _try_netstat() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            ["netstat", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        return _parse_netstat_output(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _parse_ss_output(output: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    seen: set[int] = set()

    for line in output.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 5:
            continue
        addr = parts[4]
        port = _extract_port(addr)
        if port is None or port in seen:
            continue
        seen.add(port)
        process = _extract_process_from_ss(line)
        ports.append({
            "port": port,
            "service": PORT_SERVICE_MAP.get(port, f"unknown-{port}"),
            "process": process,
            "source": "ss",
        })

    return ports


def _parse_netstat_output(output: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    seen: set[int] = set()

    for line in output.splitlines():
        if "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        addr = parts[3]
        port = _extract_port(addr)
        if port is None or port in seen:
            continue
        seen.add(port)
        process = parts[-1] if len(parts) > 5 else None
        ports.append({
            "port": port,
            "service": PORT_SERVICE_MAP.get(port, f"unknown-{port}"),
            "process": process,
            "source": "netstat",
        })

    return ports


def _extract_port(addr: str) -> int | None:
    m = re.search(r":(\d+)$", addr)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _extract_process_from_ss(line: str) -> str | None:
    m = re.search(r'users:\(\("([^"]+)"', line)
    if m:
        return m.group(1)
    return None


def _get_compose_ports(target: str) -> list[dict[str, Any]]:
    for fname in ("docker-compose.yml", "docker-compose.yaml"):
        path = os.path.join(target, fname)
        if os.path.isfile(path):
            return _parse_compose_ports(path)
    return []


def _parse_compose_ports(compose_path: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    seen: set[int] = set()

    try:
        content = open(compose_path).read()
        # Match port mappings like "8000:8000" or "- 8000:8000" or "- '8000:8000'"
        for m in re.finditer(r"['\"]?(\d+):(\d+)['\"]?", content):
            host_port = int(m.group(1))
            if host_port in seen:
                continue
            seen.add(host_port)
            ports.append({
                "port": host_port,
                "service": PORT_SERVICE_MAP.get(host_port, f"unknown-{host_port}"),
                "process": None,
                "source": "docker-compose",
            })
    except OSError:
        pass

    return ports
