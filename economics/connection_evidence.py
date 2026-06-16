"""On-box connection evidence — who is talking to a provider, right now.

Read-only. For an Unattributed spend bucket, the investigation needs to know
which on-box process was calling that provider when the spend happened. The raw
material is the host's own active outbound connections + the active process list
— observed, never inferred.

This is best-effort correlation, and the module is honest about that: provider
usage is typically day-granular while a connection snapshot is point-in-time, so
this narrows to CANDIDATES with a confidence, never a single fabricated owner.

It NEVER raises (subprocess wrapped) and changes nothing on the box.
"""

from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Known provider API hostnames. A remote IP is tagged to a provider when it
# resolves (forward DNS) to one of these hosts. Extend as providers are added.
PROVIDER_HOSTS: dict[str, tuple[str, ...]] = {
    "anthropic": ("api.anthropic.com",),
    "openai": ("api.openai.com",),
    "google": ("generativelanguage.googleapis.com", "aiplatform.googleapis.com"),
    "gemini": ("generativelanguage.googleapis.com",),
}

# Capture the peer addr:port immediately before the users:(("proc",pid=N,..)) tag.
# Anchored on `users:` so it works whether or not ss prints the State column
# (filtering with `state established` drops it). Handles IPv4 and bracketed IPv6.
_SS_LINE = re.compile(
    r"(?P<peer>\S+):(?P<port>\d+)\s+users:\(\(\"(?P<proc>[^\"]+)\",pid=(?P<pid>\d+)",
)


@dataclass(frozen=True)
class Connection:
    process: str
    pid: int
    remote_ip: str
    remote_port: int
    provider: str | None       # tagged when the IP resolves to a known provider host
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "process": self.process, "pid": self.pid,
            "remote_ip": self.remote_ip, "remote_port": self.remote_port,
            "provider": self.provider, "observed_at": self.observed_at,
        }


def _run_ss() -> str:
    """`ss -tnp` ESTABLISHED outbound connections. Empty string on any failure."""
    try:
        r = subprocess.run(
            ["ss", "-tnp", "state", "established"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _provider_ip_map(resolver: Any = socket.gethostbyname_ex) -> dict[str, str]:
    """Forward-resolve known provider hosts to a {ip: provider} map. Best-effort."""
    out: dict[str, str] = {}
    for provider, hosts in PROVIDER_HOSTS.items():
        for host in hosts:
            try:
                _, _, ips = resolver(host)
            except (OSError, ValueError):
                continue
            for ip in ips:
                out.setdefault(ip, provider)
    return out


def collect_outbound_connections(
    *,
    now: datetime | None = None,
    ss_output: str | None = None,
    ip_provider_map: dict[str, str] | None = None,
) -> list[Connection]:
    """Active outbound connections with process/pid, provider-tagged when known.

    Args are injectable for tests; defaults observe the live box. Never raises.
    """
    ts = (now or datetime.now(UTC)).isoformat()
    raw = ss_output if ss_output is not None else _run_ss()
    ip_map = ip_provider_map if ip_provider_map is not None else _provider_ip_map()

    conns: list[Connection] = []
    for line in raw.splitlines():
        m = _SS_LINE.search(line)
        if not m:
            continue
        ip = m.group("peer").strip("[]")
        conns.append(Connection(
            process=m.group("proc"),
            pid=int(m.group("pid")),
            remote_ip=ip,
            remote_port=int(m.group("port")),
            provider=ip_map.get(ip),
            observed_at=ts,
        ))
    return conns


def connections_to_provider(provider: str, conns: list[Connection]) -> list[Connection]:
    """Filter to connections tagged for one provider (alias-aware for google/gemini)."""
    provider = provider.lower()
    aliases = {provider}
    if provider in ("google", "gemini"):
        aliases |= {"google", "gemini"}
    return [c for c in conns if c.provider in aliases]
