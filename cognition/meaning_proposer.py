"""Deterministic meaning-layer proposer.

The meaning layer (per-node ``produces`` / ``consequence`` / ``owner_facing`` and
``liveness``) is hand-authored in ``config/operational_graph.yml`` and is mostly
``unknown``. This module proposes — deterministically, no LLM — only the entries
that the *observed facts already in graph_store* can support, and marks the rest
``unknown`` for the LLM/human pass that runs after it.

Design contract (mirrors consequence_walk / consequence_mapper):

  - DETERMINISTIC. Same nodes + edges + annotations in → byte-identical proposals
    out. The only inputs are the persisted graph (the scanner's observed facts);
    no clock, no randomness, no live-system probing.

  - EVIDENCE BEFORE ASSERTION. Every proposal carries source="derived",
    a ``derivation`` rule id, a ``confidence``, and the exact evidence string it
    was derived from. A proposal with no evidence is never emitted.

  - INERT. Every proposal is ``status="proposed"`` — never active. This module
    returns data; it writes nothing to graph_store and nothing to the YAML.
    The operator confirms proposals before they become meaning.

  - NEVER OVERWRITE / DOWNGRADE human work. A slot is only a candidate when it is
    *open* (missing, "", or "unknown"). A slot a human has confirmed to a real
    value is skipped and reported as untouched — never re-derived.

  - "unknown" IS A VALID RESULT. A sparse honest pass beats a full guessed one.
    Where the facts do not support a slot, it is left for the LLM/human pass.

Derivation rules (deterministic, first match wins per field):

  produces:
    P1 liveness_output_path   — liveness.signal == "output_path"; the node *is* an
                                output path. produces = that path.
    P2 cron_output_redirect   — liveness evidence for a cron/process job contains a
                                shell redirect ``>> /path`` / ``> /path``. The job
                                writes that file. produces = that path.
    P3 incoming_reads_from     — another node has a READS_FROM edge *into* this node:
                                a consumer observably reads from it, so it produces
                                what is read. produces = the read artifact, confidence
                                inherited from the edge. (SCANS / DEPENDS_ON /
                                TRIGGERS / USES_VENV are NOT producing relationships
                                and are deliberately excluded.)

  consequence:
    C1 templated_from_produces — ONLY where produces was derived:
                                "if down → no {produces}". No produces → no
                                consequence (left unknown, never guessed).

  liveness:
    L1 structural_liveness    — only for an *open* liveness slot: infer a signal from
                                co-located topology nodes (a docker node → process; a
                                uvicorn/fastapi framework node → service). Low
                                confidence; a cross-check, not a replacement. In
                                practice every declared node already has a
                                human-confirmed liveness signal, so this fires rarely.

  owner_facing:
    Never derived. Whether the operator *cares* about an output is a judgment the
    facts cannot make — always left for the LLM/human pass.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Slots that make up the meaning layer. owner_facing is intentionally never
# auto-derived (see module docstring).
MEANING_SLOTS: tuple[str, ...] = ("liveness", "produces", "consequence", "owner_facing")

# A node is in scope for proposing if it already carries one of these annotation
# types — i.e. it is an operator-declared meaning-layer node, not topology noise
# (port:* / framework:* / llm_provider:* nodes the scanner attaches in bulk).
_MEANING_ANNOTATION_TYPES: frozenset[str] = frozenset({"liveness", "consequence", "owner_facing"})

# Collector types that represent human authorship. A slot owned by one of these
# with a real (non-open) value is never re-derived or overwritten.
_HUMAN_COLLECTORS: frozenset[str] = frozenset({"human_declared", "human_confirmed"})

# Relationships whose *target* node produces something a consumer reads.
# Strictly data-flow consumption — being SCANNED (observed) or DEPENDED_ON is
# not the same as producing an output artifact, so those are excluded.
_PRODUCING_INBOUND_RELS: frozenset[str] = frozenset({"READS_FROM"})

DERIVED_SOURCE = "derived"
PROPOSED_STATUS = "proposed"

# Matches a shell output redirect to an absolute path: ">> /var/log/x.log",
# "> /tmp/out". Requires a leading "/" so we only capture real on-box artifacts,
# and stops at shell metacharacters so "2>&1" and pipes are not mistaken for paths.
_REDIRECT_RE = re.compile(r">>?\s*(/[^\s'\";|&)]+)")


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FieldProposal:
    """One inert, derived proposal for a single meaning-layer slot."""

    field: str
    value: str
    confidence: float
    derivation: str
    evidence: str
    source: str = DERIVED_SOURCE
    status: str = PROPOSED_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "derivation": self.derivation,
            "evidence": self.evidence,
        }


@dataclass
class NodeProposal:
    """All proposals (and what stays unknown) for one meaning-layer node."""

    builder_node_id: str
    target_id: str
    node_id: str
    proposals: list[FieldProposal] = field(default_factory=list)
    remaining_unknown: list[str] = field(default_factory=list)
    untouched_human: list[str] = field(default_factory=list)
    previously_rejected: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.builder_node_id,
            "target": self.target_id,
            "node_id": self.node_id,
            "proposals": [p.to_dict() for p in self.proposals],
            "remaining_unknown": self.remaining_unknown,
            "untouched_human": self.untouched_human,
            "previously_rejected": self.previously_rejected,
        }


@dataclass
class ProposalReport:
    """The full deterministic pass result over all meaning-layer nodes."""

    nodes: list[NodeProposal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "nodes": [n.to_dict() for n in self.nodes]}

    def summary(self) -> dict[str, Any]:
        by_field: dict[str, int] = {}
        for n in self.nodes:
            for p in n.proposals:
                by_field[p.field] = by_field.get(p.field, 0) + 1
        total_proposed = sum(by_field.values())
        nodes_with_proposal = sum(1 for n in self.nodes if n.proposals)
        return {
            "meaning_nodes": len(self.nodes),
            "nodes_with_proposal": nodes_with_proposal,
            "proposals_total": total_proposed,
            "proposals_by_field": by_field,
            "human_confirmed_untouched": sum(len(n.untouched_human) for n in self.nodes),
        }


# ---------------------------------------------------------------------------
# Slot-state helpers
# ---------------------------------------------------------------------------

def _is_open(value: Any) -> bool:
    """True when a slot is empty / unknown — i.e. fillable by a proposal."""
    if value is None:
        return True
    return str(value).strip().lower() in {"", "unknown", "none", "null"}


def _annotation(annotations: dict[str, Any], slot: str) -> dict[str, Any] | None:
    ann = annotations.get(slot)
    return ann if isinstance(ann, dict) else None


def _human_confirmed(annotations: dict[str, Any], slot: str) -> bool:
    """True when a human has set this slot to a real (non-open) value."""
    ann = _annotation(annotations, slot)
    if ann is None:
        return False
    if ann.get("collector_type") not in _HUMAN_COLLECTORS:
        return False
    return not _is_open(ann.get("value"))


def _liveness_fields(annotations: dict[str, Any]) -> tuple[str, str, str]:
    """Return (signal, detail, evidence) for the node's liveness annotation.

    The liveness *value* is a JSON blob {signal, detail, max_age_hours}; the
    artifact citation lives in the annotation's separate ``evidence`` column.
    """
    ann = _annotation(annotations, "liveness")
    if ann is None:
        return "unknown", "", ""
    signal, detail = "unknown", ""
    raw = ann.get("value", "")
    try:
        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            signal = str(parsed.get("signal", "unknown"))
            detail = str(parsed.get("detail", ""))
    except (json.JSONDecodeError, TypeError):
        pass
    return signal, detail, str(ann.get("evidence", ""))


# ---------------------------------------------------------------------------
# produces derivation
# ---------------------------------------------------------------------------

def _derive_produces(
    node: dict[str, Any],
    annotations: dict[str, Any],
    inbound_reads: list[dict[str, Any]],
    label_of: dict[str, str],
) -> FieldProposal | None:
    """Derive a produces proposal from observed facts, or None. First match wins."""
    signal, detail, ev = _liveness_fields(annotations)

    # P1 — the node IS an output path.
    if signal == "output_path" and detail:
        return FieldProposal(
            field="produces",
            value=detail,
            confidence=0.9,
            derivation="liveness_output_path",
            evidence=f"liveness.signal=output_path; detail: {detail}"
            + (f"; evidence: {ev}" if ev else ""),
        )

    # P2 — a cron/process job redirects stdout to an absolute path.
    if signal in {"cron", "process"} and ev:
        m = _REDIRECT_RE.search(ev)
        if m:
            path = m.group(1)
            return FieldProposal(
                field="produces",
                value=f"{path} (output file written by this {signal} job)",
                confidence=0.85,
                derivation="cron_output_redirect",
                evidence=f"liveness evidence contains redirect '{m.group(0).strip()}': {ev}",
            )

    # P3 — a consumer reads from this node, so it produces what is read.
    if inbound_reads:
        # Deterministic pick: lowest (source_label, relationship) pair.
        edge = sorted(
            inbound_reads,
            key=lambda e: (label_of.get(e.get("source_node_id", ""), ""), e.get("relationship", "")),
        )[0]
        consumer = label_of.get(edge.get("source_node_id", ""), "another node")
        rel = edge.get("relationship", "READS_FROM")
        conf = float(edge.get("confidence", 1.0))
        ev_detail = _edge_evidence_str(edge)
        return FieldProposal(
            field="produces",
            value=f"data read by {consumer} (via {rel})",
            confidence=conf,
            derivation="incoming_reads_from",
            evidence=f"inbound {rel} edge from {consumer}: {ev_detail}",
        )

    return None


def _edge_evidence_str(edge: dict[str, Any]) -> str:
    """Flatten an edge's evidence list into a single readable string."""
    ev = edge.get("evidence", [])
    parts: list[str] = []
    if isinstance(ev, list):
        for item in ev:
            if isinstance(item, dict):
                detail = str(item.get("detail", "")).strip()
                if detail:
                    parts.append(detail)
            elif item:
                parts.append(str(item))
    elif ev:
        parts.append(str(ev))
    return " | ".join(parts) if parts else "(no edge evidence)"


