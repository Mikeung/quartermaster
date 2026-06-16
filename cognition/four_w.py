"""4W Intelligence — canonical accountability for every activity.

Every meaningful finding answers, as first-class data:

    WHO   — agent / workflow owner / automation        (accountable actor)
    WHAT  — task / workflow / activity type
    WHERE — repository / subsystem / service / component
    WHEN  — start / end / duration / first_seen / last_seen
    WHICH — agent / provider / model / workflow / service
    COST  — spend / burn_rate / cumulative_cost         (economic accountability)

WHO and COST were added in the Cost Accountability hotfix (2026-05-30): a
production failure exposed that the system detected Gemini spend but could not,
as structured data, say WHO spent it or hold the COST in first-class fields.

Detectors attach a rich 4W (they hold the raw provider/model/window/cost data);
for any finding without one, `build_4w()` derives a deterministic one from the
finding's identity fields. Nothing here is heuristic or probabilistic — same
finding in, same accountability out. Unknown values are made explicit with the
`UNKNOWN` sentinel; they are never silently omitted. This module also renders
for reports (markdown) and notifications (Telegram HTML), and summarises across
a set of findings.
"""

from __future__ import annotations

from typing import Any

# Explicit sentinel for a value the system cannot determine. Per the cost
# accountability rule, an undeterminable field is surfaced as UNKNOWN (with a
# reason where applicable) — never silently dropped.
UNKNOWN = "UNKNOWN"

# ---------------------------------------------------------------------------
# WHAT — activity-type vocabulary (finding_type -> human activity label)
# ---------------------------------------------------------------------------
WHAT_ACTIVITY: dict[str, str] = {
    # economic
    "spend_spike": "economic: spend spike",
    "economic_anomaly": "economic: anomaly",
    "runaway_agent_cost": "economic: runaway agent cost",
    "abnormal_burn_rate": "economic: abnormal burn rate",
    # engineering
    "project_activity": "engineering: activity",
    "engineering_burst": "engineering: burst",
    "subsystem_rebuild": "engineering: subsystem rebuild",
    "deployment_event": "engineering: deployment",
    # agent
    "agent_activity": "agent: activity",
    "agent_cost": "agent: cost",
    "agent_burst": "agent: burst",
    "agent_runtime": "agent: long run",
    # reliability / survivability
    "kernel_oom_kill": "reliability: OOM kill",
    "dependency_unreachable": "reliability: dependency failure",
    "repeated_service_restart": "reliability: restart burst",
    "monitor_stale": "reliability: monitor stale",
    # security
    "port_exposed_publicly": "security: public exposure",
    "credential_in_unit_file": "security: credential exposure",
    "world_readable_env_file": "security: secret permissions",
    # drift
    "stable_listener_disappeared": "drift: listener disappeared",
    "service_disappeared": "drift: service disappeared",
    "coverage_gap": "coverage: unscanned service",
    # cost accountability
    "unknown_cost_owner": "economic: unattributed spend",
    "insufficient_context": "economic: recommendation suppressed",
    # cost advisor — budget (human-declared)
    "budget_approaching": "economic: budget approaching",
    "budget_exceeded": "economic: budget exceeded",
}

# ---------------------------------------------------------------------------
# WHAT for LLM activity — classified deterministically from the workflow name.
# Ordered: first matching substring wins.
# ---------------------------------------------------------------------------
_LLM_ACTIVITY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("drain", "queue", "consumer", "worker"), "queue processing"),
    (("audit", "cost_audit", "review"), "audit"),
    (("ingest", "enrich", "import", "extract", "scrape", "gather"), "ingestion"),
    (("classif", "route", "detect", "rerank", "moderat", "score"), "classification"),
    (("generat", "compose", "draft", "write", "summari", "debate", "answer"), "generation"),
)


def classify_llm_activity(workflow: str | None) -> str:
    """Map an LLM workflow label to a canonical activity type (deterministic)."""
    if not workflow:
        return "unknown"
    w = workflow.lower()
    for needles, label in _LLM_ACTIVITY_RULES:
        if any(n in w for n in needles):
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Canonical structure
# ---------------------------------------------------------------------------
_WHO_KEYS = ("agent", "owner", "automation")
_WHAT_KEYS = ("activity_type", "task", "workflow")
_WHERE_KEYS = ("repository", "subsystem", "service", "component")
_WHEN_KEYS = ("start", "end", "duration", "first_seen", "last_seen")
_WHICH_KEYS = ("agent", "provider", "model", "workflow", "service")
_COST_KEYS = ("spend", "burn_rate", "cumulative_cost", "currency", "unknown_reason")


