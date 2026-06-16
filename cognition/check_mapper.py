"""Check mapper — the recommendations ("what to check") layer.

Sibling of `consequence_mapper`. Where the consequence mapper answers *what is
affected and what happens if this is ignored*, the check mapper answers the
complementary question: *what is the diagnostic next step?* — the deterministic
checklist the OOM episode showed we were missing.

Contract (identical discipline to consequence_mapper):
  - Opt-in: graph_store is None  -> return None (no augmentation).
  - Returns None (not an error) when the finding_type has no rule, or when no
    step survives evidence binding. An unmapped type yields NO recommendation;
    that is a valid outcome, never an invented one.
  - Never raises: every exception is caught and logged. A mapping failure must
    never break an incident report, a Telegram push, or the daily digest.
  - Deterministic: same playbook + same finding + same graph -> same steps.
  - Never fabricates: a step is emitted only if EVERY {placeholder} it references
    is bound from the finding or the graph. Missing value -> step skipped.

How it works:
  1. Look up the finding_type in config/check_playbook.yml (operator-editable).
  2. Bind placeholders from the finding's own fields ({service}/{unit}/{file}/
     {port}/{process}) and, via the graph, the finding's dependents ({dependents}
     — the labels of graph nodes that depend on this one). Reuses
     consequence_mapper.map_finding_to_node_id so findings bind to their graph
     node the same way everywhere.
  3. Emit each step whose placeholders are all bound, with its rationale and an
     evidence note.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory.graph_store import GraphStore

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PLAYBOOK_PATH = PROJECT_ROOT / "config" / "check_playbook.yml"

# Placeholders referenced in a step template, e.g. "{unit}" -> "unit".
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

# Module-level cache: the playbook is static config, parsed once.
_playbook_cache: dict[str, Any] | None = None


def load_playbook(path: Path | None = None) -> dict[str, Any]:
    """Load (and cache) the check playbook. Returns {} on any failure — a missing
    or malformed playbook degrades to 'no recommendations', never an exception."""
    global _playbook_cache
    if path is None and _playbook_cache is not None:
        return _playbook_cache
    target = path or _PLAYBOOK_PATH
    try:
        import yaml

        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        rules = data.get("rules", {}) if isinstance(data, dict) else {}
        if path is None:
            _playbook_cache = rules
        return rules
    except Exception as exc:
        logger.debug("check playbook load failed: %s", type(exc).__name__)
        return {}


# ---------------------------------------------------------------------------
# Evidence binding
# ---------------------------------------------------------------------------

def _normalize_service_name(resource: str) -> str:
    """Core service label from a resource string ('redis-server.service' ->
    'redis-server'). Empty for resources with no stable label (ports, paths)."""
    if not resource or resource.startswith("port:") or resource.startswith("/"):
        return ""
    name = re.sub(r"\.service$", "", resource.strip())
    name = re.sub(r"@[^@]*$", "", name)
    return name.strip()


def _dependent_labels(finding: dict[str, Any], graph_store: GraphStore) -> list[str]:
    """Labels of graph nodes that DEPEND ON this finding's node.

    Edges run dependent (source) -> dependency (target), so the dependents of the
    mapped node are the sources of edges whose target is the mapped node.
    Returns [] when the finding maps to no node or has no dependents.
    """
    from cognition.consequence_mapper import map_finding_to_node_id

    node_id = map_finding_to_node_id(finding, graph_store)
    if not node_id:
        return []
    edges = graph_store.get_active_edges()
    dependent_ids = [e["source_node_id"] for e in edges if e.get("target_node_id") == node_id]
    if not dependent_ids:
        return []
    id_to_label = {n["node_id"]: n["label"] for n in graph_store.get_active_nodes()}
    # Deterministic order: sorted, de-duplicated labels.
    labels = sorted({id_to_label.get(d, d) for d in dependent_ids})
    return labels


def _bindings(finding: dict[str, Any], graph_store: GraphStore) -> dict[str, str]:
    """Build the placeholder -> value map from the finding and the graph.

    Only values we can actually prove are bound; everything else stays absent so
    the step that needs it is skipped (never guessed)."""
    resource = str(finding.get("resource", "") or "")
    out: dict[str, str] = {}

    if resource.startswith("/"):
        out["file"] = resource
    elif resource.startswith("port:"):
        digits = "".join(c for c in resource if c.isdigit())
        if digits:
            out["port"] = digits
    elif resource.endswith(".service"):
        out["unit"] = resource

    svc = _normalize_service_name(resource)
    if svc:
        out["service"] = svc

    # {process}: kernel_oom_kill carries the killed process as `resource`.
    if finding.get("finding_type") == "kernel_oom_kill" and resource:
        out["process"] = resource

    deps = _dependent_labels(finding, graph_store)
    if deps:
        out["dependents"] = ", ".join(deps)

    return out


def _clean(text: str) -> str:
    """Collapse the YAML block-scalar's newlines/indentation into one line."""
    return " ".join(str(text).split())


