#!/usr/bin/env python3
"""Meaning-layer confirmation gate (step 3) — turn inert proposals/drafts into
operator-confirmed, active truth.

Steps 1 (deterministic proposer) and 2 (LLM drafter) emit INERT entries in
config/proposed_meaning.yml and config/drafted_meaning.yml. This is the human gate:
review each pending entry against its evidence, decide, and promote the accepted
ones into config/operational_graph.yml as confirmed (active) truth.

Two interchangeable interfaces (same semantics, both terminal/file):

  review       Write/refresh config/meaning_decisions.yml — one review surface per
               pending entry (value + source + confidence + evidence). The operator
               edits each `decision:` (confirm/edit/reject/author/defer), then runs
               apply. Resumable: existing decisions are preserved across re-runs.

  apply        Read the decisions file, promote accepted entries into
               operational_graph.yml (with provenance), record rejections, append the
               audit, and run the loader so confirmed entries go live in graph_store.

  interactive  Walk pending entries one at a time in the terminal, decide inline,
               then apply. (Reads decisions from stdin; same promotion path as apply.)

  status       Show counts of pending / confirmed / rejected.

Guarantees: advisory-only; promotion logic is deterministic; evidence is shown at
decision time; every decision is appended to an append-only audit; confirmed entries
become human_declared annotations (protected by the lifecycle invariant); rejected
entries are remembered so they are not re-proposed. The scanner, findings, and
notifications are never touched.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import yaml  # noqa: E402

from cognition.meaning_confirmation import (  # noqa: E402
    PendingEntry,
    Promotion,
    apply_decisions,
    assemble_pending,
    rejection_keys_from_doc,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("confirm_meaning_layer")

_OPERATIONAL_GRAPH = PROJECT_ROOT / "config" / "operational_graph.yml"
_PROPOSED = PROJECT_ROOT / "config" / "proposed_meaning.yml"
_DRAFTED = PROJECT_ROOT / "config" / "drafted_meaning.yml"
_DECISIONS = PROJECT_ROOT / "config" / "meaning_decisions.yml"
_REJECTIONS = PROJECT_ROOT / "config" / "meaning_rejections.yml"
_AUDIT = PROJECT_ROOT / "reports" / "meaning_layer" / "confirmation_audit.jsonl"

_DECISIONS_HEADER = (
    "# Meaning-layer DECISIONS — edit each `decision:` then run:\n"
    "#   python scripts/confirm_meaning_layer.py apply\n"
    "# actions: confirm | edit | reject | author | defer\n"
    "#   confirm  accept candidate_value as-is\n"
    "#   edit     set edited_value, then it is accepted\n"
    "#   author   set authored_value (for needs_authoring: true entries)\n"
    "#   reject   discard; slot stays unknown and is not re-proposed\n"
    "#   defer    leave pending (blank = defer)\n"
    "# Nothing is promoted without an explicit decision. Resumable: re-run review\n"
    "# any time; your decisions here are preserved.\n"
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _now_date() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _now_ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Pending assembly
# ---------------------------------------------------------------------------

def _pending() -> list[PendingEntry]:
    proposed = _load_yaml(_PROPOSED)
    drafted = _load_yaml(_DRAFTED)
    og = _load_yaml(_OPERATIONAL_GRAPH)
    rejection_keys = rejection_keys_from_doc(_load_yaml(_REJECTIONS))
    return assemble_pending(proposed, drafted, og, rejection_keys)


# ---------------------------------------------------------------------------
# review — write the decisions file (preserving existing decisions)
# ---------------------------------------------------------------------------

def cmd_review() -> None:
    pending = _pending()

    # preserve any decisions the operator already recorded
    prior: dict[tuple[str, str], dict[str, Any]] = {}
    existing = _load_yaml(_DECISIONS)
    for e in existing.get("entries") or []:
        prior[(e.get("node"), e.get("field"))] = e

    entries_out = []
    for p in pending:
        prev = prior.get(p.key, {})
        entries_out.append({
            "node": p.node_id,
            "field": p.field,
            "source": p.source,
            "confidence": round(p.confidence, 4),
            "verdict": p.verdict,
            "needs_authoring": p.needs_authoring,
            "candidate_value": p.candidate_value,
            "evidence": p.evidence,
            "decision": prev.get("decision", ""),
            "edited_value": prev.get("edited_value", ""),
            "authored_value": prev.get("authored_value", ""),
            "note": prev.get("note", ""),
        })

    doc = {
        "version": "1",
        "generated_at": _now_ts(),
        "pending_count": len(entries_out),
        "entries": entries_out,
    }
    with _DECISIONS.open("w", encoding="utf-8") as f:
        f.write(_DECISIONS_HEADER)
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
    log.info("Wrote %s — %d pending entr%s to decide",
             _DECISIONS.relative_to(PROJECT_ROOT), len(entries_out),
             "y" if len(entries_out) == 1 else "ies")
    if not entries_out:
        log.info("Nothing pending — all generated entries are confirmed or rejected.")


# ---------------------------------------------------------------------------
# operational_graph.yml promotion — targeted, comment-preserving line replacement
# ---------------------------------------------------------------------------

def _confirmed_block(field: str, prom: Promotion) -> str:
    """Render a confirmed block for a node field, indented to sit under a node."""
    body = yaml.safe_dump(
        {field: {
            "value": prom.value,
            "status": "confirmed",
            "source": prom.source,
            "provenance": prom.provenance,
            "confirmed_at": prom.confirmed_at,
            "evidence": prom.evidence,
        }},
        sort_keys=False, default_flow_style=False, allow_unicode=True,
    )
    return "".join("    " + line if line.strip() else line for line in body.splitlines(keepends=True))


def _promote_into_graph(text: str, prom: Promotion) -> str:
    """Replace the node's scalar field line with a confirmed block. Preserves the
    rest of the file (comments, block scalars, the TODO section). Raises on anything
    ambiguous so a hand-curated file is never silently corrupted."""
    lines = text.splitlines(keepends=True)
    # locate the node block
    node_re = re.compile(rf"^\s*-\s*id:\s*{re.escape(prom.node_id)}\s*$")
    start = next((i for i, ln in enumerate(lines) if node_re.match(ln)), None)
    if start is None:
        raise ValueError(f"node not found in operational_graph.yml: {prom.node_id}")
    # block ends at next list item / top-level key
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*-\s*id:\s", lines[j]) or re.match(r"^[A-Za-z#]", lines[j]):
            end = j
            break
    field_re = re.compile(rf"^(    ){re.escape(prom.field)}:\s*(.*)$")
    matches = [i for i in range(start, end) if field_re.match(lines[i])]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one '{prom.field}:' line for {prom.node_id}, "
            f"found {len(matches)} (block scalar / already-confirmed?) — not editing")
    idx = matches[0]
    rest = field_re.match(lines[idx]).group(2).strip()
    if rest in ("|", ">", "|-", ">-", "|+", ">+") or rest.startswith(("{", "[")):
        raise ValueError(
            f"{prom.node_id}/{prom.field}: existing value is a block/flow collection "
            f"({rest!r}) — refusing to overwrite a non-scalar")
    lines[idx] = _confirmed_block(prom.field, prom)
    return "".join(lines)


# ---------------------------------------------------------------------------
# apply — promote, record rejections, append audit, run loader
# ---------------------------------------------------------------------------

def _append_rejections(rejections) -> None:
    doc = _load_yaml(_REJECTIONS)
    existing = doc.get("rejections") or []
    seen = {(r.get("node"), r.get("field")) for r in existing}
    for r in rejections:
        if (r.node_id, r.field) not in seen:
            existing.append(r.to_dict())
            seen.add((r.node_id, r.field))
    out = {
        "version": "1",
        "note": "Rejected meaning-layer entries — generators skip these so they are "
                "not re-proposed. Remove an entry to allow it to be proposed again.",
        "rejections": existing,
    }
    _REJECTIONS.write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
                           encoding="utf-8")


def _append_audit(records) -> None:
    _AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with _AUDIT.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")


def _apply_core(decisions: list[dict[str, Any]], skip_reload: bool = False) -> None:
    pending = _pending()
    result = apply_decisions(pending, decisions, now=_now_date())

    for err in result.errors:
        log.warning("decision error: %s", err)

    # 1) promote accepted entries into operational_graph.yml (comment-preserving)
    if result.promotions:
        text = _OPERATIONAL_GRAPH.read_text(encoding="utf-8")
        _OPERATIONAL_GRAPH.with_suffix(".yml.bak").write_text(text, encoding="utf-8")
        for prom in result.promotions:
            text = _promote_into_graph(text, prom)
            log.info("promoted %s/%s (%s): %s", prom.node_id, prom.field,
                     prom.provenance, prom.value[:60])
        _OPERATIONAL_GRAPH.write_text(text, encoding="utf-8")

    # 2) remember rejections so the generators don't re-propose them
    if result.rejections:
        _append_rejections(result.rejections)
        for r in result.rejections:
            log.info("rejected %s/%s (remembered)", r.node_id, r.field)

    # 3) append-only audit of every decision applied
    if result.audit:
        _append_audit(result.audit)

    s = result.summary()
    log.info("apply: confirmed=%d promotions=%d rejections=%d deferred=%d errors=%d",
             s["confirmed"], s["promotions"], s["rejections"], s["deferred"], s["errors"])

    # 4) run the loader so confirmed entries go live in graph_store
    if result.promotions and not skip_reload:
        from scripts.load_operational_graph import load as load_graph
        log.info("reloading operational_graph.yml into graph_store ...")
        load_graph(dry_run=False)


def cmd_apply() -> None:
    doc = _load_yaml(_DECISIONS)
    entries = doc.get("entries") or []
    if not entries:
        log.warning("no decisions file (%s). Run `review` first.",
                    _DECISIONS.relative_to(PROJECT_ROOT))
        return
    # the decisions file exposes `decision:` to the operator; the core uses `action`
    decisions = [
        {"node": e.get("node"), "field": e.get("field"),
         "action": e.get("decision", ""),
         "edited_value": e.get("edited_value", ""),
         "authored_value": e.get("authored_value", ""),
         "note": e.get("note", "")}
        for e in entries
    ]
    _apply_core(decisions)


# ---------------------------------------------------------------------------
# interactive — terminal walk-through
# ---------------------------------------------------------------------------

def _print_surface(p: PendingEntry, i: int, total: int) -> None:
    print("\n" + "=" * 72)
    print(f"[{i}/{total}]  {p.node_id}  ·  {p.field}  ·  target {p.target}")
    print(f"  source: {p.source}   confidence: {p.confidence:.2f}"
          + (f"   verdict: {p.verdict}" if p.verdict else ""))
    if p.candidate_value:
        print(f"  candidate value: {p.candidate_value}")
    else:
        print("  candidate value: (none — generator could not determine; author or reject)")
    print("  evidence:")
    for ev in p.evidence:
        print(f"    - {ev}")
    print("-" * 72)


def cmd_interactive() -> None:
    pending = _pending()
    if not pending:
        log.info("Nothing pending.")
        return
    decisions: list[dict[str, Any]] = []
    total = len(pending)
    print(f"{total} pending entr{'y' if total == 1 else 'ies'}. "
          "Actions: [c]onfirm [e]dit [r]eject [a]uthor [d]efer [q]uit")
    for i, p in enumerate(pending, 1):
        _print_surface(p, i, total)
        choice = input("  decision [c/e/r/a/d/q]: ").strip().lower()
        if choice in ("q", "quit"):
            break
        dec: dict[str, Any] = {"node": p.node_id, "field": p.field}
        if choice in ("c", "confirm"):
            dec["action"] = "confirm"
        elif choice in ("e", "edit"):
            dec["action"] = "edit"
            dec["edited_value"] = input("  edited value: ").strip()
        elif choice in ("a", "author"):
            dec["action"] = "author"
            dec["authored_value"] = input("  authored value: ").strip()
        elif choice in ("r", "reject"):
            dec["action"] = "reject"
        else:
            dec["action"] = "defer"
        decisions.append(dec)
    _apply_core(decisions)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    pending = _pending()
    rejections = (_load_yaml(_REJECTIONS).get("rejections") or [])
    og = _load_yaml(_OPERATIONAL_GRAPH)
    confirmed = 0
    for n in og.get("nodes") or []:
        for fld in ("consequence", "owner_facing"):
            raw = n.get(fld)
            if isinstance(raw, dict) and str(raw.get("status", "")).lower() == "confirmed":
                confirmed += 1
    log.info("pending=%d  confirmed(blocks)=%d  rejected=%d", len(pending), confirmed, len(rejections))
    for p in pending:
        print(f"  PENDING  {p.node_id:<26} {p.field:<13} [{p.source}] "
              f"{'(needs author)' if p.needs_authoring else p.candidate_value[:50]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("review", help="write/refresh the decisions file")
    sub.add_parser("apply", help="apply decisions: promote, record, reload")
    sub.add_parser("interactive", help="walk pending entries in the terminal")
    sub.add_parser("status", help="show pending / confirmed / rejected counts")
    args = parser.parse_args()

    {"review": cmd_review, "apply": cmd_apply,
     "interactive": cmd_interactive, "status": cmd_status}[args.command]()


if __name__ == "__main__":
    main()
