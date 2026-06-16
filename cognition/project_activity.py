"""Project (engineering) activity analyzer — Phase B.

Turns raw git-activity facts (from scanners.git_activity_scanner) into advisory
findings. Every decision is a deterministic threshold comparison against
config.observability_config; every finding carries the raw counts and commit
shortlog as evidence so a human can reconstruct exactly why it fired.

Finding types produced:
  - project_activity    (informational: any engineering happened here)
  - engineering_burst   (a significant push: commits/files over threshold)
  - subsystem_rebuild   (changes concentrated in one subsystem)
  - deployment_event    (deploy infra touched / release declared)

Findings are returned as plain dicts with full identity fields. Persistence and
occurrence tracking are the caller's job (FindingStore), matching the existing
security/survivability finding flow.
"""

from __future__ import annotations

from typing import Any

from config import observability_config as cfg

COLLECTOR_TYPE = "git_activity_scanner"
SCOPE = "repo"


def _finding(
    *,
    target_id: str,
    finding_type: str,
    resource: str,
    severity: str,
    title: str,
    recommendation: str,
    evidence: list[str],
    four_w: dict | None = None,
) -> dict[str, Any]:
    return {
        "target_id": target_id,
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


def analyze_repo_activity(activity: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce findings for a single repo's git-activity facts."""
    findings: list[dict[str, Any]] = []
    repo = activity.get("repo", "unknown")
    commits = activity.get("commit_count", 0)
    files = activity.get("file_count", 0)
    ins = activity.get("insertions", 0)
    dele = activity.get("deletions", 0)
    window_h = activity.get("window_hours", cfg.WINDOW_HOURS)
    authors = activity.get("authors", {}) or {}
    shortlog = activity.get("shortlog", []) or []

    if commits < cfg.PROJECT_ACTIVITY_MIN_COMMITS:
        return findings  # nothing happened in this repo this window

    author_str = ", ".join(f"{a} ({n})" for a, n in sorted(authors.items(), key=lambda x: -x[1])[:4])

    # 4W context for this repo's window
    from cognition.four_w import make_4w
    _dates = [c.get("date") for c in activity.get("commits", []) if c.get("date")]
    _start = min(_dates) if _dates else None
    _end = max(_dates) if _dates else None
    _top_author = max(authors, key=lambda a: authors[a]) if authors else None

    def _proj_4w(activity_type: str, *, subsystem: str | None = None) -> dict:
        return make_4w(
            what={"activity_type": activity_type,
                  "task": f"{commits} commits / {files} files", "workflow": None},
            where={"repository": repo, "subsystem": subsystem, "service": None, "component": repo},
            when={"start": _start, "end": _end, "duration": f"{window_h}h window",
                  "first_seen": _start, "last_seen": _end},
            which={"agent": _top_author, "provider": None, "model": None,
                   "workflow": None, "service": None},
        )

    base_evidence = [
        f"{files} files modified across {commits} commits in {window_h}h",
        f"+{ins}/-{dele} lines",
        f"authors: {author_str}",
    ]
    if shortlog:
        base_evidence.append("recent: " + " · ".join(shortlog[:3]))

    # 1. project_activity — always emitted when there is activity (situational awareness)
    findings.append(_finding(
        target_id=repo,
        finding_type="project_activity",
        resource=repo,
        severity="LOW",
        title=f"{files} files modified across {commits} commits",
        recommendation="Engineering activity observed — informational. No action required.",
        evidence=base_evidence,
        four_w=_proj_4w("engineering: activity"),
    ))

    # 2. engineering_burst — high-volume push
    if commits >= cfg.ENGINEERING_BURST_COMMITS or files >= cfg.ENGINEERING_BURST_FILES:
        sev = "MEDIUM"
        findings.append(_finding(
            target_id=repo,
            finding_type="engineering_burst",
            resource=repo,
            severity=sev,
            title=f"Major engineering activity detected: {commits} commits, {files} files in {window_h}h",
            recommendation="Significant engineering push — confirm it was expected work.",
            evidence=base_evidence + [
                f"thresholds: commits≥{cfg.ENGINEERING_BURST_COMMITS} or files≥{cfg.ENGINEERING_BURST_FILES}",
            ],
            four_w=_proj_4w("engineering: burst"),
        ))

    # 3. subsystem_rebuild — changes concentrated in one subsystem
    dom = activity.get("dominant_subsystem")
    if dom and files > 0:
        share = dom["file_count"] / files
        if share >= cfg.SUBSYSTEM_REBUILD_FILE_SHARE and dom["file_count"] >= cfg.SUBSYSTEM_REBUILD_MIN_FILES:
            sub = dom["subsystem"]
            findings.append(_finding(
                target_id=repo,
                finding_type="subsystem_rebuild",
                resource=f"{repo}:{sub}",
                severity="MEDIUM",
                title=f"{sub} subsystem rebuilt ({dom['file_count']} of {files} changed files)",
                recommendation="A single subsystem was substantially rewritten — confirm scope was intended.",
                evidence=[
                    f"{dom['file_count']}/{files} changed files ({share:.0%}) under '{sub}'",
                    f"share threshold ≥{cfg.SUBSYSTEM_REBUILD_FILE_SHARE:.0%}, min files ≥{cfg.SUBSYSTEM_REBUILD_MIN_FILES}",
                ] + (["recent: " + " · ".join(shortlog[:3])] if shortlog else []),
                four_w=_proj_4w("engineering: subsystem rebuild", subsystem=sub),
            ))

    # 4. deployment_event — deploy infra touched or release declared
    deploys = activity.get("deploy_commits", []) or []
    if deploys:
        subjects = [d["subject"] for d in deploys[:5]]
        findings.append(_finding(
            target_id=repo,
            finding_type="deployment_event",
            resource=repo,
            severity="MEDIUM",
            title=f"Deployment activity: {len(deploys)} deploy-related commit(s)",
            recommendation="A deployment likely occurred — verify it was intended and succeeded.",
            evidence=[
                f"{len(deploys)} commit(s) touched deploy infra or declared a release",
                "examples: " + " · ".join(subjects),
                "trigger: " + deploys[0]["evidence"],
            ],
            four_w=_proj_4w("engineering: deployment"),
        ))

    return findings


def analyze_project_activity(activity_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce findings across all repos. Returns a flat list of finding dicts."""
    out: list[dict[str, Any]] = []
    for activity in activity_list:
        out.extend(analyze_repo_activity(activity))
    return out