def make_who(*, agent=None, owner=None, automation=None) -> dict[str, Any]:
    """WHO is accountable: the agent, its human owner, and/or the automation."""
    return {"agent": agent, "owner": owner, "automation": automation}


def make_cost(
    *, spend=None, burn_rate=None, cumulative_cost=None,
    currency: str = "USD", unknown_reason: str | None = None,
) -> dict[str, Any]:
    """COST as structured fields. A field the system cannot determine should be
    passed as the UNKNOWN sentinel (with unknown_reason), not omitted."""
    return {
        "spend": spend, "burn_rate": burn_rate, "cumulative_cost": cumulative_cost,
        "currency": currency, "unknown_reason": unknown_reason,
    }


def make_4w(
    *,
    who: dict | None = None,
    what: dict | None = None,
    where: dict | None = None,
    when: dict | None = None,
    which: dict | None = None,
    cost: dict | None = None,
) -> dict[str, dict]:
    """Build a canonical, fully-keyed accountability dict (missing → None).

    Carries six dimensions: who/what/where/when/which/cost. The name `make_4w`
    is retained for continuity; who and cost are additive and default to empty,
    so callers that ignore them are unaffected.
    """
    def _fill(d: dict | None, keys: tuple[str, ...]) -> dict:
        d = d or {}
        return {k: d.get(k) for k in keys}
    out = {
        "what": _fill(what, _WHAT_KEYS),
        "where": _fill(where, _WHERE_KEYS),
        "when": _fill(when, _WHEN_KEYS),
        "which": _fill(which, _WHICH_KEYS),
    }
    # who/cost are only included when supplied — keeps the four-dimension shape
    # for the many findings that have no economic/ownership dimension.
    if who is not None:
        out["who"] = _fill(who, _WHO_KEYS)
    if cost is not None:
        out["cost"] = _fill(cost, _COST_KEYS)
    return out


def is_populated(four_w: dict | None) -> bool:
    """True if the 4W has at least a WHAT activity_type and one WHERE value."""
    if not four_w:
        return False
    what = four_w.get("what") or {}
    where = four_w.get("where") or {}
    return bool(what.get("activity_type")) and any(where.get(k) for k in _WHERE_KEYS)


# ---------------------------------------------------------------------------
# Fallback derivation (for findings without an attached 4W)
# ---------------------------------------------------------------------------

def build_4w(finding: dict[str, Any]) -> dict[str, dict]:
    """Derive a deterministic 4W from a finding's identity fields.

    Used for finding types whose detector does not attach a rich 4W
    (survivability, security, drift, recommendations). Detector-attached 4W
    (economic/agent/project) is always preferred via get_4w().
    """
    ftype = finding.get("finding_type", "")
    target = finding.get("target_id", "")
    resource = finding.get("resource", "") or ""
    collector = finding.get("collector_type", "")
    workflow = finding.get("workflow")

    # WHERE
    repository = target if target not in ("vps", "economic", "") else None
    subsystem = None
    service = None
    if ":" in resource:
        left, right = resource.split(":", 1)
        if repository is None and left not in ("vps", "economic"):
            repository = left
        subsystem = right
    if target == "vps":
        service = resource or None
    component = resource or None

    # WHICH
    agent = target if collector == "agent_observability" else None
    if collector == "git_activity_scanner" and repository:
        agent = agent or repository

    # WHO — derive an accountable actor where the finding identifies one.
    # The owner is left None here (no config in this layer); economic/agent
    # detectors set it explicitly. build_4w only attaches WHO when an actor is
    # actually identifiable, so non-actor findings keep the four-dimension shape.
    who = None
    if agent:
        who = {"agent": agent, "owner": None, "automation": agent}

    return make_4w(
        who=who,
        what={
            "activity_type": WHAT_ACTIVITY.get(ftype, ftype or "activity"),
            "task": finding.get("title") or finding.get("recommendation") or ftype,
            "workflow": workflow,
        },
        where={
            "repository": repository,
            "subsystem": subsystem,
            "service": service,
            "component": component,
        },
        when={
            "start": None, "end": None, "duration": None,
            "first_seen": finding.get("first_seen"),
            "last_seen": finding.get("last_seen"),
        },
        which={
            "agent": agent,
            "provider": finding.get("provider"),
            "model": finding.get("model"),
            "workflow": workflow,
            "service": service,
        },
    )


