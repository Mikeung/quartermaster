"""Tests for incident reporting enforcement.

Every P0/P1 send produces a deterministic markdown incident report (the system
of record); Telegram is shortened to an alert + report path. These tests never
touch the real repo or origin — file writes are isolated to tmp_path and the
commit/push machinery is exercised against a throwaway local remote.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from config import observability_config as _obs_cfg
from config import project_context as _pc
from config.project_context import Ownership, ProjectContext
from delivery.notifications import NotificationPipeline, format_notification
from reports.incident_report import (
    commit_and_push_incidents,
    generate_incident_report,
    incident_relpath,
    incident_slug,
    write_incident_report,
)


@pytest.fixture(autouse=True)
def _demo_registry(monkeypatch):
    """Seed a self-contained demo project registry so these report tests do not
    depend on whatever (possibly empty) registry the deployment ships with."""
    monkeypatch.setattr(_pc, "PROJECT_CONTEXT_REGISTRY", {
        "lesia": ProjectContext(
            project="Lesia",
            purpose="Procurement-intelligence platform driven by LLM agents.",
            runtime="python",
            subsystems={"procurement_intel": "Core procurement-intelligence pipeline.",
                        "backend/services": "Backend service layer."},
            services={"drain_queue": "Queue-draining worker that calls LLM providers.",
                      "procurement_intel.drain_queue": "The procurement_intel queue worker."},
        ),
        "hdt-web": ProjectContext(
            project="HDT Web",
            purpose="Public-facing web application (Next.js).",
            runtime="node",
            subsystems={"web-render": "Next.js server runtime: SSR/ISR rendering and API routes."},
            services={"node": "The Next.js Node.js server process that renders pages "
                              "and serves API routes."},
        ),
    })
    monkeypatch.setattr(_pc, "_PROJECT_ALIASES", {})
    monkeypatch.setattr(_pc, "SERVICE_OWNERSHIP", {
        "node": Ownership(project_id="hdt-web", subsystem="web-render", service="node",
                          confidence="Medium",
                          basis="process name 'node' attributed to hdt-web by runtime "
                                "(the only Next.js service); inferred, not a confirmed mapping."),
        "drain_queue": Ownership(project_id="lesia", subsystem="procurement_intel",
                                 service="drain_queue"),
    })
    monkeypatch.setattr(_pc, "PORT_OWNERSHIP", {})
    monkeypatch.setattr(_pc, "PROJECT_PATH_ROOTS", {})
    monkeypatch.setattr(_obs_cfg, "COST_OWNER_MAP", {"lesia": "Lesia"})

NOW = datetime(2026, 5, 30, 14, 0, tzinfo=UTC)
# V4 fixed section order (PROJECT CONTEXT + WHY + SO WHAT + WHICH LLMS +
# INCIDENT CORRELATION added; the standalone "# Impact" was folded into SO WHAT).
SECTIONS = ["# Executive Summary", "# PROJECT CONTEXT", "# WHAT", "# WHERE",
            "# WHEN", "# WHICH", "# WHO", "# COST", "# WHY DID THIS HAPPEN?",
            "# SO WHAT?", "# WHICH LLMS WERE INVOLVED?", "# INCIDENT CORRELATION",
            "# Evidence", "# Timeline", "# Recommendations", "# Open Questions",
            "# Validation"]


def _econ_finding():
    from cognition.cost_accountability import economic_who
    from cognition.four_w import make_4w, make_cost
    four_w = make_4w(
        who=economic_who("lesia", "procurement_intel.drain_queue"),
        what={"activity_type": "economic: runaway agent cost", "task": "queue processing"},
        where={"repository": "lesia", "subsystem": "procurement_intel"},
        when={"start": "2026-05-29T13:00:00+00:00", "end": "2026-05-30T13:00:00+00:00",
              "duration": "24.0h"},
        which={"agent": "lesia", "provider": ["google"], "model": ["gemini-2.5-flash"]},
        cost=make_cost(spend=100.21, burn_rate=4.18, cumulative_cost=100.21),
    )
    return {"target_id": "economic", "finding_type": "runaway_agent_cost",
            "resource": "lesia:procurement_intel.drain_queue", "scope": "spend",
            "collector_type": "economic_observability", "severity": "HIGH",
            "title": "Runaway cost: procurement_intel.drain_queue = $100.21 (100%) over 24.0h",
            "description": "One workflow dominated spend.", "evidence": ["$100.21 over 24h"],
            "recommendation": "Confirm intended; consider a budget cap.",
            "four_w": four_w}


def _oom_finding():
    return {"target_id": "vps", "finding_type": "kernel_oom_kill", "resource": "node",
            "scope": "survivability", "collector_type": "survivability_scanner",
            "severity": "CRITICAL", "title": "OOM kill: node (3.7 GB RSS)",
            "description": "Kernel OOM killed node.", "evidence": ["oom-kill ... node anon-rss:3.7GB"],
            "recommendation": "Add memory limits / fix the leak.",
            "first_seen": "2026-05-30T02:00:00+00:00", "last_seen": "2026-05-30T02:00:00+00:00"}


def _rebuild_finding():
    return {"target_id": "lesia", "finding_type": "subsystem_rebuild",
            "resource": "lesia:backend/services", "scope": "project",
            "collector_type": "git_activity_scanner", "severity": "MEDIUM",
            "title": "Subsystem rebuild: backend/services (28/52 files)",
            "description": "backend/services substantially rewritten.",
            "evidence": ["28 of 52 changed files in backend/services"],
            "recommendation": "Review the rewrite before regressions ship.",
            "first_seen": "2026-05-30T08:00:00+00:00", "last_seen": "2026-05-30T12:00:00+00:00"}


# --- pure path helpers -----------------------------------------------------

def test_slug_and_path_are_deterministic():
    f = _econ_finding()
    assert incident_slug(f) == incident_slug(f)
    rp = incident_relpath(f, NOW)
    assert rp.startswith("reports/incidents/2026-05-30/")
    assert rp.endswith(".md")
    # 'economic' target is dropped from the discriminator; resource is kept
    assert "runaway_agent_cost" in rp and "procurement" in rp


# --- report body -----------------------------------------------------------

def test_report_has_all_sections_in_order():
    body = generate_incident_report(_econ_finding(), now=NOW, priority="P0", reason="new")
    idx = [body.find(s) for s in SECTIONS]
    assert all(i >= 0 for i in idx), "every section present"
    assert idx == sorted(idx), "sections in fixed order"


def test_economic_report_populates_six_w_and_cost():
    body = generate_incident_report(_econ_finding(), now=NOW, priority="P0", reason="new")
    assert "lesia" in body and "Lesia" in body          # WHO
    assert "gemini-2.5-flash" in body                    # WHICH
    assert "$100.21" in body and "4.18" in body          # COST
    assert "procurement_intel" in body                   # WHERE
    assert "budget cap" in body                          # recommendation


def test_unknown_dimensions_render_explicit():
    # OOM has no economic dimension → COST section must say UNKNOWN, not blank
    body = generate_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new")
    cost_block = body.split("# COST", 1)[1].split("#", 1)[0]
    assert "UNKNOWN" in cost_block


def test_write_is_idempotent_per_day(tmp_path):
    f = _econ_finding()
    rp1 = write_incident_report(f, now=NOW, priority="P0", reason="new", root=tmp_path)
    rp2 = write_incident_report(f, now=NOW, priority="P0", reason="cooldown_elapsed", root=tmp_path)
    assert rp1 == rp2
    assert (tmp_path / rp1).exists()


# --- short alert references the report -------------------------------------

def test_alert_is_short_and_links_report():
    f = _econ_finding()
    rp = incident_relpath(f, NOW)
    text = format_notification(f, "new", rp)
    assert "P0" in text and "RUNAWAY AGENT COST" in text
    assert "Full report" in text and rp in text
    # compact: leads with WHO + COST, not the full block
    assert "WHO:" in text and "COST:" in text
    assert "WHERE:" not in text   # deferred to the report


# --- pipeline writes files, does not touch git by default ------------------

def test_pipeline_writes_reports_without_git(tmp_path):
    captured: list[str] = []
    pipe = NotificationPipeline(
        send_fn=lambda t: captured.append(t) or True, persist=True,
        state_path=tmp_path / "s.json", log_path=tmp_path / "l.jsonl",
        incident_root=tmp_path,  # git_sync defaults False
    )
    result = pipe.process([_econ_finding(), _oom_finding()], now=NOW)
    assert result.p0_sent == 2
    assert result.incidents_committed is False           # no git by default
    files = list((tmp_path / "reports" / "incidents" / "2026-05-30").glob("*.md"))
    assert len(files) == 2
    # every alert references a report path
    assert all("Full report" in m for m in captured)


# --- commit + push proven against a throwaway local remote -----------------

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _repo_with_remote(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "remote", "add", "origin", str(remote))
    (work / "reports" / "incidents").mkdir(parents=True)
    (work / "README.md").write_text("seed")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "seed")
    _git(work, "push", "-u", "origin", "main")
    return work, remote


def test_commit_and_push_to_remote(tmp_path):
    work, remote = _repo_with_remote(tmp_path)
    rps = []
    for f in (_econ_finding(), _oom_finding(), _rebuild_finding()):
        rps.append(write_incident_report(f, now=NOW, priority="P0", reason="new", root=work))
    ok, err = commit_and_push_incidents(rps, now=NOW, root=work)
    assert ok, f"push failed: {err}"
    # the three reports are in the pushed history on the remote
    log = subprocess.run(["git", "-C", str(remote), "log", "--name-only", "--oneline"],
                         capture_output=True, text=True).stdout
    for rp in rps:
        assert Path(rp).name in log


def test_full_chain_intrinsic_incidents_only(tmp_path):
    """Replay Gemini spend + OOM + subsystem rebuild end-to-end.

    Under the push policy, the two intrinsically critical findings (spend, OOM) earn
    committed/pushed incident reports referenced in the Telegram alert. The pure
    subsystem_rebuild — activity with no owner-facing consequence — is silenced:
    no report, no push.
    """
    work, remote = _repo_with_remote(tmp_path)
    captured: list[str] = []
    pipe = NotificationPipeline(
        send_fn=lambda t: captured.append(t) or True, persist=True,
        state_path=tmp_path / "s.json", log_path=tmp_path / "l.jsonl",
        incident_root=work, git_sync=True,
    )
    pushed = [_econ_finding(), _oom_finding()]
    silenced = _rebuild_finding()
    result = pipe.process([*pushed, silenced], now=NOW)
    assert result.incidents_committed is True
    remote_log = subprocess.run(["git", "-C", str(remote), "log", "--name-only"],
                                capture_output=True, text=True).stdout

    # The intrinsic findings each produced a committed, pushed, alert-referenced report.
    for f in pushed:
        rp = incident_relpath(f, NOW)
        assert (work / rp).exists(), "report created"
        assert Path(rp).name in remote_log, "report pushed"
        assert any(rp in m for m in captured), "telegram references report"

    # The impact-free subsystem_rebuild was demoted: no report, no push, no alert.
    rebuild_rp = incident_relpath(silenced, NOW)
    assert not (work / rebuild_rp).exists(), "impact-free rebuild must not file a report"
    assert Path(rebuild_rp).name not in remote_log
    assert not any(rebuild_rp in m for m in captured)
    assert any(d.reason == "no_consequence" for d in result.suppressed)

    # index + open_incidents rebuilt and pushed alongside the reports
    assert (work / "reports" / "incidents" / "index.md").exists()
    assert "index.md" in remote_log and "open_incidents.md" in remote_log


# ===========================================================================
# V4 — report architecture (PROJECT CONTEXT / WHY / SO WHAT / LLMS / CORRELATION)
# ===========================================================================

from reports.incident_report import (  # noqa: E402
    correlate_incidents,
    parse_incident_metadata,
)


def test_project_context_section_present_and_resolves_owner():
    body = generate_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new")
    ctx = body.split("# PROJECT CONTEXT", 1)[1].split("# WHAT", 1)[0]
    # the node process is attributed to hdt-web with explicit, stated inference
    assert "HDT Web" in ctx
    assert "Project purpose:" in ctx and "Service purpose:" in ctx
    assert "inferred" in ctx.lower() and "Medium" in ctx


def test_oom_report_answers_the_five_validation_questions():
    """The hard V4 requirement: a returning operator can answer all five
    questions from the OOM report alone — no follow-up needed."""
    body = generate_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new")
    # 1. What is the killed service?  → service purpose
    assert "Next.js Node.js server process" in body
    # 2. Which project owns it?       → project name
    assert "HDT Web" in body
    # 3. Why does it exist?           → subsystem/service purpose
    assert "SSR" in body or "renders pages" in body
    # 4. Why was it killed?           → WHY DID THIS HAPPEN (immediate cause)
    why = body.split("# WHY DID THIS HAPPEN?", 1)[1].split("# SO WHAT?", 1)[0]
    assert "Immediate cause:" in why and "OOM killer" in why
    assert "Confidence:" in why
    # 5. Why should I care?           → SO WHAT (operator action)
    sw = body.split("# SO WHAT?", 1)[1].split("# WHICH LLMS", 1)[0]
    assert "Operational impact:" in sw and "Operator action required:" in sw


def test_why_section_has_all_required_fields():
    body = generate_incident_report(_rebuild_finding(), now=NOW, priority="P0", reason="new")
    why = body.split("# WHY DID THIS HAPPEN?", 1)[1].split("# SO WHAT?", 1)[0]
    for field in ("Immediate cause:", "Contributing factors:",
                  "Missing safeguards:", "Unknown factors:", "Confidence:"):
        assert field in why


def test_llms_section_lists_models_for_economic_incident():
    body = generate_incident_report(_econ_finding(), now=NOW, priority="P0", reason="new")
    llm = body.split("# WHICH LLMS WERE INVOLVED?", 1)[1].split("# INCIDENT CORRELATION", 1)[0]
    assert "gemini-2.5-flash" in llm and "google" in llm
    assert "Cost:" in llm


def test_llms_section_explicit_when_no_models():
    body = generate_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new")
    llm = body.split("# WHICH LLMS WERE INVOLVED?", 1)[1].split("# INCIDENT CORRELATION", 1)[0]
    assert "No LLM" in llm


def test_metadata_header_roundtrips():
    body = generate_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new")
    assert body.startswith("<!-- quartermaster-incident")
    meta = parse_incident_metadata(body)
    assert meta["finding_type"] == "kernel_oom_kill"
    assert meta["project"] == "HDT Web"
    assert meta["status"] == "open"
    assert meta["severity"] == "CRITICAL"


def test_correlation_links_same_type_and_project(tmp_path):
    # file two prior incidents, then correlate a fresh one of the same type
    write_incident_report(_oom_finding(), now=datetime(2026, 5, 28, 2, 0, tzinfo=UTC),
                          priority="P0", reason="new", root=tmp_path)
    write_incident_report(_rebuild_finding(), now=datetime(2026, 5, 29, 8, 0, tzinfo=UTC),
                          priority="P0", reason="new", root=tmp_path)
    related = correlate_incidents(_oom_finding(), NOW, root=tmp_path)
    assert any("kernel_oom_kill" in r for _, r in related), "same-type correlation"
    # a same-project (lesia) incident is found for a lesia finding
    related2 = correlate_incidents(_econ_finding(), NOW, root=tmp_path)
    assert any("Lesia" in r or "lesia" in r for _, r in related2), "same-project correlation"


def test_rebuild_index_writes_both_files(tmp_path):
    from reports.incident_index import rebuild_index
    for f, when in ((_oom_finding(), NOW), (_econ_finding(), NOW),
                    (_rebuild_finding(), datetime(2026, 5, 29, 8, 0, tzinfo=UTC))):
        write_incident_report(f, now=when, priority="P0", reason="new", root=tmp_path)
    written = rebuild_index(root=tmp_path, now=NOW)
    assert "reports/incidents/index.md" in written
    assert "reports/incidents/open_incidents.md" in written
    index = (tmp_path / "reports" / "incidents" / "index.md").read_text()
    # 3 distinct findings, each filed once
    assert "3 distinct finding(s)" in index
    assert "HDT Web" in index and "Lesia" in index
    # all open by default → open_incidents lists 3 distinct findings
    op = (tmp_path / "reports" / "incidents" / "open_incidents.md").read_text()
    assert "3 open finding(s)" in op


def test_rebuild_index_collapses_recurring_finding(tmp_path):
    """A persistent finding re-filed across several days collapses to ONE row
    with an occurrence count and a first/last-seen span — not one row per day."""
    from reports.incident_index import rebuild_index

    # Same finding filed on three consecutive days (same finding_id).
    days = [datetime(2026, 5, 28, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 29, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 30, 2, 0, tzinfo=UTC)]
    for when in days:
        write_incident_report(_oom_finding(), now=when, priority="P0", reason="new", root=tmp_path)

    rebuild_index(root=tmp_path, now=NOW)
    index = (tmp_path / "reports" / "incidents" / "index.md").read_text()
    # one distinct finding, three filed reports
    assert "distinct finding(s)** across 3 filed report(s)" in index
    assert "**1 distinct finding(s)**" in index
    # occurrence count and the first/last-seen span are both shown
    assert "3x" in index
    assert "2026-05-28" in index and "2026-05-30" in index
    op = (tmp_path / "reports" / "incidents" / "open_incidents.md").read_text()
    assert "**1 open finding(s)** across 3 filed report(s)" in op


def test_rebuild_index_open_status_survives_old_resolved_copies(tmp_path):
    """If the active set marks a finding open, the collapsed row is open even
    though older daily copies carried status text — active set wins."""
    from memory.finding_store import compute_finding_id
    from reports.incident_index import rebuild_index

    for when in (datetime(2026, 5, 29, 2, 0, tzinfo=UTC), NOW):
        write_incident_report(_oom_finding(), now=when, priority="P0", reason="new", root=tmp_path)
    oom = _oom_finding()
    active = {compute_finding_id(target_id=oom["target_id"], finding_type=oom["finding_type"],
                                resource=oom["resource"], scope=oom["scope"],
                                collector_type=oom["collector_type"])}
    rebuild_index(root=tmp_path, now=NOW, active_finding_ids=active)
    op = (tmp_path / "reports" / "incidents" / "open_incidents.md").read_text()
    assert "**1 open finding(s)** across 2 filed report(s)" in op


def test_rebuild_index_marks_resolved_when_active_ids_given(tmp_path):
    from reports.incident_index import rebuild_index
    write_incident_report(_oom_finding(), now=NOW, priority="P0", reason="new", root=tmp_path)
    write_incident_report(_econ_finding(), now=NOW, priority="P0", reason="new", root=tmp_path)
    # only the OOM finding is still active → econ should render resolved/closed
    from memory.finding_store import compute_finding_id
    oom = _oom_finding()
    active = {compute_finding_id(target_id=oom["target_id"], finding_type=oom["finding_type"],
                                 resource=oom["resource"], scope=oom["scope"],
                                 collector_type=oom["collector_type"])}
    rebuild_index(root=tmp_path, now=NOW, active_finding_ids=active)
    op = (tmp_path / "reports" / "incidents" / "open_incidents.md").read_text()
    assert "1 open finding(s)" in op
    assert "kernel_oom_kill" in op and "runaway_agent_cost" not in op
