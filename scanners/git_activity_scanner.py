"""Git activity scanner — read-only collection of engineering activity per repo.

Answers "what changed, who changed it, was it significant?" from the one source
of truth that already exists on disk: git history. Nothing here writes to the
scanned repositories — it only runs `git log`/`git -C ... log` with bounded output.

Output is raw, deterministic facts (counts, authors, file lists, commit subjects).
Interpretation (bursts, rebuilds, deploys, agent attribution) lives in the
cognition/observability analyzers, never here.
"""

from __future__ import annotations

import logging
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bounds so a very active repo can never produce an unbounded payload.
_MAX_COMMITS = 300
_MAX_FILES = 400
_GIT_TIMEOUT_S = 20

# ASCII unit separator / record separator — safe field delimiters for git format.
_FS = "\x1f"
_RS = "\x1e"


def _run_git(repo: Path, args: list[str]) -> str | None:
    """Run a git command in repo, returning stdout or None on any failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("git failed in %s: %s", repo, exc)
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_git_repo(path: str | Path) -> bool:
    p = Path(path)
    if not p.exists():
        return False
    return _run_git(p, ["rev-parse", "--is-inside-work-tree"]) is not None


def _subsystem_of(file_path: str, depth: int) -> str:
    """Name the subsystem a file belongs to: its first `depth` path components."""
    parts = [c for c in file_path.split("/") if c]
    if len(parts) <= 1:
        return "(repo root)"
    return "/".join(parts[:depth])


def collect_git_activity(
    repo_path: str | Path,
    *,
    window_hours: int = 24,
    subsystem_depth: int = 2,
) -> dict[str, Any]:
    """Collect deterministic git activity facts for a single repo over a window.

    Returns a dict that is always JSON-serialisable. `available=False` means the
    path is not a git work tree (caller should skip it, not treat it as zero
    activity — absence of git != absence of activity).
    """
    repo = Path(repo_path)
    name = repo.name
    base: dict[str, Any] = {
        "repo": name,
        "path": str(repo),
        "window_hours": window_hours,
        "available": False,
        "commit_count": 0,
        "file_count": 0,
        "insertions": 0,
        "deletions": 0,
        "authors": {},
        "commits": [],
        "subsystems": {},
        "dominant_subsystem": None,
        "deploy_commits": [],
        "shortlog": [],
    }

    if not is_git_repo(repo):
        return base
    base["available"] = True

    since = f"{window_hours} hours ago"
    # Record separator LEADS each commit so that --name-only file lines attach to
    # the correct commit (a trailing separator would push files into the next chunk).
    # %H hash, %an author name, %ae author email, %aI author date ISO, %s subject
    fmt = _RS + _FS.join(["%H", "%an", "%ae", "%aI", "%s"])
    out = _run_git(
        repo,
        ["log", f"--since={since}", "--no-merges", f"--pretty=format:{fmt}", "--name-only"],
    )
    if out is None:
        return base

    records = [r for r in out.split(_RS) if r.strip()]
    commits: list[dict[str, Any]] = []
    all_files: set[str] = set()
    author_counter: Counter[str] = Counter()
    subsystem_counter: Counter[str] = Counter()
    deploy_commits: list[dict[str, str]] = []

    for rec in records[:_MAX_COMMITS]:
        lines = rec.split("\n")
        header = lines[0]
        fields = header.split(_FS)
        if len(fields) < 5:
            continue
        chash, an, ae, adate, subject = fields[:5]
        files = [ln.strip() for ln in lines[1:] if ln.strip()]
        commits.append({
            "hash": chash[:12],
            "author_name": an,
            "author_email": ae,
            "date": adate,
            "subject": subject,
            "file_count": len(files),
        })
        author_counter[an] += 1
        for f in files:
            all_files.add(f)
            subsystem_counter[_subsystem_of(f, subsystem_depth)] += 1

    base["commit_count"] = len(commits)
    base["file_count"] = len(all_files)
    base["authors"] = dict(author_counter)
    base["commits"] = commits
    base["subsystems"] = dict(subsystem_counter.most_common(15))
    if subsystem_counter:
        top_sub, top_n = subsystem_counter.most_common(1)[0]
        base["dominant_subsystem"] = {"subsystem": top_sub, "file_count": top_n}
    base["shortlog"] = [c["subject"] for c in commits[:10]]

    # Deploy detection happens here only as raw flagging (path/message match);
    # the deployment_event finding decision is made by the project analyzer.
    from config.observability_config import DEPLOY_MESSAGE_MARKERS, DEPLOY_PATH_MARKERS

    # Re-read with files to flag deploy commits deterministically.
    for rec in records[:_MAX_COMMITS]:
        lines = rec.split("\n")
        fields = lines[0].split(_FS)
        if len(fields) < 5:
            continue
        chash, _an, _ae, _adate, subject = fields[:5]
        files = [ln.strip().lower() for ln in lines[1:] if ln.strip()]
        subj_l = subject.lower()
        path_hit = next(
            (f for f in files if any(m in f for m in DEPLOY_PATH_MARKERS)), None
        )
        msg_hit = any(m in subj_l for m in DEPLOY_MESSAGE_MARKERS)
        if path_hit or msg_hit:
            deploy_commits.append({
                "hash": chash[:12],
                "subject": subject,
                "evidence": f"path:{path_hit}" if path_hit else f"message:{subj_l[:60]}",
            })

    base["deploy_commits"] = deploy_commits[:20]

    # numstat totals (insertions/deletions) — bounded single call.
    stat = _run_git(repo, ["log", f"--since={since}", "--no-merges", "--numstat", "--pretty=format:"])
    if stat:
        ins = dele = 0
        for ln in stat.splitlines():
            cols = ln.split("\t")
            if len(cols) == 3:
                try:
                    ins += int(cols[0]) if cols[0].isdigit() else 0
                    dele += int(cols[1]) if cols[1].isdigit() else 0
                except ValueError:
                    pass
        base["insertions"] = ins
        base["deletions"] = dele

    return base


def collect_all_git_activity(
    targets: list[str], *, window_hours: int = 24, subsystem_depth: int = 2
) -> list[dict[str, Any]]:
    """Collect git activity for every target that is a git work tree."""
    results: list[dict[str, Any]] = []
    for t in targets:
        activity = collect_git_activity(t, window_hours=window_hours, subsystem_depth=subsystem_depth)
        if activity["available"]:
            results.append(activity)
    return results