def get_4w(finding: dict[str, Any]) -> dict[str, dict]:
    """Return the finding's attached 4W if populated, else derive one.

    Preserves the WHO and COST dimensions when present on the attached blob —
    without this the cost accountability hotfix data would be silently dropped.
    """
    attached = finding.get("four_w")
    if is_populated(attached):
        # ensure canonical shape even for attached dicts; carry who/cost through
        return make_4w(
            who=attached.get("who"), what=attached.get("what"),
            where=attached.get("where"), when=attached.get("when"),
            which=attached.get("which"), cost=attached.get("cost"),
        )
    return build_4w(finding)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _join(values: list[Any]) -> str:
    seen: list[str] = []
    for v in values:
        if v in (None, "", []):
            continue
        s = ", ".join(str(x) for x in v) if isinstance(v, (list, tuple, set)) else str(v)
        if s and s not in seen:
            seen.append(s)
    return " · ".join(seen)


def four_w_pairs(four_w: dict[str, dict]) -> list[tuple[str, str]]:
    """Return [(LABEL, value)] for the accountability dimensions, omitting empties.

    WHAT/WHERE/WHEN/WHICH are always present. WHO is prepended and COST appended
    only when the finding carries them (economic/agent findings) — so the many
    findings with no ownership/economic dimension still render four rows.
    """
    who, what, where, when, which, cost = (
        four_w.get(k, {}) or {} for k in ("who", "what", "where", "when", "which", "cost")
    )

    what_v = _join([what.get("task"), what.get("activity_type")]) or what.get("activity_type") or "—"
    where_v = _join([where.get("repository") and _path(where), where.get("service")]) or "—"

    when_v = "—"
    if when.get("start") and when.get("end"):
        when_v = f"{_short(when['start'])}–{_short(when['end'])}"
        if when.get("duration"):
            when_v += f" ({when['duration']})"
    elif when.get("first_seen"):
        when_v = _short(when.get("last_seen") or when.get("first_seen"))

    which_v = _join([which.get("agent"), which.get("model"), which.get("provider"),
                     which.get("workflow"), which.get("service")]) or "—"

    pairs: list[tuple[str, str]] = []
    if _who_populated(who):
        pairs.append(("WHO", _who_value(who)))
    pairs += [("WHAT", what_v), ("WHERE", where_v), ("WHEN", when_v), ("WHICH", which_v)]
    if _cost_populated(cost):
        pairs.append(("COST", _cost_value(cost)))
    return pairs


# --- WHO / COST value formatting -------------------------------------------

def _who_populated(who: dict | None) -> bool:
    return bool(who) and any(who.get(k) for k in _WHO_KEYS)


def _who_value(who: dict) -> str:
    return _join([who.get("agent"), who.get("owner"), who.get("automation")]) or UNKNOWN


def _cost_populated(cost: dict | None) -> bool:
    return bool(cost) and any(cost.get(k) is not None for k in ("spend", "burn_rate", "cumulative_cost"))


def _usd(x: Any) -> str:
    if x == UNKNOWN or x is None:
        return UNKNOWN
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _cost_value(cost: dict) -> str:
    """Render COST. Unknown spend surfaces as 'UNKNOWN (reason)' — never blank."""
    spend = cost.get("spend")
    if spend is None or spend == UNKNOWN:
        reason = cost.get("unknown_reason")
        return f"{UNKNOWN} ({reason})" if reason else UNKNOWN
    parts = [_usd(spend)]
    burn = cost.get("burn_rate")
    if burn is not None:
        parts.append(f"burn {_usd(burn)}/hr" if burn != UNKNOWN else "burn UNKNOWN")
    cum = cost.get("cumulative_cost")
    if cum is not None:
        parts.append(f"cumulative {_usd(cum)}" if cum != UNKNOWN else "cumulative UNKNOWN")
    return " · ".join(parts)


def _path(where: dict) -> str:
    parts = [where.get("repository"), where.get("subsystem")]
    return "/".join(str(p) for p in parts if p)


def _short(ts: str | None) -> str:
    """Compact timestamp: 'YYYY-MM-DD HH:MM' from an ISO string."""
    if not ts:
        return "—"
    s = str(ts).replace("T", " ")
    return s[:16]


def render_4w_markdown(four_w: dict[str, dict], indent: str = "") -> list[str]:
    """Markdown lines (for reports)."""
    return [f"{indent}- **{label}:** {value}" for label, value in four_w_pairs(four_w)]


def render_4w_telegram(four_w: dict[str, dict]) -> str:
    """Telegram HTML block (for notifications)."""
    return "\n".join(f"<b>{label}:</b> {_esc(value)}" for label, value in four_w_pairs(four_w))


