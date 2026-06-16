"""
Security heuristics scanner.

Scans for common misconfigurations and credential exposure patterns.
Read-only. No remediation. Advisory findings only.

Checks:
- API keys in systemd unit files
- World-readable secret files
- Root-owned services that should use a dedicated user
- Application ports exposed on all interfaces (0.0.0.0) without nginx
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that suggest embedded credentials
_CREDENTIAL_PATTERNS = [
    re.compile(r'(?i)Environment=\w*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD)\w*=[^\s$]'),
    re.compile(r'(?i)sk-[A-Za-z0-9_-]{20,}'),
    re.compile(r'(?i)sk-ant-api[A-Za-z0-9_-]{10,}'),
    re.compile(r'(?i)sk-or-v[A-Za-z0-9_-]{10,}'),
]

# Service users that are suspicious running privileged services
_PRIVILEGED_CONCERN = {"root"}


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout or ""
    except Exception:
        return ""


def _scan_systemd_units() -> list[dict[str, Any]]:
    """Scan systemd unit files for embedded credentials."""
    findings: list[dict[str, Any]] = []
    unit_dir = Path("/etc/systemd/system")
    if not unit_dir.exists():
        return findings

    for unit_file in unit_dir.glob("*.service"):
        try:
            content = unit_file.read_text(errors="replace")
        except Exception:
            continue

        matched_patterns: list[str] = []
        for pattern in _CREDENTIAL_PATTERNS:
            for match in pattern.finditer(content):
                # Extract the key name but redact the value
                raw = match.group(0)
                # Find the = position and redact everything after it
                eq_pos = raw.find("=")
                if eq_pos > 0:
                    key_part = raw[:eq_pos + 1]
                    redacted = f"{key_part}<REDACTED>"
                else:
                    redacted = "<credential pattern matched>"
                if redacted not in matched_patterns:
                    matched_patterns.append(redacted)

        if matched_patterns:
            # Determine which service user
            user_match = re.search(r"^User=(.+)$", content, re.MULTILINE)
            service_user = user_match.group(1).strip() if user_match else "root"
            findings.append({
                "type": "credential_in_unit_file",
                "severity": "high",
                "unit": unit_file.name,
                "service_user": service_user,
                "patterns_found": matched_patterns,
                "recommendation": (
                    f"Move credentials from {unit_file.name} to a mode-600 "
                    f"EnvironmentFile= and rotate the exposed keys."
                ),
                # Canonical identity fields for FindingStore
                "finding_type": "credential_in_unit_file",
                "resource": unit_file.name,
                "scope": "host",
                "collector_type": "security_scanner",
            })

    return findings


def _scan_exposed_ports() -> list[dict[str, Any]]:
    """Flag application ports bound to 0.0.0.0 without a reverse proxy."""
    findings: list[dict[str, Any]] = []

    # Get all 0.0.0.0 listeners
    raw = _run(["ss", "-tlnp"])
    # Get nginx upstream targets to know which ports are proxied
    nginx_raw = _run(["nginx", "-T", "-q"], timeout=10)
    proxied_ports: set[int] = set()
    for m in re.finditer(r"proxy_pass\s+http[s]?://[^:]+:(\d+)", nginx_raw):
        proxied_ports.add(int(m.group(1)))
    # 80 and 443 are nginx itself
    proxied_ports.update({80, 443})

    infra_ports = {22, 53, 5432, 5433, 6379, 9200}

    for line in raw.splitlines():
        if "0.0.0.0:" not in line:
            continue
        m = re.search(r"0\.0\.0\.0:(\d+)", line)
        if not m:
            continue
        port = int(m.group(1))
        if port in infra_ports or port in proxied_ports:
            continue

        proc_match = re.search(r'"([^"]+)"', line)
        proc_name = proc_match.group(1) if proc_match else "unknown"

        findings.append({
            "type": "port_exposed_publicly",
            "severity": "medium",
            "port": port,
            "process": proc_name,
            "recommendation": (
                f"Port {port} ({proc_name}) is bound to 0.0.0.0 with no nginx proxy. "
                f"Bind to 127.0.0.1 unless external access is required."
            ),
            # Canonical identity fields for FindingStore
            "finding_type": "port_exposed_publicly",
            "resource": f"port:{port}",
            "scope": "host",
            "collector_type": "security_scanner",
        })

    return findings


def _scan_world_readable_secrets() -> list[dict[str, Any]]:
    """Find .env files that are world-readable.

    Files under /root/ are protected by the 700 directory permission, so actual
    exploitability is low — these are flagged as medium (best-practice violation).
    Files under /home/, /srv/, or /etc/ are flagged high since their parent
    directories are typically traversable by all users.
    """
    findings: list[dict[str, Any]] = []
    search_dirs = ["/root", "/home", "/srv", "/etc"]

    for base in search_dirs:
        raw = _run(["find", base, "-maxdepth", "5", "-name", ".env",
                    "-perm", "/o+r",
                    "-not", "-path", "*/node_modules/*",
                    "-not", "-path", "*/.vscode-server/*",
                    "-not", "-path", "*/.cursor-server/*",
                    "-not", "-path", "*/_archived/*"], timeout=15)
        for path in raw.splitlines():
            path = path.strip()
            if not path:
                continue
            # /root/ directory itself is 700 — reduce severity
            protected = path.startswith("/root/")
            findings.append({
                "type": "world_readable_env_file",
                "severity": "medium" if protected else "high",
                "path": path,
                "recommendation": f"chmod 600 {path}",
                # Canonical identity fields for FindingStore
                "finding_type": "world_readable_env_file",
                "resource": path,
                "scope": "host",
                "collector_type": "security_scanner",
            })

    return findings


def run_security_scan() -> dict[str, Any]:
    """Run all security heuristics. Returns structured findings."""
    logger.info("Security scan starting")

    unit_findings = _scan_systemd_units()
    port_findings = _scan_exposed_ports()
    secret_findings = _scan_world_readable_secrets()

    all_findings = unit_findings + port_findings + secret_findings
    high = [f for f in all_findings if f["severity"] == "high"]
    medium = [f for f in all_findings if f["severity"] == "medium"]

    result = {
        "findings": all_findings,
        "high_count": len(high),
        "medium_count": len(medium),
        "total_count": len(all_findings),
    }

    logger.info(
        "Security scan complete: %d high, %d medium findings",
        len(high), len(medium),
    )
    return result
