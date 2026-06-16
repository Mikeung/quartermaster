"""LLM meaning-layer drafter — step 2, the one non-deterministic bootstrap step.

The deterministic pass (cognition/meaning_proposer.py) filled what the facts
*mechanically* imply and left the rest unknown. This module reads that output
plus the graph facts/evidence and DRAFTS the residual unknowns:

  - owner_facing for every node where it is still unknown — judged from evidence
    (does this node produce something the OPERATOR cares about, or only internal
    telemetry?).
  - consequence for the consequence-less nodes — reasoned ONLY from the assembled
    facts ("no SEO metrics collected → SEO ranking goes unmonitored").
  - upgrades of mechanical "no {filepath}" skeletons into operational meaning.

This is a bounded, evidence-cited, schema-FILLING drafter — not a creative
consultant. It never invents dependencies or outputs not present in the facts; if
the facts don't support a conclusion it returns uncertain / cannot_determine.

CONTAINMENT (why this single non-deterministic step is safe):
  - It runs ON DEMAND, outside the runtime loop. The live system never calls it.
  - Every output is source="llm_draft", status="draft" — INERT. Nothing goes live
    until a human confirms it and copies it into config/operational_graph.yml.
  - It touches nothing confirmed and nothing in the DB. Read-only in; draft file out.
  - The model call is INJECTED (``llm_fn``) so this module is deterministic given a
    response and fully testable without a network or an API key. The only
    non-determinism is the injected call itself, which lives in the CLI runner.

Grounding scope: facts come strictly from the meaning layer + graph —
operational_graph.yml (liveness signal/detail/evidence, current values),
proposed_meaning.yml (derived produces / consequence skeletons), and the
graph_store edges touching the node (relationship + evidence). Prose project
profiles are deliberately out of scope to keep every draft traceable to the layer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

LLM_DRAFT_SOURCE = "llm_draft"
DRAFT_STATUS = "draft"

# A slot is open (draftable) when missing / empty / unknown.
_OPEN = {"", "unknown", "none", "null"}

# Allowed model verdicts, validated on parse.
_OWNER_VERDICTS = {"true", "false", "uncertain"}
_CONSEQUENCE_VERDICTS = {"determined", "cannot_determine"}

# LLM call signature: (system_prompt, user_prompt) -> parsed JSON dict.
LLMFn = Callable[[str, str], dict[str, Any]]


def _is_open(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _OPEN


def _norm(value: Any) -> str:
    """Collapse YAML block-scalar whitespace to a single line."""
    if value is None:
        return ""
    return " ".join(str(value).split())


# ---------------------------------------------------------------------------
# Assembled facts (the grounding bundle handed to the model, verbatim)
# ---------------------------------------------------------------------------

@dataclass
class NodeFacts:
    builder_node_id: str
    target_id: str
    liveness_signal: str = "unknown"
    liveness_detail: str = ""
    liveness_evidence: str = ""
    produces: str = ""              # derived produces, if any
    produces_evidence: str = ""
    consequence_skeleton: str = ""  # mechanical "no {path}" to upgrade, if any
    edges: list[str] = field(default_factory=list)  # human-readable edge facts
    needs_owner_facing: bool = False
    needs_consequence: bool = False
    consequence_is_upgrade: bool = False

    def fact_lines(self) -> list[str]:
        """The exact fact strings shown to the model and recorded for the human."""
        lines = [f"node id: {self.builder_node_id}", f"target: {self.target_id}"]
        if self.liveness_signal and self.liveness_signal != "unknown":
            lines.append(f"liveness signal: {self.liveness_signal}")
        if self.liveness_detail:
            lines.append(f"liveness detail: {self.liveness_detail}")
        if self.liveness_evidence:
            lines.append(f"liveness evidence: {self.liveness_evidence}")
        if self.produces:
            ev = f" (evidence: {self.produces_evidence})" if self.produces_evidence else ""
            lines.append(f"observed output (derived produces): {self.produces}{ev}")
        if self.consequence_skeleton:
            lines.append(f"mechanical consequence skeleton to upgrade: {self.consequence_skeleton}")
        for e in self.edges:
            lines.append(f"graph edge: {e}")
        return lines


# ---------------------------------------------------------------------------
# Draft outputs
# ---------------------------------------------------------------------------

@dataclass
class FieldDraft:
    field: str                 # "owner_facing" | "consequence"
    verdict: str               # owner: true/false/uncertain ; cons: determined/cannot_determine
    value: str                 # owner: "" ; consequence: the drafted line ("" if cannot_determine)
    confidence: float
    reasoning: str
    facts_used: list[str]
    source: str = LLM_DRAFT_SOURCE
    status: str = DRAFT_STATUS

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "verdict": self.verdict,
            "value": self.value,
            "source": self.source,
            "status": self.status,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "facts_used": self.facts_used,
        }


@dataclass
class NodeDraft:
    builder_node_id: str
    target_id: str
    facts_shown: list[str]
    drafts: list[FieldDraft] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.builder_node_id,
            "target": self.target_id,
            "facts_shown": self.facts_shown,
            "drafts": [d.to_dict() for d in self.drafts],
            "errors": self.errors,
        }


@dataclass
class DraftReport:
    model: str
    nodes: list[NodeDraft] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        owner = [d for n in self.nodes for d in n.drafts if d.field == "owner_facing"]
        cons = [d for n in self.nodes for d in n.drafts if d.field == "consequence"]
        return {
            "model": self.model,
            "nodes_drafted": sum(1 for n in self.nodes if n.drafts),
            "owner_facing_drafts": len(owner),
            "owner_facing_uncertain": sum(1 for d in owner if d.verdict == "uncertain"),
            "consequence_drafts": len(cons),
            "consequence_cannot_determine": sum(1 for d in cons if d.verdict == "cannot_determine"),
            "errors": sum(len(n.errors) for n in self.nodes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "nodes": [n.to_dict() for n in self.nodes]}


# ---------------------------------------------------------------------------
# Fact assembly
# ---------------------------------------------------------------------------

def assemble_facts(
    operational_graph: dict[str, Any],
    proposed_meaning: dict[str, Any],
    edges: list[dict[str, Any]],
    label_of: dict[str, str],
    rejection_keys: set[tuple[str, str]] | None = None,
) -> list[NodeFacts]:
    """Build per-node fact bundles and decide which fields each node needs.

    Confirmed slots (a real, non-unknown value in operational_graph.yml) are never
    drafted. owner_facing is needed when its value is open. consequence is needed
    when its value is open; if a derived skeleton exists for it, the draft is an
    upgrade rather than a fresh write.

    rejection_keys: (node_id, field) pairs the operator previously rejected. Those
    slots are NOT re-drafted (skipped before any LLM call) so a rejected draft is
    not re-proposed on the next run.
    """
    rejection_keys = rejection_keys or set()
    proposed_by_id: dict[str, dict[str, Any]] = {
        n.get("id"): n for n in (proposed_meaning.get("nodes") or [])
    }

    # Index edges by both endpoints, rendered as plain-language facts. The
    # port-attribution edges are a known cartesian-product artifact of the scanner
    # (every observed port attached to every repo) — feeding them would mislead the
    # model, so they are excluded. Operational (human_declared) and technology edges
    # carry real purpose signal and are kept.
    edge_lines_by_node: dict[str, list[str]] = {}
    for e in edges:
        if e.get("resolved_at"):
            continue
        rel = e.get("relationship", "?")
        src = label_of.get(e.get("source_node_id", ""), e.get("source_node_id", "?"))
        tgt = label_of.get(e.get("target_node_id", ""), e.get("target_node_id", "?"))
        if rel == "EXPOSES_PORT" or src.startswith("port:") or tgt.startswith("port:"):
            continue
        ev = _edge_evidence_str(e)
        line_out = f"{src} -[{rel}]-> {tgt}" + (f"  (evidence: {ev})" if ev else "")
        edge_lines_by_node.setdefault(src, []).append(line_out)
        if tgt != src:
            edge_lines_by_node.setdefault(tgt, []).append(line_out)

    out: list[NodeFacts] = []
    for node in operational_graph.get("nodes", []):
        nid = node.get("id", "")
        # A previously-rejected slot is not re-drafted (skipped before any LLM call).
        owner_open = _is_open(node.get("owner_facing")) and (nid, "owner_facing") not in rejection_keys
        cons_open = _is_open(node.get("consequence")) and (nid, "consequence") not in rejection_keys
        if not owner_open and not cons_open:
            continue  # fully confirmed, or both slots rejected — nothing to draft

        liveness = node.get("liveness") or {}
        nf = NodeFacts(
            builder_node_id=nid,
            target_id=_norm(node.get("target", "vps")),
            liveness_signal=_norm(liveness.get("signal", "unknown")),
            liveness_detail=_norm(liveness.get("detail", "")),
            liveness_evidence=_norm(liveness.get("evidence", "")),
            edges=sorted(set(edge_lines_by_node.get(nid, []))),
            needs_owner_facing=owner_open,
            needs_consequence=cons_open,
        )

        # Pull derived produces / consequence skeleton from the deterministic pass.
        prop = proposed_by_id.get(nid, {})
        proposals = prop.get("proposals", {}) if isinstance(prop, dict) else {}
        prod = proposals.get("produces")
        if isinstance(prod, dict):
            nf.produces = _norm(prod.get("value", ""))
            nf.produces_evidence = _norm(prod.get("evidence", ""))
        skel = proposals.get("consequence")
        if isinstance(skel, dict) and cons_open:
            nf.consequence_skeleton = _norm(skel.get("value", ""))
            nf.consequence_is_upgrade = True

        out.append(nf)

    return out


def _edge_evidence_str(edge: dict[str, Any]) -> str:
    ev = edge.get("evidence", [])
    parts: list[str] = []
    if isinstance(ev, list):
        for item in ev:
            if isinstance(item, dict):
                d = _norm(item.get("detail", ""))
                if d:
                    parts.append(d)
            elif item:
                parts.append(_norm(item))
    elif ev:
        parts.append(_norm(ev))
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a bounded schema-filling drafter for an operational-memory system. "
    "You DRAFT proposals a human will verify; you are NOT a creative consultant. "
    "Reason ONLY from the facts provided for the node. Never invent dependencies, "
    "outputs, owners, or behaviour that the facts do not state. Cite the exact fact "
    "strings you used.\n\n"
    "owner_facing — does the node produce something a human OPERATOR or end-user "
    "directly cares about?\n"
    "  true  = it delivers a product/website/dashboard, a delivered digest or "
    "report, or output a person consumes.\n"
    "  false = internal infrastructure or telemetry (a database, reverse proxy, an "
    "internal log/metrics file) whose value is only in keeping other systems "
    "running; its failure matters via cascade, not directly. A node whose only "
    "observed output is an internal log is almost always false.\n"
    "  uncertain = the facts do not say what it outputs or who consumes it.\n\n"
    "consequence — one line, 'if down → <operational capability or output lost, in "
    "human terms>'. Upgrade a mechanical file-path skeleton into the MEANING of "
    "losing that output (e.g. 'no /var/log/x-metrics.log' → 'no metrics collected → "
    "X goes unmonitored') ONLY if the facts tell you what the output means. If the "
    "facts do not support a meaning, set verdict='cannot_determine' and value=''.\n\n"
    "CALIBRATION — distinguish what the facts STATE from what a name SUGGESTS:\n"
    "  - A node's name (e.g. 'seo-agent') or its libraries (fastapi, an LLM SDK, a "
    "vector DB) tell you it is a service that uses an LLM — they do NOT tell you what "
    "it outputs or who consumes it. Inferring purpose from a name alone is a GUESS.\n"
    "  - 'a uvicorn service on port N' with no evidence of who consumes its output or "
    "what it serves does NOT establish owner_facing → return uncertain.\n"
    "  - Assert owner_facing true/false only when the facts name the output, the "
    "consumer, or the served product (e.g. a 'website' description, a named "
    "downstream reader, an internal-only log).\n"
    "  - Reserve confidence ≥ 0.8 for facts that EXPLICITLY state the output/consumer. "
    "Use ≤ 0.5 when reasoning from a name or technology alone, and prefer uncertain / "
    "cannot_determine over a confident guess.\n\n"
    "Return STRICT JSON only, matching the requested schema. confidence is 0.0-1.0 "
    "and must reflect how well the facts support the draft (thin facts -> low "
    "confidence or uncertain)."
)


def build_prompt(nf: NodeFacts) -> tuple[str, str]:
    """Return (system, user) prompts for one node, requesting only needed fields."""
    facts_block = "\n".join(f"- {line}" for line in nf.fact_lines())

    requested: list[str] = []
    schema_fields: list[str] = []
    if nf.needs_owner_facing:
        requested.append("owner_facing")
        schema_fields.append(
            '"owner_facing": {"verdict": "true|false|uncertain", "confidence": 0.0-1.0, '
            '"reasoning": "...", "facts_used": ["exact fact strings"]}'
        )
    if nf.needs_consequence:
        requested.append("consequence")
        verb = "UPGRADE the skeleton below into" if nf.consequence_is_upgrade else "DRAFT"
        schema_fields.append(
            '"consequence": {"verdict": "determined|cannot_determine", '
            '"value": "if down → ... (empty if cannot_determine)", "confidence": 0.0-1.0, '
            '"reasoning": "...", "facts_used": ["exact fact strings"]}'
        )
    else:
        verb = ""

    schema = "{\n  " + ",\n  ".join(schema_fields) + "\n}"

    user = (
        f"Facts for this node (your ONLY evidence):\n{facts_block}\n\n"
        f"Draft these field(s): {', '.join(requested)}.\n"
    )
    if nf.needs_consequence and nf.consequence_is_upgrade:
        user += (
            f"For consequence, {verb} a human-meaningful operational consequence, "
            "grounded in the facts.\n"
        )
    user += (
        "\nReturn STRICT JSON exactly in this shape (include only the requested "
        f"field keys):\n{schema}"
    )
    return _SYSTEM_PROMPT, user


# ---------------------------------------------------------------------------
# Response parsing + validation
# ---------------------------------------------------------------------------

def _clamp(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _as_fact_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if value:
        return [str(value)]
    return []


def parse_response(nf: NodeFacts, obj: dict[str, Any]) -> tuple[list[FieldDraft], list[str]]:
    """Validate the model's JSON into FieldDrafts. Returns (drafts, errors)."""
    drafts: list[FieldDraft] = []
    errors: list[str] = []

    if nf.needs_owner_facing:
        of = obj.get("owner_facing")
        if not isinstance(of, dict):
            errors.append("missing owner_facing object")
        else:
            verdict = str(of.get("verdict", "")).strip().lower()
            if verdict not in _OWNER_VERDICTS:
                errors.append(f"invalid owner_facing verdict: {verdict!r}")
            else:
                drafts.append(FieldDraft(
                    field="owner_facing",
                    verdict=verdict,
                    value="" if verdict == "uncertain" else verdict,
                    confidence=_clamp(of.get("confidence")),
                    reasoning=_norm(of.get("reasoning", "")),
                    facts_used=_as_fact_list(of.get("facts_used")),
                ))

    if nf.needs_consequence:
        c = obj.get("consequence")
        if not isinstance(c, dict):
            errors.append("missing consequence object")
        else:
            verdict = str(c.get("verdict", "")).strip().lower()
            if verdict not in _CONSEQUENCE_VERDICTS:
                errors.append(f"invalid consequence verdict: {verdict!r}")
            else:
                value = _norm(c.get("value", "")) if verdict == "determined" else ""
                if verdict == "determined" and not value:
                    errors.append("consequence determined but value empty")
                else:
                    drafts.append(FieldDraft(
                        field="consequence",
                        verdict=verdict,
                        value=value,
                        confidence=_clamp(c.get("confidence")),
                        reasoning=_norm(c.get("reasoning", "")),
                        facts_used=_as_fact_list(c.get("facts_used")),
                    ))

    return drafts, errors


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def draft(facts_list: list[NodeFacts], llm_fn: LLMFn, model: str) -> DraftReport:
    """Run the drafter over assembled facts using an injected LLM call.

    ``llm_fn(system, user) -> dict`` returns the model's parsed JSON. It is the
    ONLY non-deterministic input; everything else (assembly, prompting, parsing,
    validation) is deterministic and unit-testable with a fake llm_fn.
    """
    report = DraftReport(model=model)
    for nf in facts_list:
        nd = NodeDraft(
            builder_node_id=nf.builder_node_id,
            target_id=nf.target_id,
            facts_shown=nf.fact_lines(),
        )
        system, user = build_prompt(nf)
        try:
            obj = llm_fn(system, user)
        except Exception as exc:  # network / API / parse failure — isolate per node
            nd.errors.append(f"llm_fn failed: {exc}")
            report.nodes.append(nd)
            logger.warning("drafter llm_fn failed for %s: %s", nf.builder_node_id, exc)
            continue
        drafts, errors = parse_response(nf, obj)
        nd.drafts.extend(drafts)
        nd.errors.extend(errors)
        report.nodes.append(nd)
    return report
