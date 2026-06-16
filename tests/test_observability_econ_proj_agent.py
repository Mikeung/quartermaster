"""Tests for economic / project / agent observability (Phases A/B/C).

Deterministic: every test builds its own input and asserts on exact finding
types and thresholds. No reliance on the live VPS state.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from config import observability_config as cfg
from memory.finding_store import (
    _SEVERITY_RATIONALE,
    ACTIONABILITY_MAP,
    OPERATIONAL_RELEVANCE_MAP,
    operator_posture,
)
from memory.llm_store import LLMEventStore
from schemas.llm_event_schema import LLMEvent

NEW_FINDING_TYPES = [
    "economic_anomaly", "spend_spike", "abnormal_burn_rate", "runaway_agent_cost",
    "project_activity", "engineering_burst", "subsystem_rebuild", "deployment_event",
    "agent_activity", "agent_cost", "agent_burst", "agent_runtime",
]


# ---------------------------------------------------------------------------
# Finding-type registration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ftype", NEW_FINDING_TYPES)
def test_finding_types_registered(ftype):
    assert ftype in OPERATIONAL_RELEVANCE_MAP
    assert ftype in ACTIONABILITY_MAP
    assert ftype in _SEVERITY_RATIONALE
    # operator_posture must resolve without falling through to the generic default
    posture = operator_posture({"finding_type": ftype, "severity": "HIGH"})
    assert posture in {"immediate_attention", "investigate", "monitor", "informational_only"}


# ---------------------------------------------------------------------------
# Phase B — git activity scanner + project analyzer
# ---------------------------------------------------------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def burst_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "your.name@example.com")
    _git(repo, "config", "user.name", "Your Name")
    sub = repo / "backend" / "services"
    sub.mkdir(parents=True)
    # 15 commits, all touching the backend/services subsystem -> burst + rebuild
    for i in range(15):
        (sub / f"mod_{i}.py").write_text(f"x = {i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"feature {i}")
    # one deploy commit
    (repo / "deploy.sh").write_text("echo deploy\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release v1")
    return repo


def test_git_scanner_counts_and_attribution(burst_repo):
    from scanners.git_activity_scanner import collect_git_activity

    a = collect_git_activity(burst_repo, window_hours=48)
    assert a["available"] is True
    assert a["commit_count"] == 16          # 15 + deploy commit
    assert a["file_count"] >= 15            # files correctly attributed (RS-leading fix)
    assert a["dominant_subsystem"]["subsystem"] == "backend/services"
    assert any("deploy" in d["evidence"] or "release" in d["subject"].lower()
               for d in a["deploy_commits"])
    assert "Your Name" in a["authors"]


def test_non_git_path_is_unavailable(tmp_path):
    from scanners.git_activity_scanner import collect_git_activity

    a = collect_git_activity(tmp_path / "nope", window_hours=24)
    assert a["available"] is False
    assert a["commit_count"] == 0


def test_project_analyzer_emits_expected_findings(burst_repo):
    from cognition.project_activity import analyze_repo_activity
    from scanners.git_activity_scanner import collect_git_activity

    a = collect_git_activity(burst_repo, window_hours=48)
    types = {f["finding_type"] for f in analyze_repo_activity(a)}
    assert "project_activity" in types
    assert "engineering_burst" in types
    assert "subsystem_rebuild" in types
    assert "deployment_event" in types


def test_quiet_repo_emits_nothing():
    from cognition.project_activity import analyze_repo_activity

    quiet = {"repo": "q", "commit_count": 0, "file_count": 0}
    assert analyze_repo_activity(quiet) == []


# ---------------------------------------------------------------------------
# Phase A — economic
# ---------------------------------------------------------------------------

@pytest.fixture
def spend_store(tmp_path):
    store = LLMEventStore(str(tmp_path / "ev.db"))
    store.connect()
    yield store
    store.disconnect()


def _add_spend(store, *, hours_ago, cost, provider="anthropic", workflow="loop", project="x"):
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    store.append(
        LLMEvent(timestamp=ts, provider=provider, model="m", workflow=workflow,
                 prompt_tokens=0, completion_tokens=0, total_tokens=0,
                 latency_ms=0.0, success=True, estimated_cost=cost),
        project_id=project,
    )


def test_no_spend_no_findings(spend_store):
    from observability.economic import detect_economic_findings
    assert detect_economic_findings(spend_store, 24) == []


def test_runaway_burn_and_spike(spend_store):
    from observability.economic import detect_economic_findings
    # 10 events of $6 across the last ~10h, one dominant workflow -> runaway
    for h in range(1, 11):
        _add_spend(spend_store, hours_ago=h, cost=6.0)
    findings = {f["finding_type"]: f for f in detect_economic_findings(spend_store, 24)}
    assert "spend_spike" in findings              # $60 >= absolute high band
    assert findings["spend_spike"]["severity"] == "HIGH"
    assert "abnormal_burn_rate" in findings        # ~$6.7/hr >= high
    assert "runaway_agent_cost" in findings        # one workflow 100% over >6h
    assert "loop" in findings["runaway_agent_cost"]["resource"]


def test_burn_only_below_runaway_threshold(spend_store):
    from observability.economic import detect_economic_findings
    # short, cheap, spread across 2 workflows -> no runaway, maybe burn
    _add_spend(spend_store, hours_ago=1, cost=3.0, workflow="a")
    _add_spend(spend_store, hours_ago=1, cost=3.0, workflow="b")
    types = {f["finding_type"] for f in detect_economic_findings(spend_store, 24)}
    assert "runaway_agent_cost" not in types


# ---------------------------------------------------------------------------
# Phase C — agent
# ---------------------------------------------------------------------------

def test_is_agent_commit_patterns():
    from observability.agent_activity import is_agent_commit
    assert is_agent_commit({"author_name": "Your Name", "author_email": "x@y", "subject": "f"})
    assert is_agent_commit({"author_name": "Mike", "author_email": "m@x", "subject": "quartermaster: tick"})
    assert is_agent_commit({"author_name": "Mike", "author_email": "m@x", "subject": "real work"}) is None


def test_agent_activity_fuses_git_and_spend(spend_store):
    from observability.agent_activity import analyze_agent_activity
    for h in range(1, 14):  # 13 agent commits over ~13h
        _add_spend(spend_store, hours_ago=h, cost=2.0, project="lesia")
    git_activity = [{
        "repo": "lesia",
        "commits": [
            {"author_name": "Your Name", "author_email": "y@n",
             "subject": f"c{i}", "date": (datetime.now(UTC) - timedelta(hours=i)).isoformat()}
            for i in range(1, 14)
        ],
    }]
    findings = {f["finding_type"]: f for f in analyze_agent_activity(git_activity, spend_store, 24)}
    assert "agent_activity" in findings
    assert "agent_burst" in findings               # 13 >= AGENT_BURST_COMMITS
    assert "agent_cost" in findings                # $26 >= notable
    assert "agent_runtime" in findings             # ~12h >= notable


def test_thresholds_are_constants():
    # guard against accidental non-determinism / type drift in config
    assert isinstance(cfg.ENGINEERING_BURST_COMMITS, int)
    assert isinstance(cfg.RUNAWAY_MIN_USD, float)
    assert cfg.SUPPORTED_PROVIDERS  # non-empty
