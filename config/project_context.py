"""Project-context registry — the operational memory of *what each thing is*.

An incident report must be understandable by an operator who has forgotten the
project, the architecture, and the workflows. The hardest question to answer from
a finding's identity fields alone is:

    "What is this service, which project owns it, and why does it exist?"

That durable knowledge is authored once here and reused by every report.

This OSS build ships with EMPTY registries. Describe your own environment in
`config/projects.yml` (copy `config/projects.example.yml`) — it is loaded at
import time. Everything is deterministic and operator-editable; no LLM, no
probability. Unregistered subjects yield an explicit context-gap marker (itself
an operational signal), never a silent omission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Explicit markers — consistent with cognition.four_w.UNKNOWN. A value we cannot
# determine is surfaced, never dropped.
UNKNOWN = "UNKNOWN"
NOT_REGISTERED = "context not registered — add this project/service to config/projects.yml"

_CONFIG_PATH = Path(__file__).resolve().parent / "projects.yml"


@dataclass(frozen=True)
class ProjectContext:
    """Durable description of a project and its parts."""

    project: str                      # human project name
    purpose: str                      # what the project is for
    runtime: str = ""                 # primary runtime (python / node / ...)
    subsystems: dict[str, str] = field(default_factory=dict)   # name -> purpose
    services: dict[str, str] = field(default_factory=dict)     # name -> purpose


@dataclass(frozen=True)
class Ownership:
    project_id: str
    subsystem: str = ""
    service: str = ""
    confidence: str = "High"
    basis: str = "configured service ownership"


# ---------------------------------------------------------------------------
# Registries — loaded from config/projects.yml (operator-declared). Empty by
# default so a fresh install ships with no environment-specific data.
# ---------------------------------------------------------------------------

def _load() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _build_registry(doc: dict[str, Any]) -> dict[str, ProjectContext]:
    out: dict[str, ProjectContext] = {}
    for pid, raw in (doc.get("projects") or {}).items():
        raw = raw or {}
        out[str(pid)] = ProjectContext(
            project=str(raw.get("project") or pid),
            purpose=str(raw.get("purpose") or ""),
            runtime=str(raw.get("runtime") or ""),
            subsystems={str(k): str(v) for k, v in (raw.get("subsystems") or {}).items()},
            services={str(k): str(v) for k, v in (raw.get("services") or {}).items()},
        )
    return out


def _build_ownership(entries: dict[str, Any]) -> dict[str, Ownership]:
    out: dict[str, Ownership] = {}
    for name, raw in (entries or {}).items():
        raw = raw or {}
        out[str(name)] = Ownership(
            project_id=str(raw.get("project_id") or ""),
            subsystem=str(raw.get("subsystem") or ""),
            service=str(raw.get("service") or ""),
            confidence=str(raw.get("confidence") or "High"),
            basis=str(raw.get("basis") or "configured service ownership"),
        )
    return out


_DOC = _load()
PROJECT_CONTEXT_REGISTRY: dict[str, ProjectContext] = _build_registry(_DOC)
_PROJECT_ALIASES: dict[str, str] = {
    str(k): str(v) for k, v in (_DOC.get("aliases") or {}).items()
}
SERVICE_OWNERSHIP: dict[str, Ownership] = _build_ownership(_DOC.get("service_ownership") or {})
PORT_OWNERSHIP: dict[int, Ownership] = {
    int(k): v for k, v in _build_ownership(_DOC.get("port_ownership") or {}).items()
    if str(k).isdigit()
}
PROJECT_PATH_ROOTS: dict[str, str] = {
    str(k): str(v) for k, v in (_DOC.get("path_roots") or {}).items()
}


# ---------------------------------------------------------------------------
# Resolution (deterministic — unchanged regardless of how registries are loaded)
# ---------------------------------------------------------------------------

def canonical_project_id(pid: str | None) -> str | None:
    if not pid:
        return None
    pid = str(pid).strip().lower()
    if pid in PROJECT_CONTEXT_REGISTRY:
        return pid
    return _PROJECT_ALIASES.get(pid)


def _own_for(name: str | None) -> Ownership | None:
    if not name:
        return None
    n = str(name).strip().lower()
    if n in SERVICE_OWNERSHIP:
        return SERVICE_OWNERSHIP[n]
    if "/" in n:
        tail = n.rsplit("/", 1)[-1]
        if tail in SERVICE_OWNERSHIP:
            return SERVICE_OWNERSHIP[tail]
    return None


def _own_for_path(path: str | None) -> Ownership | None:
    """Attribute a filesystem path to the project whose directory tree contains it
    (longest-prefix match). Containment is reliable, so confidence is High."""
    if not path or "/" not in path:
        return None
    p = str(path).strip()
    best_root = ""
    best_pid = ""
    for root, pid in PROJECT_PATH_ROOTS.items():
        if (p == root or p.startswith(root + "/")) and len(root) > len(best_root):
            best_root, best_pid = root, pid
    if not best_root:
        return None
    return Ownership(
        project_id=best_pid, service=p,
        basis=f"path resides under the project directory {best_root}.",
    )


def _own_for_port(resource: str | None) -> Ownership | None:
    """Attribute a `port:<n>` resource (from a port_exposed_publicly finding)."""
    if not resource or "port:" not in str(resource):
        return None
    tail = str(resource).split("port:", 1)[-1].strip()
    digits = "".join(c for c in tail if c.isdigit())
    if not digits:
        return None
    return PORT_OWNERSHIP.get(int(digits))


@dataclass
class ResolvedContext:
    """A fully-populated, render-ready project-context block."""

    project: str
    project_purpose: str
    subsystem: str
    subsystem_purpose: str
    service: str
    service_purpose: str
    registered: bool                 # was the owning project found in the registry?
    inferred: bool = False           # was ownership inferred (not certain)?
    confidence: str = "High"
    basis: str = ""

    def as_pairs(self) -> list[tuple[str, str]]:
        return [
            ("Project", self.project),
            ("Project purpose", self.project_purpose),
            ("Subsystem", self.subsystem),
            ("Subsystem purpose", self.subsystem_purpose),
            ("Service", self.service),
            ("Service purpose", self.service_purpose),
        ]


def resolve_project_context(
    finding: dict[str, Any], four_w: dict[str, dict] | None = None
) -> ResolvedContext:
    """Resolve durable project context for a finding (deterministic).

    Resolution order for the owning project:
      1. SERVICE_OWNERSHIP on the resource/process/service name, then by containing
         project directory, then by known port.
      2. The finding's WHERE.repository / target_id.
    Unregistered subjects render an explicit marker rather than a blank.
    """
    four_w = four_w or {}
    where = (four_w.get("where") or {}) if isinstance(four_w, dict) else {}

    target = finding.get("target_id") or ""
    resource = finding.get("resource") or ""
    svc_candidate = where.get("service") or ""
    res_tail = resource.split(":", 1)[-1] if ":" in resource else resource

    own = (_own_for(svc_candidate) or _own_for(resource) or _own_for(res_tail)
           or _own_for(target if target != "vps" else None)
           or _own_for_path(resource) or _own_for_path(svc_candidate)
           or _own_for_port(resource))

    inferred = False
    confidence = "High"
    basis = ""
    if own is not None:
        project_id = own.project_id
        subsystem = own.subsystem or where.get("subsystem") or ""
        service = own.service or svc_candidate or res_tail or ""
        inferred = own.confidence != "High"
        confidence = own.confidence
        basis = own.basis
    else:
        project_id = canonical_project_id(where.get("repository")) or canonical_project_id(target) or ""
        subsystem = where.get("subsystem") or (res_tail if ":" in resource else "") or ""
        service = svc_candidate or res_tail or resource or ""

    ctx = PROJECT_CONTEXT_REGISTRY.get(canonical_project_id(project_id) or "")

    if ctx is None:
        proj_name = project_id or UNKNOWN
        return ResolvedContext(
            project=proj_name if project_id else UNKNOWN,
            project_purpose=NOT_REGISTERED,
            subsystem=subsystem or UNKNOWN,
            subsystem_purpose=NOT_REGISTERED if subsystem else UNKNOWN,
            service=service or UNKNOWN,
            service_purpose=NOT_REGISTERED if service else UNKNOWN,
            registered=False, inferred=inferred, confidence=confidence, basis=basis,
        )

    sub_purpose = ctx.subsystems.get(subsystem) if subsystem else ""
    if subsystem and not sub_purpose:
        sub_purpose = ctx.subsystems.get(subsystem.rsplit("/", 1)[-1], "")
    svc_purpose = ctx.services.get(service) if service else ""
    if service and not svc_purpose:
        svc_purpose = ctx.services.get(service.rsplit("/", 1)[-1], "")

    return ResolvedContext(
        project=ctx.project,
        project_purpose=ctx.purpose,
        subsystem=subsystem or "(project-level — no specific subsystem)",
        subsystem_purpose=sub_purpose or (
            "(not separately described)" if subsystem else "(project-level — no specific subsystem)"),
        service=service or "(no specific service/process named)",
        service_purpose=svc_purpose or (
            "(not separately described)" if service else "(no specific service/process named)"),
        registered=True, inferred=inferred, confidence=confidence, basis=basis,
    )