def _subst(text: str, bindings: dict[str, str]) -> str:
    """Substitute only known {placeholder}s by targeted replacement.

    Deliberately NOT str.format: a check may legitimately contain literal braces
    (e.g. a docker inspect Go template `{{.Name}}`), which str.format would mangle.
    Replacing exact `{key}` tokens leaves all other braces untouched."""
    for key, value in bindings.items():
        text = text.replace("{" + key + "}", value)
    return text


def _bind_step(step: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any] | None:
    """Return a rendered step, or None if any referenced placeholder is unbound.

    Gating looks at check + why + evidence together: if a step's rationale
    references a value we cannot bind, the whole step is skipped (never guessed).
    `_PLACEHOLDER_RE` only matches `{word}`, so Go-template `{{.Name}}` braces are
    not treated as placeholders."""
    check = _clean(step.get("check", ""))
    if not check:
        return None
    why = _clean(step.get("why", ""))
    evidence_raw = step.get("evidence", "")
    evidence = _clean(evidence_raw) if isinstance(evidence_raw, str) else ""

    referenced = (
        set(_PLACEHOLDER_RE.findall(check))
        | set(_PLACEHOLDER_RE.findall(why))
        | set(_PLACEHOLDER_RE.findall(evidence))
    )
    if not referenced.issubset(bindings.keys()):
        return None  # an unbindable placeholder -> skip the step (never guess)

    return {
        "check": _subst(check, bindings),
        "why": _subst(why, bindings),
        "evidence": _subst(evidence, bindings),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_check_steps(
    finding: dict[str, Any],
    graph_store: GraphStore | None,
    *,
    playbook_path: Path | None = None,
) -> dict[str, Any] | None:
    """Return a 'what to check' block for a finding, or None.

    The block is pre-structured for the incident report, the Telegram alert and
    the daily digest so no caller has to know the playbook. All three treat None
    as 'no recommendation available'.

    Returns None when:
      - graph_store is None (opt-in; called without graph context)
      - the finding_type has no rule in the playbook
      - no step survives evidence binding
      - anything raises (caught internally)
    """
    if graph_store is None:
        return None
    try:
        ftype = finding.get("finding_type", "")
        rules = load_playbook(playbook_path)
        rule = rules.get(ftype)
        if not rule:
            return None  # unmapped type -> no recommendation (valid, not invented)

        bindings = _bindings(finding, graph_store)
        steps: list[dict[str, Any]] = []
        for raw in rule.get("steps", []):
            bound = _bind_step(raw, bindings)
            if bound is not None:
                steps.append(bound)

        if not steps:
            return None

        return {
            "finding_type": ftype,
            "note": _clean(rule.get("note", "")),
            "steps": steps,
        }
    except Exception as exc:
        logger.debug("get_check_steps error: %s", type(exc).__name__)
        return None
