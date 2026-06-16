"""Agent observability — Phase C.

Attributes activity and cost to non-interactive agents (AI coding agents,
bots, scheduled automations). Two deterministic, evidence-based signals are
fused per agent:

  - git authorship: commits whose author identity or message matches a
    configured agent pattern (the matched pattern is the evidence).
  - spend attribution: per-project LLM/API spend from the llm_events store.

The agent's name is the repo/project it acts on (e.g. "lesia"), so git and
spend signals for the same agent merge naturally.

Finding types: agent_activity, agent_cost, agent_burst, agent_runtime.
Advisory only — this layer never starts, stops, or throttles any agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config import observability_config as cfg
from memory.llm_store import LLMEventStore

COLLECTOR_TYPE = "agent_observability"
SCOPE = "agent"


def _span_hours(timestamps: list[str]) -> float:
    parsed = []
    for t in timestamps:
        try:
            parsed.append(datetime.fromisoformat(str(t).replace("Z", "+00:00")))
        except (ValueError, TypeError):
            continue
    if len(parsed) < 2:
        return 0.0
    return round((max(parsed) - min(parsed)).total_seconds() / 3600.0, 2)


def is_agent_commit(commit: dict[str, Any]) -> str | None:
    """Return the matched agent pattern if this commit is agent-authored, else None."""
    author = f"{commit.get('author_name', '')} {commit.get('author_email', '')}".lower()
    for pat in cfg.AGENT_AUTHOR_PATTERNS:
        if pat in author:
            return f"author~'{pat}'"
    subject = commit.get("subject", "").lower()
    for pat in cfg.AGENT_MESSAGE_PATTERNS:
        if pat in subject:
            return f"message~'{pat}'"
    return None


def _finding(
    *,
    agent: str,
    finding_type: str,
    resource: str,
    severity: str,
    title: str,
    recommendation: str,
    evidence: list[str],
    four_w: dict | None = None,
) -> dict[str, Any]:
    return {
        "target_id": agent,
        "finding_type": finding_type,
        "resource": resource,
        "scope": SCOPE,
        "collector_type": COLLECTOR_TYPE,
        "severity": severity,
        "title": title,
        "description": title,
        "recommendation": recommendation,
        "evidence": evidence,
        "confidence": 1.0,
        "four_w": four_w or {},
    }


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def analyze_agent_activity(
    git_activity_list: list[dict[str, Any]],
    store: LLMEventStore | None = None,
    window_hours: int = cfg.WINDOW_HOURS,
) -> list[dict[str, Any]]:
    """Fuse git authorship + spend attribution into per-agent findings."""
    # name -> aggregated agent signal
    agents: dict[str, dict[str, Any]] = {}

    def _agent(name: str) -> dict[str, Any]:
        return agents.setdefault(name, {
            "commit_count": 0, "git_span": 0.0, "patterns": set(),
            "authors": set(), "cost": 0.0, "calls": 0, "spend_span": 0.0,
            "providers": set(), "shortlog": [],
            "git_start": None, "git_end": None, "spend_start": None, "spend_end": None,
        })

    # --- git signal ---
    for activity in git_activity_list:
        repo = activity.get("repo", "unknown")
        agent_commits = []
        for c in activity.get("commits", []):
            pat = is_agent_commit(c)
            if pat:
                agent_commits.append((c, pat))
        if not agent_commits:
            continue
        a = _agent(repo)
        a["commit_count"] = len(agent_commits)
        _cdates = [c["date"] for c, _ in agent_commits if c.get("date")]
        a["git_span"] = _span_hours(_cdates)
        if _cdates:
            a["git_start"], a["git_end"] = min(_cdates), max(_cdates)
        a["patterns"].update(pat for _, pat in agent_commits)
        a["authors"].update(c.get("author_name", "?") for c, _ in agent_commits)
        a["shortlog"] = [c.get("subject", "") for c, _ in agent_commits[:5]]

    # --- spend signal ---
    if store is not None:
        for row in store.aggregate_project_spend(window_hours):
            name = row.get("project_id")
            if not name:
                continue
            a = _agent(name)
            a["cost"] = float(row.get("total_cost") or 0.0)
            a["calls"] = int(row.get("event_count") or 0)
            a["spend_span"] = float(row.get("active_span_hours") or 0.0)
            a["spend_start"], a["spend_end"] = row.get("first_ts"), row.get("last_ts")
            try:
                a["providers"].update(
                    p.get("provider") for p in store.aggregate_by_provider_project(name, window_hours)
                    if p.get("provider")
                )
            except Exception:
                pass

    findings: list[dict[str, Any]] = []
    for name, a in agents.items():
        commits = a["commit_count"]
        cost = a["cost"]
        runtime = max(a["git_span"], a["spend_span"])
        if commits == 0 and cost <= 0:
            continue

        # --- 4W for this agent (WHO + COST included) ---
        from cognition.cost_accountability import economic_cost, economic_who
        from cognition.four_w import make_4w
        _starts = [t for t in (a["git_start"], a["spend_start"]) if t]
        _ends = [t for t in (a["git_end"], a["spend_end"]) if t]
        _burn = round(cost / runtime, 2) if (cost > 0 and runtime > 0) else None

        # Loop-dependent values are bound as default args (evaluated per iteration)
        # so this closure captures the current agent's values, not the last loop's.
        def _agent_4w(activity_type: str, duration: str | None = None, *,
                      name=name, commits=commits, cost=cost, runtime=runtime,
                      _starts=_starts, _ends=_ends, _burn=_burn, a=a) -> dict:
            return make_4w(
                who=economic_who(name),
                what={"activity_type": activity_type,
                      "task": f"{commits} commits, {_usd(cost)} spend", "workflow": None},
                where={"repository": name, "subsystem": None, "service": None, "component": name},
                when={"start": min(_starts) if _starts else None,
                      "end": max(_ends) if _ends else None,
                      "duration": duration or (f"{runtime:.1f}h" if runtime else None),
                      "first_seen": min(_starts) if _starts else None,
                      "last_seen": max(_ends) if _ends else None},
                which={"agent": name, "provider": sorted(a["providers"]) or None,
                       "model": None, "workflow": None, "service": None},
                # COST only when this agent actually spent — git-only agents have
                # no economic dimension and should not render a $0.00 COST row.
                cost=economic_cost(spend=cost, burn_rate=_burn) if cost > 0 else None,
            )

        ev_bits = []
        if commits:
            ev_bits.append(
                f"{commits} agent commit(s) [{', '.join(sorted(a['patterns']))}] "
                f"by {', '.join(sorted(a['authors']))}"
            )
        if cost > 0:
            ev_bits.append(f"{_usd(cost)} spend across {a['calls']} call event(s)")
        if a["shortlog"]:
            ev_bits.append("recent: " + " · ".join(s for s in a["shortlog"][:3] if s))

        # agent_activity — always when an agent did anything
        findings.append(_finding(
            agent=name,
            finding_type="agent_activity",
            resource=name,
            severity="LOW",
            title=f"Agent '{name}': {commits} agent commits, {_usd(cost)} spend",
            recommendation="Autonomous agent activity observed — informational.",
            evidence=ev_bits,
            four_w=_agent_4w("agent: activity"),
        ))

        # agent_burst — high autonomous change volume
        if commits >= cfg.AGENT_BURST_COMMITS:
            findings.append(_finding(
                agent=name,
                finding_type="agent_burst",
                resource=name,
                severity="MEDIUM",
                title=f"Agent burst: '{name}' produced {commits} agent commits in {window_hours}h",
                recommendation="High autonomous activity — confirm the agent is operating as intended.",
                evidence=ev_bits + [f"threshold ≥{cfg.AGENT_BURST_COMMITS} agent commits"],
                four_w=_agent_4w("agent: burst"),
            ))

        # agent_cost — meaningful spend attributed to this agent
        if cost >= cfg.AGENT_COST_NOTABLE_USD:
            sev = "HIGH" if cost >= cfg.DAILY_SPEND_HIGH_USD else "MEDIUM"
            findings.append(_finding(
                agent=name,
                finding_type="agent_cost",
                resource=name,
                severity=sev,
                title=f"Agent cost: '{name}' spent {_usd(cost)} in {window_hours}h",
                recommendation="Confirm this agent's spend is within budget expectations.",
                evidence=[
                    f"{_usd(cost)} across {a['calls']} event(s), providers: "
                    f"{', '.join(sorted(a['providers'])) or 'see economic report'}",
                    f"notable threshold ≥{_usd(cfg.AGENT_COST_NOTABLE_USD)}",
                ],
                four_w=_agent_4w("agent: cost"),
            ))

        # agent_runtime — long continuous run
        if runtime >= cfg.AGENT_RUNTIME_NOTABLE_HOURS:
            findings.append(_finding(
                agent=name,
                finding_type="agent_runtime",
                resource=name,
                severity="LOW",
                title=f"Agent '{name}' continuously active ~{runtime:.1f}h",
                recommendation="Long unattended runs are where cost and risk accrue — confirm expected.",
                evidence=[
                    f"activity span {runtime:.1f}h (git {a['git_span']:.1f}h / spend {a['spend_span']:.1f}h)",
                    f"notable threshold ≥{cfg.AGENT_RUNTIME_NOTABLE_HOURS}h",
                ],
                four_w=_agent_4w("agent: long run"),
            ))

    return findings
