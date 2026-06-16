"""Incident report generation — the system-of-record half of an alert.

Every P0/P1 notification produces a full markdown incident report under
`reports/incidents/YYYY-MM-DD/<slug>.md`, committed and pushed to git. Telegram
only alerts and links here; this file is the durable, traceable record.

The report is rendered deterministically from the finding's existing 4W blob
(who/what/where/when/which/cost) plus its evidence — no new detection, no LLM.
Same finding + same day → same path and same body (modulo the generated-at line).

Path helpers are pure (no I/O) so the short alert can reference the path even on
a dry run; only `write_incident_report` / `commit_and_push_incidents` touch disk
or git, and callers gate those on a real (persisted) run.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INCIDENTS_DIR = PROJECT_ROOT / "reports" / "incidents"

_SECTIONS = (
    "WHAT", "WHERE", "WHEN", "WHICH", "WHO", "COST",
)

# Notification "reason" codes that carry operational meaning worth showing as the
# incident trigger. Internal dedup-timing artifacts (new, cooldown_elapsed,
# rate_capped, duplicate) are never user-facing — they would read as machinery, not
# cause. Mirrors delivery.notifications._MEANINGFUL_REASONS.
_MEANINGFUL_TRIGGERS: dict[str, str] = {
    "escalated": "severity escalated",
    "reactivated": "returned after resolving",
}

# Deterministic operational-impact statements (the impact OF the incident).
_IMPACT_BY_TYPE: dict[str, str] = {
    "runaway_agent_cost": "Unbounded, unattended spend continues to accrue until the dominant workflow is capped or interrupted.",
    "spend_spike": "Cost is materially above baseline; left unconfirmed it recurs and compounds daily.",
    "abnormal_burn_rate": "Spend is accruing faster than expected; a sustained burn translates directly into daily cost exposure.",
    "economic_anomaly": "A new or unexpected spender means cost is no longer fully attributable to known workloads.",
    "unknown_cost_owner": "Paid resource consumption is occurring with no accountable owner — cost cannot be governed.",
    "agent_cost": "An agent's cost is no longer negligible; without a budget it can grow unobserved.",
    "kernel_oom_kill": "The kernel terminated a process under memory pressure — in-flight work was lost and the service may be degraded or down.",
    "dependency_unreachable": "A core dependency is unreachable; dependent services may be failing or timing out silently.",
    "repeated_service_restart": "A service is crash-looping — reliability is degraded and restarts waste resources.",
    "port_exposed_publicly": "A service is reachable from any network interface — an open attack surface until closed.",
    "credential_in_unit_file": "Credentials are readable by any user who can inspect the unit file — an active exposure until rotated.",
    "subsystem_rebuild": "A subsystem was substantially rewritten; unreviewed, regressions can ship undetected.",
    "engineering_burst": "A large engineering push landed; review/QA capacity may lag the change volume.",
    "deployment_event": "A deploy likely occurred; if it regressed, fast rollback depends on knowing it happened.",
    "agent_burst": "High autonomous change volume — confirm the agent is operating as intended.",
}

# Deterministic open-questions per finding type (what a human must still decide).
_OPEN_QUESTIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "runaway_agent_cost": (
        "Was this run intended, or did an unattended loop drive it?",
        "Should a budget cap / kill-switch be set for this workflow?",
    ),
    "spend_spike": (
        "Was the increased spend expected (new workload) or anomalous?",
        "Which provider/workflow drove the spike, and is it sustainable?",
    ),
    "abnormal_burn_rate": (
        "Is a continuous loop or retry storm driving the sustained rate?",
        "What burn rate is acceptable for this workload?",
    ),
    "economic_anomaly": (
        "Is the new spender a legitimate, intended workload?",
        "Should it be added to the expected-providers baseline?",
    ),
    "unknown_cost_owner": (
        "Which agent/workflow emitted this spend?",
        "Why is the emitting workload not tagging a project_id/owner?",
    ),
    "kernel_oom_kill": (
        "Is this a leak, an undersized box, or a one-off spike?",
        "Should memory limits or a restart policy be added?",
    ),
    "subsystem_rebuild": (
        "Was this rewrite reviewed before landing?",
        "Are there regression tests covering the changed subsystem?",
    ),
}

_DEFAULT_OPEN_QUESTIONS = (
    "Was this event expected?",
    "What action, if any, should the operator take?",
)


# ---------------------------------------------------------------------------
# WHY DID THIS HAPPEN? — deterministic root-cause skeleton per finding type.
# Fields: immediate, contributing[], missing_safeguard[], unknown[], confidence.
# These describe the *mechanism* of the incident, not the specific instance —
# instance specifics come from the finding's evidence/4W, rendered alongside.
# ---------------------------------------------------------------------------
_WHY_BY_TYPE: dict[str, dict[str, Any]] = {
    "kernel_oom_kill": {
        "immediate": "The Linux OOM killer terminated the process because the host ran out of available memory.",
        "contributing": [
            "Process memory usage (resident set) grew to exceed free RAM + swap.",
            "No per-process memory cap, so a single process could consume the whole host.",
        ],
        "missing_safeguard": [
            "No memory limit (cgroup / systemd MemoryMax) bounding the process.",
            "No automatic restart policy to recover the service after a kill.",
        ],
        "unknown": [
            "The exact in-flight workload at the moment of termination.",
            "Whether this is a slow leak, an undersized host, or a one-off spike.",
        ],
        "confidence": "High (the kernel OOM message is unambiguous on mechanism).",
    },
    "runaway_agent_cost": {
        "immediate": "A single workflow/agent drove a dominant share of spend across a long, uninterrupted run.",
        "contributing": [
            "The workflow ran unattended for many hours without a budget checkpoint.",
            "No per-workflow spend cap or kill-switch to halt it.",
        ],
        "missing_safeguard": [
            "No per-workflow/agent budget cap.",
            "No alert/interrupt on sustained burn before the total accrued.",
        ],
        "unknown": [
            "Whether the run was intentional or an unattended loop.",
        ],
        "confidence": "High on cost (ledger-sourced); Medium on intent.",
    },
    "subsystem_rebuild": {
        "immediate": "A single subsystem received a dominant share of the window's changed files — a substantial rewrite.",
        "contributing": [
            "A large automated (e.g. aider-driven) engineering push concentrated on one subsystem.",
            "High change volume relative to normal cadence.",
        ],
        "missing_safeguard": [
            "No pre-merge review gate confirmed for the rewrite.",
            "Unknown regression-test coverage over the changed subsystem.",
        ],
        "unknown": [
            "Whether the rewrite was reviewed before landing.",
            "Whether behaviour-preserving tests exist for the changed code.",
        ],
        "confidence": "High on the change concentration (git-sourced); Medium on review status.",
    },
    "spend_spike": {
        "immediate": "Window spend exceeded the spike threshold (multiple of the trailing baseline or an absolute floor).",
        "contributing": ["A new or intensified workload increased call volume or model cost."],
        "missing_safeguard": ["No daily spend budget/alert below the spike level."],
        "unknown": ["Whether the spike is a new steady-state or a transient."],
        "confidence": "High on the figure; Medium on cause.",
    },
    "abnormal_burn_rate": {
        "immediate": "Sustained USD/hour over the window exceeded the burn-rate threshold.",
        "contributing": ["A continuous loop or retry storm kept calls flowing without pause."],
        "missing_safeguard": ["No burn-rate ceiling that interrupts sustained high spend."],
        "unknown": ["What burn rate is acceptable for this workload."],
        "confidence": "High on the rate; Medium on cause.",
    },
    "unknown_cost_owner": {
        "immediate": "Real spend was observed that could not be attributed to any project_id/owner.",
        "contributing": ["The emitting workload did not tag a project_id / owner on its spend."],
        "missing_safeguard": ["No enforced ownership tag on cost-bearing calls."],
        "unknown": ["Which agent/workflow emitted the unattributed spend."],
        "confidence": "High that the spend exists; ownership is the explicit UNKNOWN.",
    },
    "dependency_unreachable": {
        "immediate": "A core dependency stopped responding to health checks.",
        "contributing": ["The dependency crashed, was overloaded, or lost network reachability."],
        "missing_safeguard": ["No automatic failover or restart for the dependency."],
        "unknown": ["Whether the cause is the dependency itself or the network path to it."],
        "confidence": "High that it is unreachable; Medium on root cause.",
    },
    "port_exposed_publicly": {
        "immediate": "A service is bound to a public interface (0.0.0.0) with no proxy in front.",
        "contributing": ["Default bind address left public; no reverse proxy / firewall scoping."],
        "missing_safeguard": ["No bind-to-localhost or firewall rule restricting the port."],
        "unknown": ["Whether the exposure is intentional (public service) or accidental."],
        "confidence": "High on the exposure; Medium on intent.",
    },
    "credential_in_unit_file": {
        "immediate": "A credential is stored in plaintext in a systemd unit file readable by other users.",
        "contributing": ["Secret inlined into the unit instead of a mode-600 EnvironmentFile."],
        "missing_safeguard": ["No secret-management / restricted-permission storage for the credential."],
        "unknown": ["Whether the credential has already been read by another user."],
        "confidence": "High.",
    },
}

_DEFAULT_WHY = {
    "immediate": "The detector's threshold for this event type was crossed by the observed values.",
    "contributing": ["See the Evidence section for the specific values that triggered detection."],
    "missing_safeguard": ["No preventive control stopped the underlying condition before detection."],
    "unknown": ["Whether the event was expected/intended."],
    "confidence": "Medium (mechanism inferred from the finding type and evidence).",
}


# ---------------------------------------------------------------------------
# SO WHAT? — deterministic impact facets per finding type.
# Facets: operational, financial, project, user, operator_action.
# ---------------------------------------------------------------------------
_SO_WHAT_BY_TYPE: dict[str, dict[str, str]] = {
    "kernel_oom_kill": {
        "operational": "The service was killed mid-flight; in-flight work was lost and it may be down or degraded until restarted.",
        "financial": "No direct spend, but lost work may need re-running, and repeated kills waste compute.",
        "project": "The owning project's function backed by this process is interrupted until recovery.",
        "user": "Any user-facing path served by this process fails or stalls while it is down.",
        "operator_action": "Confirm the process restarted; add a memory limit / restart policy; investigate whether it is a leak or an undersized host.",
    },
    "runaway_agent_cost": {
        "operational": "An unattended workflow is consuming provider quota and may still be running.",
        "financial": "Direct, unbudgeted spend that compounds for as long as the workflow runs.",
        "project": "The project's LLM budget is being drained by one workflow, crowding out others.",
        "user": "No direct user impact, but quota exhaustion could later degrade user-facing LLM features.",
        "operator_action": "Confirm the run was intended; if not, interrupt it; set a per-workflow budget cap / kill-switch.",
    },
    "subsystem_rebuild": {
        "operational": "A large, possibly-unreviewed change landed in one subsystem — regression risk until verified.",
        "financial": "Indirect: an unreviewed regression can cause incidents (and cost) downstream.",
        "project": "The subsystem's behaviour may have changed materially; downstream assumptions may break.",
        "user": "If the subsystem is on a user path, regressions could reach users unnoticed.",
        "operator_action": "Confirm the rewrite was reviewed; ensure regression tests cover the changed subsystem before it ships further.",
    },
    "spend_spike": {
        "operational": "Cost is materially above baseline — something changed in workload or model usage.",
        "financial": "Daily spend is elevated; left unconfirmed it recurs and compounds.",
        "project": "The project driving the spike is consuming more budget than its norm.",
        "user": "No direct user impact unless it leads to quota limits.",
        "operator_action": "Identify the driving provider/workflow and confirm whether the new level is expected.",
    },
    "abnormal_burn_rate": {
        "operational": "Spend is accruing faster than expected — a sustained high-rate workload is active.",
        "financial": "A sustained burn translates directly into daily cost exposure.",
        "project": "The project's spend rate is above tolerance.",
        "user": "No direct user impact unless quota is exhausted.",
        "operator_action": "Find the loop/retry driving the rate and decide an acceptable ceiling.",
    },
    "unknown_cost_owner": {
        "operational": "Paid consumption is occurring that the system cannot attribute — cost is ungoverned.",
        "financial": "Real money is being spent with no accountable owner.",
        "project": "Some project is spending without tagging itself; budget cannot be allocated.",
        "user": "None directly.",
        "operator_action": "Identify the emitting workload and require it to tag a project_id/owner on its spend.",
    },
    "dependency_unreachable": {
        "operational": "A dependency is down; dependent services may be failing or timing out silently.",
        "financial": "Indirect: failed work and retries.",
        "project": "Any project feature relying on the dependency is impaired.",
        "user": "User-facing features backed by the dependency may fail.",
        "operator_action": "Restore the dependency or its network path; add failover/restart.",
    },
    "port_exposed_publicly": {
        "operational": "An open, unproxied port is reachable from any network — an active attack surface.",
        "financial": "Indirect: a breach via the open port could be costly.",
        "project": "The owning project's service is exposed beyond its intended scope.",
        "user": "User data served by the service could be at risk if the exposure is exploited.",
        "operator_action": "Bind to localhost or scope with a firewall/proxy unless the exposure is intentional.",
    },
    "credential_in_unit_file": {
        "operational": "A secret is readable by other local users — an active exposure until rotated.",
        "financial": "Indirect: a leaked credential could enable costly abuse.",
        "project": "The project's secret (API key/DB password) is compromised in scope.",
        "user": "User data protected by the credential could be at risk.",
        "operator_action": "Move the secret to a mode-600 EnvironmentFile and rotate the key.",
    },
}

_DEFAULT_SO_WHAT = {
    "operational": "An operational condition crossed its detection threshold and warrants operator awareness.",
    "financial": "No direct cost is attributed to this event by itself.",
    "project": "The owning project should be aware of this event.",
    "user": "No direct user impact is implied by this event type.",
    "operator_action": "Review the event and confirm whether it was expected.",
}


# ---------------------------------------------------------------------------
# Pure path helpers (no I/O)
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(text).strip().lower())
    return s.strip("-.") or "incident"


def incident_slug(finding: dict[str, Any]) -> str:
    """Deterministic filename stem: '<finding_type>__<discriminator>'.

    The discriminator (target/resource) keeps distinct incidents of the same type
    in distinct files, while the same incident maps to a stable path all day.
    """
    ftype = finding.get("finding_type", "incident")
    disc_parts = [finding.get("target_id", ""), finding.get("resource", "")]
    disc = "-".join(p for p in disc_parts if p and p not in ("economic", "vps"))
    stem = f"{ftype}__{disc}" if disc else ftype
    return _slugify(stem)[:120]


def incident_relpath(finding: dict[str, Any], now: datetime) -> str:
    """Repo-relative path for the report (pure — safe to show in a dry run)."""
    day = now.strftime("%Y-%m-%d")
    return f"reports/incidents/{day}/{incident_slug(finding)}.md"


def incident_path(finding: dict[str, Any], now: datetime, root: Path | None = None) -> Path:
    return (root or PROJECT_ROOT) / incident_relpath(finding, now)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _timeline(finding: dict[str, Any], four_w: dict, now: datetime, finding_events=None) -> list[str]:
    """Deterministic timeline from event log (if available) else from 4W times."""
    rows: list[tuple[str, str]] = []
    if finding_events:
        for ev in finding_events:
            ts = str(ev.get("event_ts", ""))
            label = ev.get("event_type", "event")
            detail = ev.get("detail", "")
            rows.append((ts, f"{label}{(' — ' + detail) if detail else ''}"))
    else:
        when = four_w.get("when", {}) or {}
        if when.get("start"):
            rows.append((str(when["start"]), "activity window start"))
        if when.get("end"):
            rows.append((str(when["end"]), "activity window end"))
        if when.get("first_seen") and when.get("first_seen") not in (when.get("start"),):
            rows.append((str(when["first_seen"]), "first observed"))
        if when.get("last_seen") and when.get("last_seen") not in (when.get("end"),):
            rows.append((str(when["last_seen"]), "last observed"))
    rows.append((now.isoformat(), "incident report generated"))
    # stable chronological order, de-duplicated; tie-break by label for full determinism
    rows = sorted({r for r in rows if r[0]}, key=lambda r: (r[0], r[1]))
    if not rows:
        return ["- _no timestamped events available_"]
    return [f"- `{t}` — {d}" for t, d in rows]


# ---------------------------------------------------------------------------
# Machine-readable metadata header (parsed by the index builders)
# ---------------------------------------------------------------------------

_META_OPEN = "<!-- quartermaster-incident"
_META_CLOSE = "-->"


def _finding_id_for(finding: dict[str, Any]) -> str:
    if finding.get("finding_id"):
        return str(finding["finding_id"])
    keys = ("target_id", "finding_type", "resource", "scope", "collector_type")
    if all(k in finding for k in keys):
        try:
            from memory.finding_store import compute_finding_id
            return compute_finding_id(
                target_id=finding["target_id"], finding_type=finding["finding_type"],
                resource=finding["resource"], scope=finding["scope"],
                collector_type=finding["collector_type"],
            )
        except Exception:
            pass
    return f"anon:{finding.get('finding_type', '?')}:{finding.get('resource', '?')}"


def _metadata_header(finding, ctx, now, priority, status: str = "open") -> list[str]:
    """Leading HTML comment carrying the fields the index builders parse."""
    def clean(v: str) -> str:
        return str(v).replace("\n", " ").replace(_META_CLOSE, "->").strip()
    fields = {
        "finding_id": _finding_id_for(finding),
        "finding_type": finding.get("finding_type", "incident"),
        "project": ctx.project,
        "subsystem": ctx.subsystem,
        "service": ctx.service,
        "severity": finding.get("severity", ""),
        "priority": priority or "",
        "date": now.strftime("%Y-%m-%d"),
        "status": status,
        "title": finding.get("title", finding.get("finding_type", "incident")),
    }
    out = [_META_OPEN]
    out += [f"{k}: {clean(v)}" for k, v in fields.items()]
    out.append(_META_CLOSE)
    return out


def parse_incident_metadata(text: str) -> dict[str, str]:
    """Parse the leading quartermaster-incident metadata block from a report's text."""
    meta: dict[str, str] = {}
    inside = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(_META_OPEN):
            inside = True
            continue
        if inside:
            if s.startswith(_META_CLOSE):
                break
            if ":" in s:
                k, _, v = s.partition(":")
                meta[k.strip()] = v.strip()
    return meta