# ---------------------------------------------------------------------------
# consequence derivation
# ---------------------------------------------------------------------------

def _derive_consequence(produces: FieldProposal | None) -> FieldProposal | None:
    """Template a consequence ONLY where produces is known. No produces → None."""
    if produces is None:
        return None
    return FieldProposal(
        field="consequence",
        value=f"if down → no {produces.value}",
        confidence=produces.confidence,
        derivation="templated_from_produces",
        evidence=f"templated from derived produces ({produces.derivation}): {produces.value}",
    )


# ---------------------------------------------------------------------------
# liveness derivation (open slots only — a cross-check, not a replacement)
# ---------------------------------------------------------------------------

def _derive_liveness(
    node: dict[str, Any],
    target_topology_types: set[str],
) -> FieldProposal | None:
    """Infer a liveness signal for an OPEN slot from co-located topology nodes."""
    if "docker" in target_topology_types:
        signal, why = "process", "a docker node is active for this target"
    elif {"framework"} & target_topology_types:
        signal, why = "service", "a web-framework node (uvicorn/fastapi/etc.) is active for this target"
    else:
        return None
    return FieldProposal(
        field="liveness",
        value=json.dumps({"signal": signal, "detail": "unknown", "max_age_hours": "unknown"}),
        confidence=0.5,
        derivation="structural_liveness",
        evidence=f"topology: {why}",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def propose(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    annotations: dict[str, dict[str, Any]],
    rejection_keys: set[tuple[str, str]] | None = None,
) -> ProposalReport:
    """Run the deterministic meaning-layer proposal pass.

    Args:
        nodes:       active graph nodes (graph_store.get_active_nodes()).
        edges:       active graph edges (graph_store.get_active_edges()).
        annotations: node_id -> {annotation_type -> {value, evidence, collector_type, ...}}
                     (graph_store.get_all_annotations()).
        rejection_keys: (builder_node_id, field) pairs the operator previously
                     rejected. A rejected slot is not re-proposed; it is recorded
                     under previously_rejected instead — so review is never Groundhog
                     Day. Defaults to none.

    Returns a ProposalReport. Nodes are processed in a stable order so the output
    is byte-for-byte reproducible.
    """
    rejection_keys = rejection_keys or set()
    label_of: dict[str, str] = {n.get("node_id", ""): n.get("builder_node_id", "") for n in nodes}

    # Index inbound producing edges by target node.
    inbound_by_node: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        if e.get("relationship") in _PRODUCING_INBOUND_RELS and not e.get("resolved_at"):
            inbound_by_node.setdefault(e.get("target_node_id", ""), []).append(e)

    # Topology node types co-located on each target (for the liveness cross-check).
    topo_types_by_target: dict[str, set[str]] = {}
    for n in nodes:
        if n.get("collector_type") != "human_declared":
            topo_types_by_target.setdefault(n.get("target_id", ""), set()).add(n.get("node_type", ""))

    # Scope: only operator-declared meaning-layer nodes (those carrying a meaning
    # annotation). Stable sort by builder_node_id for deterministic output.
    meaning_nodes = [
        n for n in nodes
        if _MEANING_ANNOTATION_TYPES & set(annotations.get(n.get("node_id", ""), {}).keys())
    ]
    meaning_nodes.sort(key=lambda n: n.get("builder_node_id", ""))

    report = ProposalReport()

    for n in meaning_nodes:
        node_id = n.get("node_id", "")
        ann = annotations.get(node_id, {})
        np = NodeProposal(
            builder_node_id=n.get("builder_node_id", ""),
            target_id=n.get("target_id", ""),
            node_id=node_id,
        )

        # Record human-confirmed slots up front: these are never re-derived.
        for slot in MEANING_SLOTS:
            if _human_confirmed(ann, slot):
                np.untouched_human.append(slot)

        # --- produces ---
        produces: FieldProposal | None = None
        if "produces" in np.untouched_human:
            pass  # human already declared produces — never overwrite
        else:
            produces = _derive_produces(n, ann, inbound_by_node.get(node_id, []), label_of)
            if produces is not None:
                np.proposals.append(produces)

        # --- consequence (only from a derived produces, into an open slot) ---
        if "consequence" not in np.untouched_human and _is_open(
            _annotation(ann, "consequence").get("value") if _annotation(ann, "consequence") else None
        ):
            consequence = _derive_consequence(produces)
            if consequence is not None:
                np.proposals.append(consequence)

        # --- liveness (open slots only) ---
        if "liveness" not in np.untouched_human:
            live_ann = _annotation(ann, "liveness")
            live_open = live_ann is None or _is_open(_liveness_fields(ann)[0])
            if live_open:
                liveness = _derive_liveness(n, topo_types_by_target.get(n.get("target_id", ""), set()))
                if liveness is not None:
                    np.proposals.append(liveness)

        # --- drop previously-rejected slots: do not re-propose them ---
        if rejection_keys:
            kept: list[FieldProposal] = []
            for p in np.proposals:
                if (np.builder_node_id, p.field) in rejection_keys:
                    if p.field not in np.previously_rejected:
                        np.previously_rejected.append(p.field)
                else:
                    kept.append(p)
            np.proposals = kept

        # --- what remains unknown for the LLM/human pass ---
        proposed_fields = {p.field for p in np.proposals}
        for slot in MEANING_SLOTS:
            if slot in np.untouched_human:
                continue
            if (np.builder_node_id, slot) in rejection_keys:
                if slot not in np.previously_rejected:
                    np.previously_rejected.append(slot)
                continue  # rejected — operator chose to leave it unknown
            ann_slot = _annotation(ann, slot)
            slot_open = ann_slot is None or _is_open(
                _liveness_fields(ann)[0] if slot == "liveness" else ann_slot.get("value")
            )
            if slot_open and slot not in proposed_fields:
                np.remaining_unknown.append(slot)

        report.nodes.append(np)

    return report
