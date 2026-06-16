"""Meaning-layer confirmation — the human gate (step 3).

Steps 1 (deterministic proposer) and 2 (LLM drafter) produce INERT proposals and
drafts. Nothing they emit is active. This module is the operator's gate: it turns
those inert entries into a review surface, applies the operator's per-entry
decisions, and produces the promotions that go live — with provenance preserved and
every decision recorded in an append-only audit.

This module is PURE and DETERMINISTIC: it reads dicts (the parsed inert files +
operational_graph + the rejection ledger) and returns decisions/promotions. All I/O
— reading YAML, editing operational_graph.yml, running the loader, appending the
audit — lives in scripts/confirm_meaning_layer.py. That keeps promotion logic
testable and side-effect-free.

Decision model (per pending entry, exactly one):
  confirm  — accept the candidate value as-is
  edit     — correct the value, then accept
  reject   — discard; the slot stays unknown and is remembered so it is not
             re-proposed verbatim on the next generator/drafter run
  author   — type the value (for "can't determine" entries with no candidate)
  defer    — leave pending for a later batch

Provenance is preserved end-to-end so the audit always shows where a confirmed
value came from:
  derived   + confirm → derived->confirmed
  llm_draft + confirm → llm_draft->confirmed
  derived   + edit    → derived->edited->confirmed
  llm_draft + edit    → llm_draft->edited->confirmed
  author              → human_authored

Scope: the promotable meaning-layer slots are ``consequence`` and ``owner_facing``
(the two unknowns the generators fill, and the two non-liveness annotations the
loader activates). The deterministic ``produces`` field is surfaced as supporting
evidence for its consequence, not promoted as its own slot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Promotable meaning-layer slots (liveness is already human-confirmed; produces is
# supporting evidence, not its own slot).
PROMOTABLE_FIELDS: tuple[str, ...] = ("consequence", "owner_facing")

ACTIONS: frozenset[str] = frozenset({"confirm", "edit", "reject", "author", "defer"})

# Source ranking: an llm_draft ran on the deterministic output and may upgrade a
# derived skeleton, so it is the candidate of record when both exist for a slot.
_SOURCE_RANK = {"derived": 0, "llm_draft": 1}

_OPEN = {"", "unknown", "none", "null"}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _is_open_value(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _OPEN


# ---------------------------------------------------------------------------
# Confirmed-state detection
# ---------------------------------------------------------------------------

def is_confirmed(field_raw: Any) -> bool:
    """True when a node field in operational_graph.yml is already operator truth.

    Handles both legacy scalars (a non-unknown value, e.g. the hand-authored
    consequences) and structured confirmed blocks (a dict with status=confirmed).
    """
    if isinstance(field_raw, dict):
        status = str(field_raw.get("status", "")).strip().lower()
        if status == "confirmed":
            return True
        return not _is_open_value(field_raw.get("value"))
    return not _is_open_value(field_raw)


# ---------------------------------------------------------------------------
# Pending entry (the review surface)
# ---------------------------------------------------------------------------

@dataclass
class PendingEntry:
    node_id: str
    target: str
    field: str
    candidate_value: str          # "" for cannot_determine / uncertain drafts
    source: str                   # "derived" | "llm_draft"
    confidence: float
    verdict: str                  # draft verdict ("determined"/"cannot_determine"/...) or ""
    evidence: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.node_id, self.field)

    @property
    def needs_authoring(self) -> bool:
        """An empty candidate (the generator could not determine it) — confirm/edit
        do not apply; the operator must author or reject/defer."""
        return not self.candidate_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node_id,
            "field": self.field,
            "source": self.source,
            "confidence": round(self.confidence, 4),
            "verdict": self.verdict,
            "candidate_value": self.candidate_value,
            "needs_authoring": self.needs_authoring,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Assemble pending entries from the inert files
# ---------------------------------------------------------------------------

def _produces_by_node(proposed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for n in proposed.get("nodes") or []:
        prod = (n.get("proposals") or {}).get("produces")
        if isinstance(prod, dict):
            out[n.get("id")] = prod
    return out


def assemble_pending(
    proposed: dict[str, Any],
    drafted: dict[str, Any],
    operational_graph: dict[str, Any],
    rejection_keys: set[tuple[str, str]] | None = None,
) -> list[PendingEntry]:
    """Build the review surface: one entry per (node, field) still needing a decision.

    Excludes slots already confirmed (operator truth) and slots already rejected
    (so review never becomes Groundhog Day). When both a derived and an llm_draft
    candidate exist for a slot, the llm_draft wins and the derived skeleton is kept
    in the evidence trail.
    """
    rejection_keys = rejection_keys or set()

    # confirmed state + target, keyed by node id
    confirmed: dict[str, dict[str, Any]] = {}
    target_of: dict[str, str] = {}
    for n in operational_graph.get("nodes") or []:
        nid = n.get("id")
        target_of[nid] = _norm(n.get("target", "vps"))
        confirmed[nid] = {f: is_confirmed(n.get(f)) for f in PROMOTABLE_FIELDS}

    produces = _produces_by_node(proposed)

    # Gather raw candidates: {(node, field): {source: entry-dict}}
    raw: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    for n in proposed.get("nodes") or []:
        nid = n.get("id")
        cons = (n.get("proposals") or {}).get("consequence")
        if isinstance(cons, dict):
            raw.setdefault((nid, "consequence"), {})["derived"] = cons

    for n in drafted.get("nodes") or []:
        nid = n.get("id")
        for fld in PROMOTABLE_FIELDS:
            d = (n.get("drafts") or {}).get(fld)
            if isinstance(d, dict):
                raw.setdefault((nid, fld), {})["llm_draft"] = d

    out: list[PendingEntry] = []
    for (nid, fld), by_source in raw.items():
        if confirmed.get(nid, {}).get(fld):
            continue  # already operator truth
        if (nid, fld) in rejection_keys:
            continue  # already rejected — do not resurface
        # pick the highest-ranked source as the candidate of record
        source = max(by_source, key=lambda s: _SOURCE_RANK.get(s, -1))
        cand = by_source[source]
        entry = _build_entry(nid, target_of.get(nid, "vps"), fld, source, cand, by_source, produces)
        out.append(entry)

    out.sort(key=lambda e: (e.node_id, e.field))
    return out


def _build_entry(
    nid: str, target: str, fld: str, source: str,
    cand: dict[str, Any], by_source: dict[str, dict[str, Any]],
    produces: dict[str, dict[str, Any]],
) -> PendingEntry:
    value = _norm(cand.get("value", ""))
    verdict = _norm(cand.get("verdict", ""))
    confidence = float(cand.get("confidence", 0.0) or 0.0)

    evidence: list[str] = []
    # llm_draft reasoning + cited facts
    if source == "llm_draft":
        if cand.get("reasoning"):
            evidence.append(f"[reasoning] {_norm(cand['reasoning'])}")
        for f in cand.get("facts_used") or []:
            evidence.append(f"[fact] {_norm(f)}")
        # a derived skeleton that this draft upgraded, kept for lineage
        skel = by_source.get("derived")
        if isinstance(skel, dict) and skel.get("value"):
            evidence.append(f"[derived skeleton] {_norm(skel['value'])}")
    else:  # derived
        if cand.get("derivation"):
            evidence.append(f"[derivation] {_norm(cand['derivation'])}")
        if cand.get("evidence"):
            evidence.append(f"[evidence] {_norm(cand['evidence'])}")

    # supporting produces (the consequence is grounded in what the node outputs)
    if fld == "consequence" and nid in produces:
        p = produces[nid]
        evidence.append(f"[produces] {_norm(p.get('value', ''))} — {_norm(p.get('evidence', ''))}")

    return PendingEntry(
        node_id=nid, target=target, field=fld, candidate_value=value,
        source=source, confidence=confidence, verdict=verdict, evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Apply decisions
# ---------------------------------------------------------------------------

@dataclass
class Promotion:
    node_id: str
    target: str
    field: str
    value: str
    source: str           # provenance origin: derived | llm_draft | human_authored
    provenance: str       # full chain
    evidence: str         # summary written into operational_graph.yml + annotation
    confirmed_at: str


@dataclass
class Rejection:
    node_id: str
    field: str
    rejected_value: str
    source: str
    rejected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node_id, "field": self.field,
            "rejected_value": self.rejected_value, "source": self.source,
            "rejected_at": self.rejected_at,
        }


@dataclass
class AuditRecord:
    ts: str
    node_id: str
    field: str
    action: str
    source: str
    provenance: str
    value: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "node": self.node_id, "field": self.field,
            "action": self.action, "source": self.source, "provenance": self.provenance,
            "value": self.value, "note": self.note,
        }


@dataclass
class ConfirmationResult:
    promotions: list[Promotion] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    deferred: list[tuple[str, str]] = field(default_factory=list)
    audit: list[AuditRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "confirmed": sum(1 for a in self.audit if a.action in ("confirm", "edit", "author")),
            "promotions": len(self.promotions),
            "rejections": len(self.rejections),
            "deferred": len(self.deferred),
            "errors": len(self.errors),
        }


def _provenance(source: str, action: str) -> str:
    if action == "author":
        return "human_authored"
    if action == "edit":
        return f"{source}->edited->confirmed"
    return f"{source}->confirmed"


def _evidence_summary(entry: PendingEntry, provenance: str, now: str, note: str) -> str:
    parts = [f"confirmed {now} via {provenance}"]
    if entry.evidence:
        parts.append("basis: " + " | ".join(entry.evidence[:3]))
    if note:
        parts.append(f"note: {_norm(note)}")
    return "; ".join(parts)


def apply_decisions(
    pending: list[PendingEntry],
    decisions: list[dict[str, Any]],
    now: str,
) -> ConfirmationResult:
    """Deterministically turn operator decisions into promotions / rejections / audit.

    ``decisions`` is a list of {node, field, action, edited_value?, authored_value?,
    note?}. A decision with no matching pending entry, an unknown action, or a
    missing required value is recorded as an error and skipped — never guessed.
    """
    result = ConfirmationResult()
    by_key = {e.key: e for e in pending}

    for dec in decisions:
        nid = dec.get("node", "")
        fld = dec.get("field", "")
        action = str(dec.get("action", "")).strip().lower()
        note = _norm(dec.get("note", ""))
        key = (nid, fld)

        if not action or action == "defer":
            if key in by_key:
                result.deferred.append(key)
            continue
        if action not in ACTIONS:
            result.errors.append(f"{nid}/{fld}: unknown action {action!r}")
            continue

        entry = by_key.get(key)
        if entry is None:
            result.errors.append(f"{nid}/{fld}: no pending entry (already confirmed/rejected?)")
            continue

        if action == "confirm":
            if entry.needs_authoring:
                result.errors.append(
                    f"{nid}/{fld}: cannot confirm an empty ({entry.verdict or 'unknown'}) "
                    f"entry — use author")
                continue
            value, src = entry.candidate_value, entry.source
        elif action == "edit":
            value = _norm(dec.get("edited_value", ""))
            if not value:
                result.errors.append(f"{nid}/{fld}: edit requires a non-empty edited_value")
                continue
            src = entry.source
        elif action == "author":
            value = _norm(dec.get("authored_value", ""))
            if not value:
                result.errors.append(f"{nid}/{fld}: author requires a non-empty authored_value")
                continue
            src = "human_authored"
        elif action == "reject":
            result.rejections.append(Rejection(
                node_id=nid, field=fld, rejected_value=entry.candidate_value,
                source=entry.source, rejected_at=now))
            result.audit.append(AuditRecord(
                ts=now, node_id=nid, field=fld, action="reject", source=entry.source,
                provenance="rejected", value=entry.candidate_value, note=note))
            continue
        else:  # pragma: no cover — guarded above
            result.errors.append(f"{nid}/{fld}: unhandled action {action!r}")
            continue

        provenance = _provenance(src, action)
        evidence = _evidence_summary(entry, provenance, now, note)
        result.promotions.append(Promotion(
            node_id=nid, target=entry.target, field=fld, value=value,
            source=src, provenance=provenance, evidence=evidence, confirmed_at=now))
        result.audit.append(AuditRecord(
            ts=now, node_id=nid, field=fld, action=action, source=src,
            provenance=provenance, value=value, note=note))

    return result


# ---------------------------------------------------------------------------
# Rejection-ledger helpers (shared with the generators)
# ---------------------------------------------------------------------------

def rejection_keys_from_doc(doc: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Parse a rejection-ledger dict into a set of (node, field) keys.

    The generators (proposer / drafter) use this to skip previously-rejected slots
    so a rejected entry is not re-proposed on the next run.
    """
    keys: set[tuple[str, str]] = set()
    if not doc:
        return keys
    for r in doc.get("rejections") or []:
        node = r.get("node")
        fld = r.get("field")
        if node and fld:
            keys.add((node, fld))
    return keys