# ---------------------------------------------------------------------------
# V4 narrative sections (deterministic)
# ---------------------------------------------------------------------------

def _project_context_lines(ctx) -> list[str]:
    """PROJECT CONTEXT — the mandatory 'what is this and who owns it' section."""
    lines = ["# PROJECT CONTEXT", ""]
    if not ctx.registered:
        lines.append(
            "> ⚠️ The owning project/service is **not registered** in "
            "`config/project_context.py`. Context cannot be fully reconstructed — "
            "this is itself a gap the operator should close."
        )
        lines.append("")
    for label, value in ctx.as_pairs():
        lines.append(f"- **{label}:** {value}")
    if ctx.inferred:
        lines += [
            "",
            f"_Attribution confidence: **{ctx.confidence}** (inferred). "
            f"Basis: {ctx.basis}_",
        ]
    lines.append("")
    return lines


def _why_lines(ftype: str, finding: dict[str, Any]) -> list[str]:
    """WHY DID THIS HAPPEN? — root cause, not description."""
    why = _WHY_BY_TYPE.get(ftype, _DEFAULT_WHY)
    lines = ["# WHY DID THIS HAPPEN?", ""]
    lines.append(f"**Immediate cause:** {why['immediate']}")
    lines.append("")
    lines.append("**Contributing factors:**")
    lines += [f"- {c}" for c in why["contributing"]]
    lines.append("")
    lines.append("**Missing safeguards:**")
    lines += [f"- {m}" for m in why["missing_safeguard"]]
    lines.append("")
    lines.append("**Unknown factors:**")
    lines += [f"- {u}" for u in why["unknown"]]
    lines.append("")
    lines.append(f"**Confidence:** {why['confidence']}")
    lines.append("")
    return lines


