"""Incident index builders — `index.md` and `open_incidents.md`.

These two files let an operator navigate the whole incident history without
reading every report. They are rebuilt **deterministically** from the
machine-readable metadata header embedded at the top of each incident report
(see `reports.incident_report.parse_incident_metadata`) — no database is
consulted, so the indexes regenerate from the committed artifacts alone. This is
consistent with "git is the system of record": the reports ARE the source.

- `reports/incidents/index.md` — every filed incident, newest first.
- `reports/incidents/open_incidents.md` — the subset whose status is `open`.

Status is `open` at write time. Callers that know which findings are still
active (e.g. the scan, via FindingStore) may pass `active_finding_ids`; any
incident whose finding_id is NOT in that set is rendered `resolved`. Without it,
metadata status is used verbatim (default `open`).

**Recurring findings are collapsed.** A persistent finding (e.g. a
world-readable `.env`) is re-filed as a fresh daily report under each day's
directory, all sharing one stable `finding_id`. Listing every daily copy buries
the few genuinely new signals under hundreds of duplicate rows — the opposite of
understanding. So the indexes group by `finding_id` (falling back to the report
stem for legacy reports without one) and render **one row per distinct finding**,
with `First seen` / `Last seen` / `Occurrences` so the recurrence is still
visible. Every daily report stays on disk and in git history untouched — only
this navigational view collapses; the link points to the most recent occurrence.

Both files live under `reports/incidents/`, so the existing
`commit_and_push_incidents` stages them with the reports.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from reports.incident_report import parse_incident_metadata

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INDEX_NAME = "index.md"
OPEN_NAME = "open_incidents.md"
_SKIP = {INDEX_NAME, OPEN_NAME}


def _collect(root: Path) -> list[dict[str, str]]:
    """Parse every incident report's metadata header. Newest day first."""
    base = root / "reports" / "incidents"
    rows: list[dict[str, str]] = []
    if not base.exists():
        return rows
    for day_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for md in sorted(day_dir.glob("*.md")):
            if md.name in _SKIP:
                continue
            try:
                meta = parse_incident_metadata(md.read_text(encoding="utf-8"))
            except OSError:
                continue
            if not meta:
                continue
            meta["_relpath"] = f"reports/incidents/{day_dir.name}/{md.name}"
            meta["_name"] = md.stem
            meta.setdefault("date", day_dir.name)
            rows.append(meta)
    rows.sort(key=lambda m: (m.get("date", ""), m.get("_name", "")), reverse=True)
    return rows


_SEV_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}


def _group_key(meta: dict[str, str]) -> str:
    """Stable identity for a recurring finding. Prefer the finding_id embedded in
    the metadata header; fall back to the report stem for legacy reports that
    predate finding_id so they still collapse by their (stable) filename."""
    return meta.get("finding_id") or meta.get("_name", "")


def _group_status(occurrences: list[dict[str, str]], active: set[str] | None) -> str:
    """A finding is open if the active set says so (when provided), otherwise if
    any of its occurrences is still open."""
    if active is not None:
        return "open" if occurrences[0].get("finding_id", "") in active else "resolved"
    return (
        "open"
        if any((m.get("status", "open") or "open") == "open" for m in occurrences)
        else "resolved"
    )


def _group(rows: list[dict[str, str]], active: set[str] | None) -> list[dict[str, Any]]:
    """Collapse rows sharing a finding identity into one entry per distinct
    finding. `rows` arrive newest-first (from `_collect`), so the first
    occurrence seen for a key is the most recent — it becomes the representative
    the row links to. Returns groups sorted by last-seen, newest first."""
    groups: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for m in rows:
        key = _group_key(m)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)

    out: list[dict[str, Any]] = []
    for key in order:
        occ = groups[key]
        dates = [m.get("date", "") for m in occ if m.get("date")]
        out.append(
            {
                "rep": occ[0],  # most recent occurrence (rows are newest-first)
                "first_seen": min(dates) if dates else occ[0].get("date", ""),
                "last_seen": max(dates) if dates else occ[0].get("date", ""),
                "occurrences": len(occ),
                "status": _group_status(occ, active),
            }
        )
    out.sort(key=lambda g: (g["last_seen"], g["rep"].get("_name", "")), reverse=True)
    return out


def _table(groups: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Last seen | Sev | Project | Type | Incident | Occurrences | First seen | Status |",
        "|-----------|-----|---------|------|----------|-------------|-----------|--------|",
    ]
    for g in groups:
        m = g["rep"]
        sev = (m.get("severity", "") or "").upper()
        icon = _SEV_ICON.get(sev, "")
        title = (m.get("title", m.get("_name", "")) or "").replace("|", "/")
        occ = g["occurrences"]
        occ_str = f"{occ}x" if occ > 1 else "1"
        lines.append(
            f"| {g['last_seen']} | {icon} {sev} | {m.get('project', '')} | "
            f"`{m.get('finding_type', '')}` | [{title}]({m['_relpath']}) | "
            f"{occ_str} | {g['first_seen']} | {g['status']} |"
        )
    return lines


def rebuild_index(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    active_finding_ids: Iterable[str] | None = None,
) -> list[str]:
    """Rebuild index.md and open_incidents.md. Returns the repo-relative paths written.

    Deterministic: output depends only on the reports on disk (+ the optional
    active-id set). `now` only stamps the 'generated' line; pass it for
    reproducible output, otherwise it is omitted.
    """
    root = root or PROJECT_ROOT
    base = root / "reports" / "incidents"
    base.mkdir(parents=True, exist_ok=True)
    rows = _collect(root)
    active = set(active_finding_ids) if active_finding_ids is not None else None
    stamp = f"_Generated {now.strftime('%Y-%m-%d %H:%M UTC')}._" if now else ""

    groups = _group(rows, active)
    open_groups = [g for g in groups if g["status"] == "open"]
    open_reports = sum(g["occurrences"] for g in open_groups)

    # index.md — every distinct finding
    idx = [
        "# Incident Index",
        "",
        "Every distinct finding (the system of record), newest activity first. "
        "Recurring findings are collapsed across daily reports — see `Occurrences`; "
        "the link points to the most recent. Rebuilt deterministically from each "
        "report's metadata header.",
        "",
        f"**{len(groups)} distinct finding(s)** across {len(rows)} filed report(s) · "
        f"**{len(open_groups)} open** · see also [open incidents](open_incidents.md).",
        "",
    ]
    idx += _table(groups) if groups else ["_No incident reports filed yet._"]
    if stamp:
        idx += ["", "---", stamp]

    # open_incidents.md — open findings only
    op = [
        "# Open Incidents",
        "",
        "Distinct findings still active (not resolved), one row per finding. "
        "See the [full index](index.md) for all findings.",
        "",
        f"**{len(open_groups)} open finding(s)** across {open_reports} filed report(s).",
        "",
    ]
    op += _table(open_groups) if open_groups else ["_No open incidents._"]
    if stamp:
        op += ["", "---", stamp]

    written: list[str] = []
    for name, body in ((INDEX_NAME, idx), (OPEN_NAME, op)):
        (base / name).write_text("\n".join(body) + "\n", encoding="utf-8")
        written.append(f"reports/incidents/{name}")
    logger.info(
        "Incident index rebuilt: %d distinct finding(s) from %d report(s), %d open",
        len(groups),
        len(rows),
        len(open_groups),
    )
    return written
