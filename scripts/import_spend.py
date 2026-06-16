#!/usr/bin/env python3
"""Spend-ledger importer — observe-only ingestion of LLM/API spend.

Contract (intentionally minimal, so any producer can emit it without coupling):

    data/spend/*.jsonl    — one JSON object per line:
      {
        "timestamp": "2026-05-29T10:00:00+00:00",   # ISO 8601 (required)
        "provider":  "anthropic" | "openai" | "google" | "gemini" | ...,
        "model":     "claude-sonnet-4-20250514",
        "workflow":  "procurement_intel.drain_queue",
        "project_id":"lesia",
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "estimated_cost": 6.55,                       # USD (required for cost intel)
        "calls": 126,                                 # optional; recorded in metadata
        "success": true,
        "source": "PM/P7-COST-AUDIT-RESULTS.md"       # provenance (recommended)
      }

The importer is idempotent: each line is hashed and recorded in
data/spend_import_state.json, so re-running never double-counts. quartermaster never
writes back into producer projects — it only reads this drop directory.

Usage:  python -m scripts.import_spend            (import all new ledger lines)
        python -m scripts.import_spend --dry-run
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import observability_config as cfg  # noqa: E402
from memory.llm_store import LLMEventStore  # noqa: E402
from schemas.llm_event_schema import LLMEvent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_spend")

DB_PATH = PROJECT_ROOT / "data" / "operational_memory.db"
LEDGER_DIR = PROJECT_ROOT / "data" / cfg.SPEND_LEDGER_DIRNAME
STATE_PATH = PROJECT_ROOT / "data" / cfg.SPEND_IMPORT_STATE_FILE


def _line_hash(file_name: str, line: str) -> str:
    return hashlib.sha256(f"{file_name}\x1f{line.strip()}".encode()).hexdigest()


def _load_state() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text()).get("imported_hashes", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_state(hashes: set[str]) -> None:
    STATE_PATH.write_text(json.dumps({"imported_hashes": sorted(hashes)}, indent=0))


def _to_event(rec: dict) -> tuple[LLMEvent, str | None]:
    pt = int(rec.get("prompt_tokens", 0) or 0)
    ct = int(rec.get("completion_tokens", 0) or 0)
    tt = int(rec.get("total_tokens", 0) or (pt + ct))
    meta = {"source": str(rec.get("source", "spend_ledger"))[:256]}
    if "calls" in rec:
        meta["calls"] = str(rec["calls"])[:256]
    if "note" in rec:
        meta["note"] = str(rec["note"])[:256]
    event = LLMEvent(
        timestamp=str(rec["timestamp"]),
        provider=str(rec.get("provider", "unknown")),
        model=str(rec.get("model", "unknown")),
        workflow=str(rec.get("workflow", "unknown")),
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        latency_ms=float(rec.get("latency_ms", 0.0) or 0.0),
        success=bool(rec.get("success", True)),
        request_kind=str(rec.get("request_kind", "completion")),
        estimated_cost=float(rec["estimated_cost"]) if rec.get("estimated_cost") is not None else None,
        error_type=rec.get("error_type"),
        metadata=meta,
    )
    return event, rec.get("project_id")


def import_spend(dry_run: bool = False) -> dict:
    """Import all new ledger lines. Returns a summary dict."""
    if not LEDGER_DIR.exists():
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Created empty ledger dir: %s", LEDGER_DIR)
        return {"files": 0, "imported": 0, "skipped": 0, "cost": 0.0}

    seen = _load_state()
    files = sorted(LEDGER_DIR.glob("*.jsonl"))
    imported = skipped = 0
    cost = 0.0
    new_hashes: set[str] = set()

    store = None
    if not dry_run:
        store = LLMEventStore(str(DB_PATH))
        store.connect()

    try:
        for fp in files:
            for line in fp.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                h = _line_hash(fp.name, line)
                if h in seen:
                    skipped += 1
                    continue
                try:
                    rec = json.loads(line)
                    event, project_id = _to_event(rec)
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    log.warning("Skipping bad ledger line in %s: %s", fp.name, exc)
                    continue
                if not dry_run and store is not None:
                    store.append(event, project_id=project_id)
                imported += 1
                cost += event.estimated_cost or 0.0
                new_hashes.add(h)
    finally:
        if store is not None:
            store.disconnect()

    if not dry_run and new_hashes:
        _save_state(seen | new_hashes)

    summary = {
        "files": len(files),
        "imported": imported,
        "skipped": skipped,
        "cost": round(cost, 2),
        "dry_run": dry_run,
    }
    log.info("Spend import: %s", summary)
    return summary


def main() -> int:
    dry = "--dry-run" in sys.argv
    summary = import_spend(dry_run=dry)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