def _so_what_lines(ftype: str) -> list[str]:
    """SO WHAT? — why the operator should care."""
    sw = _SO_WHAT_BY_TYPE.get(ftype, _DEFAULT_SO_WHAT)
    return [
        "# SO WHAT?",
        "",
        f"- **Operational impact:** {sw['operational']}",
        f"- **Financial impact:** {sw['financial']}",
        f"- **Project impact:** {sw['project']}",
        f"- **User impact:** {sw['user']}",
        f"- **Operator action required:** {sw['operator_action']}",
        "",
    ]


def _llms_lines(four_w: dict, now: datetime, root: Path) -> list[str]:
    """WHICH LLMS WERE INVOLVED? — models/providers/agents/cost + audit links."""
    which = four_w.get("which", {}) or {}
    who = four_w.get("who", {}) or {}
    cost = four_w.get("cost", {}) or {}

    def _flat(v) -> list[str]:
        if v in (None, "", []):
            return []
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v if x]
        return [str(v)]

    providers = _flat(which.get("provider"))
    models = _flat(which.get("model"))
    agents = sorted(set(_flat(which.get("agent")) + _flat(who.get("agent")) + _flat(who.get("automation"))))

    lines = ["# WHICH LLMS WERE INVOLVED?", ""]
    if not (providers or models or agents):
        lines.append("- No LLM / model activity is directly implicated in this incident.")
        lines.append("")
        return lines

    lines.append(f"- **Models:** {', '.join(models) if models else 'UNKNOWN'}")
    lines.append(f"- **Providers:** {', '.join(providers) if providers else 'UNKNOWN'}")
    lines.append(f"- **Agents:** {', '.join(agents) if agents else 'UNKNOWN'}")
    from cognition.four_w import _cost_populated, _cost_value  # reuse formatting
    if _cost_populated(cost):
        lines.append(f"- **Cost:** {_cost_value(cost)}")

    # Cost-audit / spend links — only those that actually exist on disk.
    refs: list[str] = []
    day = now.strftime("%Y-%m-%d")
    candidates = [
        f"reports/costs/{day}_cost_audit.md",
        f"reports/history/{day}/daily_report.md",
        "data/spend/lesia_p7_audit.jsonl",
    ]
    costs_dir = root / "reports" / "costs"
    if costs_dir.exists():
        for md in sorted(costs_dir.glob("*.md")):
            refs.append(f"reports/costs/{md.name}")
    for c in candidates:
        if (root / c).exists() and c not in refs:
            refs.append(c)
    lines.append("")
    if refs:
        lines.append("See cost audits / spend records:")
        lines += [f"- `{r}`" for r in dict.fromkeys(refs)]
    else:
        lines.append("_No committed cost audit found for this date; consult the "
                     "daily report economic section and provider dashboards._")
    lines.append("")
    return lines