# Deterministic expected-impact statement per finding type (Phase 5).
_IMPACT_BY_TYPE: dict[str, str] = {
    "runaway_agent_cost": "Capping/interrupting the dominant workflow prevents repeat unbounded overnight spend.",
    "spend_spike": "Confirming or curbing the spike avoids recurring unexpected cost.",
    "abnormal_burn_rate": "Lowering sustained burn rate reduces daily cost exposure.",
    "economic_anomaly": "Validating the new spender keeps spend attributable and expected.",
    "agent_cost": "Setting a budget for this agent bounds its cost.",
    "budget_approaching": "Knowing spend is nearing the declared budget enables a decision before it is exceeded.",
    "budget_exceeded": "Confirming the overrun lets the operator curb or re-budget the spend deliberately.",
    "subsystem_rebuild": "Awareness of the rewrite enables review before regressions ship.",
    "engineering_burst": "Visibility into the push supports timely review/QA.",
    "deployment_event": "Confirming the deploy enables fast rollback if it regressed.",
    "kernel_oom_kill": "Adding memory limits/leak fixes prevents repeat OOM termination and lost work.",
    "dependency_unreachable": "Restoring the dependency removes silent downstream failures.",
    "port_exposed_publicly": "Binding to localhost / adding a proxy removes public attack surface.",
    "credential_in_unit_file": "Moving secrets to a mode-600 EnvironmentFile and rotating keys closes the exposure.",
    "repeated_service_restart": "Fixing the crash loop restores reliability and stops wasted restarts.",
}


def format_recommendation_markdown(finding: dict[str, Any]) -> list[str]:
    """4W-derived recommendation block (Phase 5). No recommendation without 4W.

    Observed (4W) → Evidence → Recommendation → Expected impact.
    """
    w = get_4w(finding)
    lines = ["**Observed:**"]
    for label, value in four_w_pairs(w):
        lines.append(f"  - {label}: {value}")
    evidence = finding.get("evidence") or []
    ev = " · ".join(str(e) for e in evidence[:2]) if evidence else "—"
    rec = finding.get("recommendation") or finding.get("title") or "Review this finding."
    impact = _IMPACT_BY_TYPE.get(finding.get("finding_type", ""), "Resolving this reduces operational risk.")
    lines.append(f"**Evidence:** {ev}")
    lines.append(f"**Recommendation:** {rec}")
    lines.append(f"**Expected impact:** {impact}")
    return lines


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Aggregation — a day's 4W at a glance (report header)
# ---------------------------------------------------------------------------

def summarize_4w(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up accountability across findings: distinct actors/activities/places,
    time span, and total observed spend (WHO + COST included)."""
    activities: set[str] = set()
    repos: set[str] = set()
    subsystems: set[str] = set()
    services: set[str] = set()
    agents: set[str] = set()
    providers: set[str] = set()
    models: set[str] = set()
    who_actors: set[str] = set()
    who_owners: set[str] = set()
    firsts: list[str] = []
    lasts: list[str] = []
    spends: list[float] = []

    for f in findings:
        w = get_4w(f)
        if w["what"].get("activity_type"):
            activities.add(w["what"]["activity_type"])
        if w["where"].get("repository"):
            repos.add(w["where"]["repository"])
        if w["where"].get("subsystem"):
            subsystems.add(w["where"]["subsystem"])
        if w["where"].get("service"):
            services.add(w["where"]["service"])
        for key, bucket in (("agent", agents), ("provider", providers), ("model", models)):
            val = w["which"].get(key)
            if isinstance(val, (list, tuple, set)):
                bucket.update(str(x) for x in val if x)
            elif val:
                bucket.add(str(val))
        who = w.get("who") or {}
        for key, bucket in (("agent", who_actors), ("automation", who_actors), ("owner", who_owners)):
            val = who.get(key)
            if val and val != UNKNOWN:
                bucket.add(str(val))
        cost = w.get("cost") or {}
        sp = cost.get("spend")
        if sp not in (None, UNKNOWN):
            try:
                spends.append(float(sp))
            except (TypeError, ValueError):
                pass
        if w["when"].get("first_seen"):
            firsts.append(w["when"]["first_seen"])
        if w["when"].get("last_seen"):
            lasts.append(w["when"]["last_seen"])
        if w["when"].get("start"):
            firsts.append(w["when"]["start"])
        if w["when"].get("end"):
            lasts.append(w["when"]["end"])

    return {
        "what": sorted(activities),
        "where_repos": sorted(repos),
        "where_subsystems": sorted(subsystems),
        "where_services": sorted(services),
        "who_actors": sorted(who_actors),
        "who_owners": sorted(who_owners),
        "which_agents": sorted(agents),
        "which_providers": sorted(providers),
        "which_models": sorted(models),
        "when_earliest": _short(min(firsts)) if firsts else None,
        "when_latest": _short(max(lasts)) if lasts else None,
        "max_finding_spend": round(max(spends), 2) if spends else None,
    }
