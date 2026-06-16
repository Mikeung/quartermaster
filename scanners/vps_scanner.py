"""
VPS-level runtime state scanner.

Collects the actual running state of the VPS — systemd services, listening
ports, Docker containers, nginx domains, active processes — and normalizes
this into a service inventory.

Read-only. No writes to disk, no network calls, no configuration changes.
Advisory output only.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Ports that are infrastructure, not application services
_INFRA_PORTS = {22, 53, 80, 443, 5432, 5433, 6379, 9200, 9300, 9600, 9650}

# Known scan targets so the inventory can mark coverage status
SCAN_TARGETS: list[str] = []  # injected by scheduled_scan


def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a shell command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout or ""
    except Exception as exc:
        logger.debug("vps_scanner: command failed %s: %s", cmd, exc)
        return ""


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _collect_systemd_services() -> list[dict[str, Any]]:
    """Return running systemd service units with basic metadata."""
    raw = _run(["systemctl", "list-units", "--type=service", "--state=running",
                "--no-pager", "--no-legend", "--plain"])
    services = []
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        unit = parts[0]
        description = " ".join(parts[4:]) if len(parts) > 4 else ""
        services.append({"unit": unit, "description": description})
    return services


def _collect_listening_ports() -> list[dict[str, Any]]:
    """Return TCP listening ports with process info."""
    raw = _run(["ss", "-tlnp"])
    ports = []
    for line in raw.splitlines():
        if not line.startswith("LISTEN"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[3]
        proc_field = parts[6] if len(parts) > 6 else ""

        # Parse address:port
        port_num = None
        if local.startswith("["):
            # IPv6
            m = re.search(r"\]:(\d+)$", local)
            if m:
                port_num = int(m.group(1))
        else:
            m = re.search(r":(\d+)$", local)
            if m:
                port_num = int(m.group(1))

        if port_num is None:
            continue

        # Parse process name from users:(...) field
        proc_name = ""
        pid = None
        m_proc = re.search(r'"([^"]+)".*?pid=(\d+)', proc_field)
        if m_proc:
            proc_name = m_proc.group(1)
            pid = int(m_proc.group(2))

        # Determine if localhost-only
        localhost_only = local.startswith("127.") or local.startswith("[::1]") or "127.0.0" in local

        ports.append({
            "port": port_num,
            "local_address": local,
            "localhost_only": localhost_only,
            "process": proc_name,
            "pid": pid,
        })
    return ports


def _collect_docker_containers() -> list[dict[str, Any]]:
    """Return running Docker containers with basic metadata."""
    raw = _run(["docker", "ps", "--format",
                '{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}",'
                '"status":"{{.Status}}","ports":"{{.Ports}}"}'], timeout=15)
    containers = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
            containers.append(c)
        except json.JSONDecodeError:
            pass
    return containers


def _collect_nginx_domains() -> list[dict[str, Any]]:
    """Parse nginx config for server_name → proxy_pass mappings."""
    raw = _run(["nginx", "-T", "-q"], timeout=10)
    mappings: list[dict[str, Any]] = []

    current_server: dict[str, Any] = {}
    in_server = 0

    for line in raw.splitlines():
        line = line.strip()

        if line == "server {":
            in_server += 1
            if in_server == 1:
                current_server = {"server_names": [], "proxy_targets": [], "roots": []}
            continue

        if line == "}" and in_server > 0:
            in_server -= 1
            if in_server == 0 and current_server.get("server_names"):
                mappings.append(current_server)
                current_server = {}
            continue

        if in_server == 1:
            if line.startswith("server_name"):
                names = line.replace("server_name", "").replace(";", "").split()
                current_server["server_names"].extend(n for n in names if n != "_")
            elif "proxy_pass" in line:
                m = re.search(r"proxy_pass\s+(\S+);", line)
                if m:
                    current_server["proxy_targets"].append(m.group(1))
            elif line.startswith("root "):
                m = re.search(r"root\s+(\S+);", line)
                if m:
                    current_server["roots"].append(m.group(1))

    return mappings


def _collect_active_processes() -> list[dict[str, Any]]:
    """Return notable processes (Python/Node/uvicorn/langgraph etc)."""
    raw = _run(["ps", "aux", "--no-headers"])
    procs = []
    patterns = re.compile(
        r"python|uvicorn|gunicorn|node|next-server|langgraph|fastapi", re.IGNORECASE
    )
    for line in raw.splitlines():
        if "[" in line[:20]:  # kernel threads
            continue
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        user, pid, cmd = parts[0], parts[1], parts[10]
        if patterns.search(cmd):
            procs.append({"user": user, "pid": pid, "cmd": cmd.strip()})
    return procs


def _get_proc_cwd(pid: int | str) -> str:
    try:
        import os
        return os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        return ""


def _get_unit_working_dir(unit: str) -> str:
    """Get WorkingDirectory from a systemd unit via systemctl show."""
    raw = _run(["systemctl", "show", unit, "--property=WorkingDirectory",
                "--property=User", "--no-pager"])
    cwd = ""
    user = ""
    for line in raw.splitlines():
        if line.startswith("WorkingDirectory="):
            cwd = line.split("=", 1)[1].strip()
        elif line.startswith("User="):
            user = line.split("=", 1)[1].strip()
    return cwd, user


# Ports that are dev tools / OS infra — exclude from orphan tracking
_NOISY_PORTS = _INFRA_PORTS | {27099, 36891, 54441, 64452, 9300, 9600, 9650}

# OS/infra units to skip entirely
_OS_UNITS = {
    "dbus.service", "atd.service", "cron.service", "ssh.service",
    "rsyslog.service", "fail2ban.service", "multipathd.service",
    "syslog.service", "systemd-journald.service", "systemd-logind.service",
    "systemd-networkd.service", "systemd-resolved.service",
    "systemd-timesyncd.service", "systemd-udevd.service",
    "polkit.service", "qemu-guest-agent.service",
    "getty@tty1.service", "serial-getty@ttyS0.service",
    "unattended-upgrades.service", "tailscaled.service",
    "postgresql@16-main.service", "containerd.service", "docker.service",
}

# Infrastructure docker images
_INFRA_IMAGES = ("redis", "postgres", "minio", "opensearch")


# ---------------------------------------------------------------------------
# Inventory builder
# ---------------------------------------------------------------------------

def _build_inventory(
    services: list[dict],
    ports: list[dict],
    containers: list[dict],
    domains: list[dict],
    procs: list[dict],
    scan_targets: list[str],
) -> list[dict[str, Any]]:
    """Normalize raw collections into service inventory entries."""

    # Map port → domain via nginx proxy_pass
    port_to_domain: dict[int, list[str]] = {}
    for mapping in domains:
        for target in mapping.get("proxy_targets", []):
            m = re.search(r":(\d+)", target)
            if m:
                p = int(m.group(1))
                port_to_domain.setdefault(p, []).extend(mapping["server_names"])

    # Map pid → cwd for all port processes
    pid_to_cwd: dict[int, str] = {}
    for port_entry in ports:
        pid = port_entry.get("pid")
        if pid and pid not in pid_to_cwd:
            pid_to_cwd[pid] = _get_proc_cwd(pid)

    # Map port → cwd via PID
    port_to_cwd: dict[int, str] = {}
    for port_entry in ports:
        pid = port_entry.get("pid")
        if pid:
            cwd = pid_to_cwd.get(pid, "")
            if cwd:
                port_to_cwd[port_entry["port"]] = cwd

    inventory: list[dict[str, Any]] = []

    # Build from systemd services
    for svc in services:
        unit = svc["unit"]
        if unit.startswith("user@") or unit in _OS_UNITS:
            continue

        name = unit.replace(".service", "")
        cwd, user = _get_unit_working_dir(unit)

        covered = bool(cwd) and any(cwd.startswith(t) for t in scan_targets)
        entry: dict[str, Any] = {
            "service_name": name,
            "systemd_unit": unit,
            "description": svc["description"],
            "process_supervisor": "systemd",
            "containerized": False,
            "user": user or None,
            "cwd": cwd or None,
            "exposed_ports": [],
            "domains": [],
            "scan_coverage": "covered" if covered else "unscanned",
            "flags": [],
        }
        inventory.append(entry)

    # Build from Docker containers (skip pure infra images)
    for c in containers:
        name = c.get("name", "")
        image = c.get("image", "")
        if any(x in image for x in _INFRA_IMAGES):
            continue
        inventory.append({
            "service_name": name,
            "systemd_unit": None,
            "description": f"Docker: {image}",
            "process_supervisor": "docker",
            "containerized": True,
            "user": None,
            "cwd": None,
            "exposed_ports": [],
            "domains": [],
            "scan_coverage": "unscanned",
            "flags": ["containerized"],
        })

    # Enrich: assign ports and domains to services via CWD matching
    app_ports = [p for p in ports if p["port"] not in _NOISY_PORTS]
    for port_entry in app_ports:
        port_num = port_entry["port"]
        port_cwd = port_to_cwd.get(port_num, "")
        domains_for_port = port_to_domain.get(port_num, [])

        # Match to an inventory entry by CWD prefix
        if port_cwd:
            for entry in inventory:
                entry_cwd = entry.get("cwd") or ""
                if entry_cwd and port_cwd.startswith(entry_cwd):
                    if port_num not in entry["exposed_ports"]:
                        entry["exposed_ports"].append(port_num)
                    for d in domains_for_port:
                        if d not in entry["domains"]:
                            entry["domains"].append(d)
                    break

    return inventory


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_vps_state(scan_targets: list[str] | None = None) -> dict[str, Any]:
    """Collect full VPS runtime state. Returns a structured snapshot dict."""
    targets = scan_targets or SCAN_TARGETS

    logger.info("VPS state collection starting")
    services = _collect_systemd_services()
    ports = _collect_listening_ports()
    containers = _collect_docker_containers()
    domains = _collect_nginx_domains()
    procs = _collect_active_processes()

    inventory = _build_inventory(services, ports, containers, domains, procs, targets)

    # Summary sets for drift comparison
    service_names = {s["unit"] for s in services}
    port_set = {p["port"] for p in ports}
    container_names = {c.get("name", "") for c in containers}
    domain_names = {n for m in domains for n in m.get("server_names", [])}

    unscanned = [e["service_name"] for e in inventory if e["scan_coverage"] == "unscanned"]
    containerized = [e["service_name"] for e in inventory if e.get("containerized")]

    state = {
        "services_raw": services,
        "ports_raw": ports,
        "containers_raw": containers,
        "domains_raw": domains,
        "inventory": inventory,
        # Sets for fast drift comparison
        "service_names": sorted(service_names),
        "port_set": sorted(port_set),
        "container_names": sorted(container_names),
        "domain_names": sorted(domain_names),
        # Coverage summary
        "unscanned_services": sorted(unscanned),
        "containerized_services": sorted(containerized),
    }

    logger.info(
        "VPS state collected: %d services, %d ports, %d containers, %d domains, "
        "%d unscanned services",
        len(services), len(ports), len(containers), len(domain_names), len(unscanned),
    )
    return state