def correlate_incidents(
    finding: dict[str, Any], now: datetime, root: Path | None = None
) -> list[tuple[str, str]]:
    """Find prior incident reports related to this finding (deterministic scan).

    Related = shares the owning project OR the finding type. Returns
    [(repo_relative_path, relation)] sorted newest first, excluding this
    incident's own report. Reads only the committed reports' metadata headers.
    """
    root = root or PROJECT_ROOT
    base = root / "reports" / "incidents"
    if not base.exists():
        return []
    from cognition.four_w import get_4w
    from config.project_context import resolve_project_context
    self_slug = incident_slug(finding)
    self_proj = resolve_project_context(finding, get_4w(finding)).project
    self_type = finding.get("finding_type", "")

    out: list[tuple[str, str, str]] = []  # (date, relpath, relation)
    for day_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for md in sorted(day_dir.glob("*.md")):
            if md.stem == self_slug and day_dir.name == now.strftime("%Y-%m-%d"):
                continue  # skip self (same slug, same day)
            try:
                meta = parse_incident_metadata(md.read_text(encoding="utf-8"))
            except OSError:
                continue
            if not meta:
                continue
            rel = f"reports/incidents/{day_dir.name}/{md.name}"
            relation = ""
            if self_type and meta.get("finding_type") == self_type:
                relation = f"same incident type (`{self_type}`)"
            elif self_proj and self_proj != "UNKNOWN" and meta.get("project") == self_proj:
                relation = f"same project ({self_proj})"
            if relation:
                out.append((day_dir.name, rel, relation))
    out.sort(key=lambda r: r[0], reverse=True)
    return [(rel, relation) for _, rel, relation in out]


