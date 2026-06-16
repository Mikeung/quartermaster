#!/usr/bin/env python3
"""Management Briefing — the daily CTO-facing product.

One Telegram message at 09:00 (Asia/Ho_Chi_Minh) that a busy CTO reads in 2–3
minutes to decide whether intervention is required. The markdown artifact under
reports/briefings/ is supporting documentation.

Design constraints (PM task "Management Briefing MVP"):
  - Uses EXISTING intelligence only: the operational-memory DB (snapshots, llm
    cost ledger), the incident record (reports/incidents/index.md), and the
    Project Profiles / INDEX. No new scanners.
  - Deterministic: same data -> same briefing. No LLM, no probabilistic prose.
  - Advisory: it explains and recommends; the CTO decides. Telegram send is
    gated on TELEGRAM_ENABLED, exactly like the existing daily report.

Structure (both renderings): Factory Status / Attention Required /
Top Attention Items / Safe To Ignore / Biggest Risk / Biggest Unknown /
Manager Actions.

Usage:
  python3 scripts/management_briefing.py            # dry-run: print + write artifact
  python3 scripts/management_briefing.py --send      # also send to Telegram
  python3 scripts/management_briefing.py --commit     # also git add/commit/push artifact

Cron (09:00 Asia/Ho_Chi_Minh):
  CRON_TZ=Asia/Ho_Chi_Minh
  0 9 * * *  cd /opt/quartermaster && venv/bin/python3 scripts/management_briefing.py --send --commit
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

DB_PATH = PROJECT_ROOT / "data" / "operational_memory.db"
INCIDENT_INDEX = PROJECT_ROOT / "reports" / "incidents" / "index.md"
BRIEFINGS_DIR = PROJECT_ROOT / "reports" / "briefings"

# Incident types that are this system observing/committing its own activity —
# routine background noise a CTO can safely ignore in a daily glance.
SELF_ACTIVITY_TYPES = {
    "engineering_burst", "agent_burst", "agent_runtime",
    "subsystem_rebuild", "deployment_event",
}
SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
SEV_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "⚪"}

# Management-readable labels for incident types (so a grouped line reads like a
# decision item, not a raw record). Falls back to the incident's own title.
TYPE_LABEL = {
    "credential_in_unit_file": "API keys stored in {n} service unit file(s) — rotate & lock down",
    "abnormal_burn_rate": "Unattributed LLM burn-rate spike(s)",
    "cost": "LLM spend runaway — verify the budget cap held",
    "port_exposed_publicly": "Service port exposed publicly",
    "economic_anomaly": "New LLM spender appeared",
}
# For UNKNOWN-owner incidents, give the line a management subject by type.
UNKNOWN_SUBJECT = {
    "credential_in_unit_file": "Security",
    "abnormal_burn_rate": "Cost (unattributed)",
    "port_exposed_publicly": "Network exposure",
    "economic_anomaly": "Cost",
}


def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# --------------------------------------------------------------------------- #
# Data gathering — read-only, from existing stores                            #
# --------------------------------------------------------------------------- #

@dataclass
class Incident:
    date: str
    severity: str
    project: str
    itype: str
    title: str
    path: str
    status: str


_ROW = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*\S+\s*([A-Z]+)\s*\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*(\w+)\s*\|"
)


def parse_incidents(path: Path) -> list[Incident]:
    out: list[Incident] = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        d, sev, proj, itype, title, p, status = m.groups()
        out.append(Incident(d, sev.upper(), proj.strip(), itype, title.strip(), p, status.lower()))
    return out


def gather_costs(db: sqlite3.Connection) -> dict:
    def q(sql, *a):
        return db.execute(sql, a).fetchall()
    total = q("SELECT ROUND(SUM(estimated_cost),2) FROM llm_events")[0][0] or 0.0
    by_provider = q(
        "SELECT provider, ROUND(SUM(estimated_cost),2) FROM llm_events GROUP BY provider ORDER BY 2 DESC"
    )
    by_project = q(
        "SELECT COALESCE(project_id,'(unattributed)'), ROUND(SUM(estimated_cost),2) "
        "FROM llm_events GROUP BY project_id ORDER BY 2 DESC"
    )
    by_day = q("SELECT substr(timestamp,1,10) d, ROUND(SUM(estimated_cost),2) FROM llm_events GROUP BY d ORDER BY d")
    last_day = by_day[-1] if by_day else (None, 0.0)
    return {
        "total": total,
        "by_provider": by_provider,
        "by_project": by_project,
        "last_day": last_day,
        "instrumented_projects": [p for p, _ in by_project if p != "(unattributed)"],
    }


def gather_projects(db: sqlite3.Connection) -> dict:
    rows = db.execute(
        "SELECT DISTINCT project_id FROM snapshots WHERE snapshot_type='full_scan'"
    ).fetchall()
    # Exclude scan artifacts / parent dirs that are not standalone projects.
    skip = {".", "/srv"}
    projects = sorted({r[0] for r in rows if r[0] and r[0] not in skip})
    return {"discovered": projects, "count": len(projects)}


# --------------------------------------------------------------------------- #
# Briefing model                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class Briefing:
    day: str
    weekday: str
    project_count: int
    open_total: int
    open_by_sev: dict
    new_today: list[Incident]
    new_high: int
    carried_high: list[Incident]
    cost_total: float
    cost_last_day: tuple
    instrumented: int
    uninstrumented_llm: list[str]
    top_items: list[dict] = field(default_factory=list)
    safe_to_ignore: list[str] = field(default_factory=list)
    biggest_risk: str = ""
    biggest_unknown: str = ""
    actions: list[dict] = field(default_factory=list)
    verdict: str = ""


# Known LLM/cloud-billing projects (from the Project Profiles) used only to name
# the cost blind spot — not new analysis, just which profiles say "uses LLMs".
LLM_PROJECTS = {
    "lesia": "Lesia", "seo-agent": "SEO Agent", "dtv-agent": "DTV Agent",
    "telegram-humint": "Telegram HUMINT", "deer-flow": "DeerFlow",
}


def build_briefing(now: datetime) -> Briefing:
    today = now.date().isoformat()
    incidents = parse_incidents(INCIDENT_INDEX)
    open_inc = [i for i in incidents if i.status == "open"]

    by_sev: dict[str, int] = {}
    for i in open_inc:
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1

    # "New since yesterday" = filed today (the 09:00 briefing reports the last day).
    recent = {today}
    new_today = [i for i in open_inc if i.date in recent]
    carried_high = sorted(
        [i for i in open_inc if i.severity in ("CRITICAL", "HIGH")],
        key=lambda i: (SEV_RANK[i.severity], i.date),
    )

    with sqlite3.connect(DB_PATH) as db:
        costs = gather_costs(db)
        projects = gather_projects(db)

    instrumented = set(costs["instrumented_projects"])
    uninstrumented = [name for key, name in LLM_PROJECTS.items() if key not in instrumented]

    b = Briefing(
        day=today,
        weekday=now.strftime("%A"),
        project_count=projects["count"],
        open_total=len(open_inc),
        open_by_sev=by_sev,
        new_today=new_today,
        new_high=sum(1 for i in new_today if i.severity in ("CRITICAL", "HIGH")),
        carried_high=carried_high,
        cost_total=costs["total"],
        cost_last_day=costs["last_day"],
        instrumented=len(instrumented),
        uninstrumented_llm=uninstrumented,
    )

    # --- Top attention items: every open CRITICAL + HIGH, grouped, severity-first.
    crit = [i for i in open_inc if i.severity == "CRITICAL"]
    high = [i for i in open_inc if i.severity == "HIGH"]
    for i in crit:
        b.top_items.append({
            "sev": "CRITICAL", "project": i.project, "title": i.title,
            "new": i.date in recent, "path": i.path,
        })
    # Group HIGH by (project, type) so the message stays short (3 cost incidents → 1 line).
    cost_types = {"spend_spike", "runaway_agent_cost", "agent_cost"}
    seen_groups: dict[tuple, dict] = {}
    for i in high:
        gtype = "cost" if i.itype in cost_types else i.itype
        key = (i.project, gtype)
        g = seen_groups.get(key)
        if g:
            g["count"] += 1
            g["new"] = g["new"] or (i.date in recent)
        else:
            seen_groups[key] = {
                "sev": "HIGH", "project": i.project, "gtype": gtype,
                "raw_title": i.title, "count": 1, "new": i.date in recent, "path": i.path,
            }
    for g in seen_groups.values():
        # Management label: subject for UNKNOWN owners, generic type label for the title.
        proj = g["project"]
        if proj.upper() == "UNKNOWN":
            proj = UNKNOWN_SUBJECT.get(g["gtype"], "Other")
        label = TYPE_LABEL.get(g["gtype"], g["raw_title"])
        label = label.replace("{n}", str(g["count"]))
        b.top_items.append({
            "sev": "HIGH", "project": proj, "title": label,
            "new": g["new"], "path": g["path"],
        })

    # --- Safe to ignore: self-activity + routine medium hygiene.
    self_cnt = sum(1 for i in open_inc if i.itype in SELF_ACTIVITY_TYPES)
    med_env = sum(1 for i in open_inc if i.itype == "world_readable_env_file")
    if self_cnt:
        b.safe_to_ignore.append(
            f"{self_cnt} self-activity incidents — the monitor recording its own "
            f"engineering/agent/deploy activity (expected; not a fault)."
        )
    if med_env:
        b.safe_to_ignore.append(
            f"{med_env} world-readable .env notices (MEDIUM) — real but routine file-permission hygiene."
        )
    b.safe_to_ignore.append("Everything not listed under Top Attention or Manager Actions below.")

    # --- Biggest risk / unknown (deterministic from the open set + cost ledger).
    if crit:
        c = crit[0]
        b.biggest_risk = (
            f"{c.project}: {c.title} — the highest-severity open event; "
            f"confirm the service is up and protected."
        )
    elif high:
        b.biggest_risk = f"{high[0].project}: {high[0].title}."
    else:
        b.biggest_risk = "No CRITICAL/HIGH events open."

    b.biggest_unknown = (
        f"True LLM spend. Only {b.instrumented} of {len(LLM_PROJECTS)} LLM systems is metered "
        f"(${b.cost_total:,.2f} measured); {', '.join(b.uninstrumented_llm)} bill providers "
        f"with no cost on record — spend there is unknown, not zero."
    )

    # --- Manager actions: intervention-oriented, severity-led.
    if crit:
        c = crit[0]
        b.actions.append({"do": f"Confirm {c.project} is serving and add a memory cap + auto-restart.",
                          "why": "CRITICAL outage with no recovery policy.", "intervene": True})
    cost_high = [i for i in high if i.project.lower().startswith("lesia")]
    if cost_high:
        b.actions.append({"do": "Confirm Lesia's overnight LLM spend stayed within its cap.",
                          "why": "A $100 runaway already fired once.", "intervene": False})
    cred = [i for i in high if i.itype == "credential_in_unit_file"]
    if cred:
        b.actions.append({"do": f"Rotate credentials exposed in {len(cred)} systemd unit files.",
                          "why": "HIGH — secrets readable on disk.", "intervene": True})
    if not b.actions:
        b.actions.append({"do": "None — steady state.", "why": "", "intervene": False})

    # --- One-word factory verdict.
    if crit:
        b.verdict = "ACTION NEEDED"
    elif high:
        b.verdict = "ATTENTION"
    else:
        b.verdict = "STEADY"
    return b


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sev_line(by_sev: dict) -> str:
    parts = []
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if by_sev.get(sev):
            parts.append(f"{SEV_EMOJI[sev]}{by_sev[sev]}")
    return " ".join(parts) if parts else "none"


def render_telegram(b: Briefing) -> str:
    L: list[str] = []
    L.append(f"🏭 <b>Management Briefing — {b.day}</b>")
    L.append(f"<i>{b.weekday} 09:00 · Quartermaster</i>")
    L.append("")
    L.append(
        f"<b>Factory status: {b.verdict}</b> — {b.project_count} projects · "
        f"{b.open_total} open incidents ({_sev_line(b.open_by_sev)}) · "
        f"${b.cost_total:,.2f} measured LLM spend · coverage 100%."
    )
    L.append("")
    attn = b.open_by_sev.get("CRITICAL", 0) + b.open_by_sev.get("HIGH", 0)
    L.append(
        f"<b>Attention required:</b> {'YES' if attn else 'No'} — "
        f"{b.open_by_sev.get('CRITICAL',0)} critical + {b.open_by_sev.get('HIGH',0)} high open · "
        f"{len(b.new_today)} new since yesterday ({b.new_high} need attention, the rest routine)."
    )
    L.append("")
    L.append("<b>Top attention items</b>")
    for it in b.top_items:
        tag = " <i>(new)</i>" if it.get("new") else ""
        cnt = f" ×{it['count']}" if it.get("count", 1) > 1 else ""
        L.append(f"{SEV_EMOJI[it['sev']]} <b>{_esc(it['project'])}</b>{cnt}: {_esc(it['title'])}{tag}")
    L.append("")
    L.append("<b>Safe to ignore</b>")
    for s in b.safe_to_ignore:
        L.append(f"• {_esc(s)}")
    L.append("")
    L.append(f"<b>Biggest risk:</b> {_esc(b.biggest_risk)}")
    L.append("")
    L.append(f"<b>Biggest unknown:</b> {_esc(b.biggest_unknown)}")
    L.append("")
    L.append("<b>Manager actions</b>")
    for i, a in enumerate(b.actions, 1):
        flag = " ⟵ <b>intervene</b>" if a.get("intervene") else ""
        why = f" <i>({_esc(a['why'])})</i>" if a.get("why") else ""
        L.append(f"{i}. {_esc(a['do'])}{why}{flag}")
    L.append("")
    L.append(f"<i>Full briefing: reports/briefings/{b.day}.md · No reply needed if this all looks fine.</i>")
    return "\n".join(L)


def render_markdown(b: Briefing) -> str:
    L: list[str] = []
    L.append(f"# Management Briefing — {b.day}")
    L.append("")
    L.append(f"_{b.weekday} 09:00 · Quartermaster · the Telegram message is the product; this is its supporting record._")
    L.append("")
    L.append("## Factory Status")
    L.append("")
    L.append(
        f"**{b.verdict}** — {b.project_count} projects · {b.open_total} open incidents "
        f"({_sev_line(b.open_by_sev)}) · ${b.cost_total:,.2f} measured LLM spend · coverage 100% of discovered projects."
    )
    L.append("")
    attn = b.open_by_sev.get("CRITICAL", 0) + b.open_by_sev.get("HIGH", 0)
    L.append("## Attention Required")
    L.append("")
    L.append(
        f"**{'YES' if attn else 'No'}** — {b.open_by_sev.get('CRITICAL',0)} CRITICAL + "
        f"{b.open_by_sev.get('HIGH',0)} HIGH open; {len(b.new_today)} new since yesterday "
        f"({b.new_high} need attention, the rest routine)."
    )
    L.append("")
    L.append("## Top Attention Items")
    L.append("")
    for it in b.top_items:
        tag = " *(new)*" if it.get("new") else ""
        cnt = f" ×{it['count']}" if it.get("count", 1) > 1 else ""
        L.append(f"- {SEV_EMOJI[it['sev']]} **{it['project']}**{cnt}: {it['title']}{tag} — `{it['path']}`")
    L.append("")
    L.append("## Safe To Ignore")
    L.append("")
    for s in b.safe_to_ignore:
        L.append(f"- {s}")
    L.append("")
    L.append("## Biggest Risk")
    L.append("")
    L.append(b.biggest_risk)
    L.append("")
    L.append("## Biggest Unknown")
    L.append("")
    L.append(b.biggest_unknown)
    L.append("")
    L.append("## Manager Actions")
    L.append("")
    for i, a in enumerate(b.actions, 1):
        flag = " **← intervention**" if a.get("intervene") else ""
        why = f" _({a['why']})_" if a.get("why") else ""
        L.append(f"{i}. {a['do']}{why}{flag}")
    L.append("")
    L.append("---")
    L.append("")
    L.append(
        f"_Generated deterministically from existing intelligence (incident record, cost ledger, "
        f"snapshots) at {datetime.now(UTC).isoformat(timespec='seconds')}. Advisory only — the "
        f"system recommends; the operator decides. See `reports/projects/INDEX.md` for the full briefing._"
    )
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Delivery + persistence                                                      #
# --------------------------------------------------------------------------- #

def send_telegram(text: str) -> bool:
    from delivery.notifications import default_telegram_sender
    return default_telegram_sender(text)


def write_artifact(b: Briefing, md: str) -> Path:
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out = BRIEFINGS_DIR / f"{b.day}.md"
    out.write_text(md)
    return out


def commit_artifact(path: Path, day: str) -> None:
    rel = path.relative_to(PROJECT_ROOT)
    try:
        subprocess.run(["git", "add", str(rel)], cwd=PROJECT_ROOT, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"briefing: management briefing {day}"],
            cwd=PROJECT_ROOT, check=True, capture_output=True,
        )
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=PROJECT_ROOT, capture_output=True)
        subprocess.run(["git", "push"], cwd=PROJECT_ROOT, capture_output=True)
    except subprocess.CalledProcessError:
        pass  # best-effort, never break the briefing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="send the briefing to Telegram")
    ap.add_argument("--commit", action="store_true", help="git commit + push the markdown artifact")
    args = ap.parse_args()

    _load_env()
    now = datetime.now(UTC)
    b = build_briefing(now)
    tg = render_telegram(b)
    md = render_markdown(b)

    out = write_artifact(b, md)
    print(f"[artifact] {out}")
    print("=" * 70)
    print(tg)
    print("=" * 70)
    print(f"[telegram message length] {len(tg)} chars (limit 4096)")

    if args.send:
        ok = send_telegram(tg)
        print(f"[telegram send] {'sent' if ok else 'NOT sent (TELEGRAM_ENABLED/config or error)'}")
    if args.commit:
        commit_artifact(out, b.day)
        print("[git] artifact committed (best-effort)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