def _correlation_lines(finding, now, root) -> list[str]:
    """INCIDENT CORRELATION — links to related prior incidents + the standard prompts."""
    related = correlate_incidents(finding, now, root)
    lines = ["# INCIDENT CORRELATION", ""]
    lines.append("Is this related to previous incidents, spend spikes, deployments, "
                 "agent activity, or subsystem rebuilds?")
    lines.append("")
    if related:
        lines.append("**Related incident reports on record:**")
        for rel, relation in related[:10]:
            lines.append(f"- `{rel}` — {relation}")
        if len(related) > 10:
            lines.append(f"- _(+{len(related) - 10} more)_")
    else:
        lines.append("- No prior incident reports share this project or incident "
                     "type. If a related event predates incident reporting, check "
                     "the daily reports under `reports/history/`.")
    lines.append("")
    return lines


def _consequence_exec_lines(framing: dict[str, Any]) -> list[str]:
    """Consequence walk subsection for the Executive Summary.

    Uses bold/list markdown only (no bare `#` section headers) so the V4
    section-order invariant stays intact. Includes the consequence-adjusted
    severity rank when the walk elevated it above the intrinsic level.
    """
    lines: list[str] = ["**Consequence Walk (graph-derived)**", ""]
    node_label = framing.get("mapped_node_label", "")
    if node_label:
        lines.append(f"- Mapped node: `{node_label}`")

    # Severity rank — only show when the walk actually raised the floor.
    if framing.get("escalated"):
        base = framing.get("base_severity", "")
        effective = framing.get("consequence_severity", "")
        lines.append(
            f"- Effective severity: **{effective}** "
            f"(elevated from {base} — owner-facing output is provably lost)"
        )
    for item in framing.get("owner_facing_lost", []):
        label = item["label"]
        c = item["consequence"]
        conf = item["confidence"]
        if c != "unknown":
            lines.append(f"- Impact: **{label}** → {c} (confidence: {conf})")
        else:
            lines.append(
                f"- Impact: **{label}** goes dark "
                f"(consequence unknown — declare in `config/operational_graph.yml`)"
            )
    for label in framing.get("affected_labels", []):
        # Only list if not already covered by owner_facing_lost
        covered = {x["label"] for x in framing.get("owner_facing_lost", [])}
        if label not in covered:
            lines.append(f"- Cascade: {label} goes dark")
    trail = framing.get("evidence_trail", [])
    if trail:
        lines.append(f"- Evidence: {trail[0]}")
    if not framing.get("owner_facing_lost") and not framing.get("affected_labels"):
        lines.append(
            "- No downstream graph nodes depend on this node. "
            "Extend `config/operational_graph.yml` to declare dependencies."
        )
    lines.append("")
    return lines


def _consequence_so_what_lines(framing: dict[str, Any]) -> list[str]:
    """Graph-derived cascade block appended to the SO WHAT section."""
    lines: list[str] = ["**Graph-derived cascade (dependency walk):**", ""]
    items = framing.get("owner_facing_lost", [])
    covered = {x["label"] for x in items}
    for item in items:
        label = item["label"]
        c = item["consequence"]
        conf = item["confidence"]
        depth = item.get("depth", 0)
        loc = "directly affected" if depth == 0 else f"depth {depth}"
        if c != "unknown":
            lines.append(f"- **{label}** ({loc}): {c} — confidence: {conf}")
        else:
            lines.append(
                f"- **{label}** ({loc}): consequence not declared "
                f"— extend `config/operational_graph.yml`"
            )
    for label in framing.get("affected_labels", []):
        if label not in covered:
            lines.append(f"- {label}: structural cascade confirmed; consequence unknown")
    if not items and not framing.get("affected_labels"):
        lines.append(
            "- No downstream dependencies found in the current graph. "
            "Consequence impact is unquantified."
        )
    trail = framing.get("evidence_trail", [])
    if trail:
        lines.append(f"- Evidence: `{trail[0]}`")
    lines.append(f"- Walk confidence: {framing.get('overall_confidence', 'unknown')}")
    lines.append(
        "_Advisory — graph-derived framing; consequence annotations may be incomplete._"
    )
    lines.append("")
    return lines


def _check_steps_lines(check: dict[str, Any]) -> list[str]:
    """🔍 What to check — the deterministic diagnostic next steps for a finding.

    Rendered after the consequence (📍 Impact) block: consequence answers 'what
    happens if ignored', this answers 'what to look at next'. Advisory only."""
    lines: list[str] = ["**🔍 What to check (diagnostic — advisory):**", ""]
    for step in check.get("steps", []):
        lines.append(f"- {step['check']}")
        if step.get("why"):
            lines.append(f"  - _why: {step['why']}_")
        if step.get("evidence"):
            lines.append(f"  - _evidence: {step['evidence']}_")
    lines.append(
        "_Advisory — diagnostic steps to CHECK; the system never acts. "
        "Edit `config/check_playbook.yml` to refine._"
    )
    lines.append("")
    return lines


def generate_incident_report(
    finding: dict[str, Any],
    *,
    now: datetime,
    priority: str = "",
    reason: str = "",
    finding_events: list[dict] | None = None,
    root: Path | None = None,
    status: str = "open",
    graph_store: Any = None,
) -> str:
    """Render the full V4 markdown incident report for a finding.

    Section order: metadata header · Executive Summary · PROJECT CONTEXT · 6W
    (WHAT/WHERE/WHEN/WHICH/WHO/COST) · WHY DID THIS HAPPEN? · SO WHAT? · WHICH
    LLMS WERE INVOLVED? · INCIDENT CORRELATION · Evidence · Timeline ·
    Recommendations · Open Questions · Validation.

    graph_store (optional): when provided, consequence framing from the dependency
    walk is injected into the Executive Summary and SO WHAT sections. Reports
    generated without graph_store are identical to the prior V4 format.
    """
    from cognition.four_w import four_w_pairs, get_4w
    from config.project_context import resolve_project_context

    root = root or PROJECT_ROOT
    four_w = get_4w(finding)
    pairs = dict(four_w_pairs(four_w))
    ctx = resolve_project_context(finding, four_w)
    ftype = finding.get("finding_type", "incident")
    severity = finding.get("severity", "")
    title = finding.get("title", ftype)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")

    # Consequence framing (graph-derived, additive). Never raises.
    consequence_framing: dict | None = None
    check_steps: dict | None = None
    if graph_store is not None:
        try:
            from cognition.consequence_mapper import get_consequence_framing
            consequence_framing = get_consequence_framing(finding, graph_store)
        except Exception as _exc:
            logger.debug("consequence framing unavailable: %s", _exc)
        try:
            from cognition.check_mapper import get_check_steps
            check_steps = get_check_steps(finding, graph_store)
        except Exception as _exc:
            logger.debug("check steps unavailable: %s", _exc)

    header = " · ".join(p for p in (priority, severity) if p)
    lines: list[str] = list(_metadata_header(finding, ctx, now, priority, status))
    lines += [
        "",
        "# Executive Summary",
        "",
        f"**{title}**",
        "",
        f"- Incident type: `{ftype}`" + (f"  ·  {header}" if header else ""),
        f"- Detected: {generated}" + (f"  ·  trigger: {_trigger}" if (_trigger := _MEANINGFUL_TRIGGERS.get(reason, '')) else ""),
        f"- Description: {finding.get('description', title)}",
        "",
    ]

    # Consequence framing injected into Executive Summary (additive — never removes content).
    if consequence_framing is not None:
        lines += _consequence_exec_lines(consequence_framing)

    # 🔍 What to check — diagnostic next steps, after the consequence (📍 Impact) block.
    if check_steps is not None:
        lines += _check_steps_lines(check_steps)

    # PROJECT CONTEXT (mandatory) — what is this, who owns it, why does it exist.
    lines += _project_context_lines(ctx)

    # WHAT / WHERE / WHEN / WHICH / WHO / COST — fixed order per spec.
    for label in _SECTIONS:
        lines += [f"# {label}", "", pairs.get(label, "UNKNOWN"), ""]

    # WHY DID THIS HAPPEN? (mandatory) — root cause.
    lines += _why_lines(ftype, finding)

    # SO WHAT? (mandatory) — why the operator should care.
    lines += _so_what_lines(ftype)

    # Graph-derived cascade appended inside SO WHAT (additive).
    if consequence_framing is not None:
        lines += _consequence_so_what_lines(consequence_framing)

    # WHICH LLMS WERE INVOLVED?
    lines += _llms_lines(four_w, now, root)

    # INCIDENT CORRELATION
    lines += _correlation_lines(finding, now, root)

    # Evidence
    lines += ["# Evidence", ""]
    evidence = finding.get("evidence") or []
    if evidence:
        lines += [f"- {e}" for e in evidence if e]
    else:
        lines.append("- _no structured evidence recorded_")
    lines.append("")

    # Timeline
    lines += ["# Timeline", ""]
    lines += _timeline(finding, four_w, now, finding_events)
    lines.append("")

    # Recommendations
    lines += ["# Recommendations", ""]
    rec = finding.get("recommendation")
    if rec:
        lines.append(f"- {rec}")
    else:
        lines.append("- Review this event and confirm whether it was expected.")
    lines.append("")
    lines.append("_Advisory only — the system recommends; the operator decides and acts._")
    lines.append("")

    # Open Questions
    lines += ["# Open Questions", ""]
    for q in _OPEN_QUESTIONS_BY_TYPE.get(ftype, _DEFAULT_OPEN_QUESTIONS):
        lines.append(f"- {q}")
    lines.append("")

    # Validation
    lines += [
        "# Validation",
        "",
        "- This report was generated deterministically from the persisted finding "
        "(identity + 4W + evidence); the same finding reproduces the same report.",
        f"- Finding identity: type=`{ftype}`, target=`{finding.get('target_id', 'UNKNOWN')}`, "
        f"resource=`{finding.get('resource', 'UNKNOWN')}`.",
        "- Costs (where shown) are estimates from ingested events, not authoritative "
        "billing. Consult provider dashboards for definitive figures.",
        "- The system observes and reports; it never changed infrastructure, spend, "
        "or any provider account in producing this report.",
        "",
        "---",
        f"_Generated {generated} · advisory operational record._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Disk + git (real runs only)
# ---------------------------------------------------------------------------

def write_incident_report(
    finding: dict[str, Any],
    *,
    now: datetime,
    priority: str = "",
    reason: str = "",
    finding_events: list[dict] | None = None,
    root: Path | None = None,
    graph_store: Any = None,
) -> str:
    """Write the report to disk; return its repo-relative path. Idempotent per day."""
    relpath = incident_relpath(finding, now)
    path = (root or PROJECT_ROOT) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    body = generate_incident_report(
        finding, now=now, priority=priority, reason=reason,
        finding_events=finding_events, root=(root or PROJECT_ROOT),
        graph_store=graph_store,
    )
    path.write_text(body, encoding="utf-8")
    logger.info("Incident report written: %s", relpath)
    return relpath


def commit_and_push_incidents(
    relpaths: list[str], *, now: datetime, root: Path | None = None
) -> tuple[bool, str | None]:
    """Stage reports/incidents/, commit, rebase, push. Best-effort, race-safe.

    Stages ONLY the incidents directory (never findings DB / scan state), so it
    does not disturb occurrence_count or the notification dedup state. Uses
    `git pull --rebase --autostash` before push to absorb concurrent report-cron
    commits. Never raises — returns (ok, error_message).
    """
    cwd = root or PROJECT_ROOT
    rel_dir = "reports/incidents"
    n = len(set(relpaths))
    msg = f"quartermaster: incident report(s) {now.strftime('%Y-%m-%d %H:%M UTC')} (+{n})"
    try:
        subprocess.run(["git", "add", rel_dir], cwd=cwd, check=True,
                       capture_output=True, text=True)
        commit = subprocess.run(["git", "commit", "-m", msg], cwd=cwd,
                                capture_output=True, text=True)
        if commit.returncode != 0:
            out = (commit.stderr + commit.stdout).strip()
            if "nothing to commit" not in out:
                logger.error("Incident commit failed: %s", out[:200])
                return False, out[:200]
            logger.info("Incident commit: nothing new to commit")
        else:
            logger.info("Incident commit: %s", commit.stdout.strip()[:120])
        # Absorb interleaved commits from other crons, then push.
        subprocess.run(["git", "pull", "--rebase", "--autostash"], cwd=cwd,
                       capture_output=True, text=True, timeout=60)
        push = subprocess.run(["git", "push"], cwd=cwd, capture_output=True,
                              text=True, timeout=60)
        if push.returncode != 0:
            out = (push.stderr + push.stdout).strip()
            logger.error("Incident push failed: %s", out[:200])
            return False, out[:200]
        logger.info("Incident push: ok")
        return True, None
    except subprocess.TimeoutExpired:
        logger.error("Incident git operation timed out")
        return False, "timeout"
    except Exception as exc:
        logger.error("Incident git error: %s", type(exc).__name__)
        return False, str(exc)[:200]
