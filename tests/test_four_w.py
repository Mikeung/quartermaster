"""Tests for the 4W intelligence layer (WHAT/WHERE/WHEN/WHICH)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from cognition.four_w import (
    build_4w,
    classify_llm_activity,
    format_recommendation_markdown,
    four_w_pairs,
    get_4w,
    is_populated,
    make_4w,
    render_4w_telegram,
    summarize_4w,
)

# --- LLM activity classification (Phase 2) ---------------------------------

@pytest.mark.parametrize("workflow,expected", [
    ("procurement_intel.drain_queue", "queue processing"),
    ("nightly_cost_audit", "audit"),
    ("lexis_enrichment_tick", "ingestion"),
    ("intent_classifier", "classification"),
    ("answer_generation", "generation"),
    ("something_else", "unknown"),
    (None, "unknown"),
])
def test_classify_llm_activity(workflow, expected):
    assert classify_llm_activity(workflow) == expected


# --- canonical shape -------------------------------------------------------

def test_make_4w_is_fully_keyed():
    w = make_4w(what={"activity_type": "x"})
    assert set(w) == {"what", "where", "when", "which"}
    assert set(w["what"]) == {"activity_type", "task", "workflow"}
    assert set(w["where"]) == {"repository", "subsystem", "service", "component"}
    assert set(w["when"]) == {"start", "end", "duration", "first_seen", "last_seen"}
    assert set(w["which"]) == {"agent", "provider", "model", "workflow", "service"}


def test_is_populated():
    assert is_populated(make_4w(what={"activity_type": "a"}, where={"repository": "r"}))
    assert not is_populated(make_4w(what={"activity_type": "a"}))   # no WHERE
    assert not is_populated(make_4w(where={"repository": "r"}))     # no WHAT
    assert not is_populated({})


# --- fallback derivation ---------------------------------------------------

def test_build_4w_repo_subsystem_split():
    f = {"finding_type": "subsystem_rebuild", "target_id": "lesia",
         "resource": "lesia:backend/services", "collector_type": "git_activity_scanner",
         "first_seen": "2026-05-30T01:00:00+00:00", "last_seen": "2026-05-30T02:00:00+00:00"}
    w = build_4w(f)
    assert w["where"]["repository"] == "lesia"
    assert w["where"]["subsystem"] == "backend/services"
    assert w["which"]["agent"] == "lesia"   # git collector → agent = repo


def test_build_4w_vps_service():
    f = {"finding_type": "kernel_oom_kill", "target_id": "vps", "resource": "node",
         "collector_type": "survivability_scanner"}
    w = build_4w(f)
    assert w["where"]["service"] == "node"
    assert w["where"]["repository"] is None
    assert w["what"]["activity_type"].startswith("reliability")


def test_get_4w_prefers_attached():
    attached = make_4w(what={"activity_type": "economic: runaway agent cost"},
                       where={"repository": "lesia", "subsystem": "procurement_intel"})
    f = {"finding_type": "runaway_agent_cost", "target_id": "economic",
         "resource": "lesia:procurement_intel.drain_queue", "four_w": attached}
    w = get_4w(f)
    assert w["where"]["repository"] == "lesia"
    assert w["where"]["subsystem"] == "procurement_intel"


# --- rendering -------------------------------------------------------------

def test_four_w_pairs_labels():
    w = make_4w(
        what={"activity_type": "economic: runaway agent cost", "task": "drain"},
        where={"repository": "lesia", "subsystem": "procurement_intel"},
        when={"start": "2026-05-29T22:00:00+00:00", "end": "2026-05-30T03:00:00+00:00", "duration": "5.0h"},
        which={"agent": "lesia", "model": ["gemini", "claude"]},
    )
    pairs = dict(four_w_pairs(w))
    assert set(pairs) == {"WHAT", "WHERE", "WHEN", "WHICH"}
    assert "lesia/procurement_intel" in pairs["WHERE"]
    assert "2026-05-29 22:00" in pairs["WHEN"] and "5.0h" in pairs["WHEN"]
    assert "gemini" in pairs["WHICH"] and "claude" in pairs["WHICH"]


def test_render_telegram_has_all_four():
    w = make_4w(what={"activity_type": "x"}, where={"repository": "r"})
    block = render_4w_telegram(w)
    for label in ("WHAT", "WHERE", "WHEN", "WHICH"):
        assert f"<b>{label}:</b>" in block


def test_summarize_4w_rolls_up():
    findings = [
        {"finding_type": "subsystem_rebuild", "target_id": "lesia",
         "resource": "lesia:backend/services", "collector_type": "git_activity_scanner",
         "four_w": make_4w(what={"activity_type": "engineering: subsystem rebuild"},
                           where={"repository": "lesia", "subsystem": "backend/services"},
                           which={"agent": "Your Name"})},
        {"finding_type": "runaway_agent_cost", "target_id": "economic", "resource": "lesia:wf",
         "four_w": make_4w(what={"activity_type": "economic: runaway agent cost"},
                           where={"repository": "lesia"},
                           which={"provider": ["google", "anthropic"], "model": ["gemini"]})},
    ]
    s = summarize_4w(findings)
    assert "lesia" in s["where_repos"]
    assert "backend/services" in s["where_subsystems"]
    assert "google" in s["which_providers"] and "gemini" in s["which_models"]
    assert "Your Name" in s["which_agents"]


# --- recommendations (Phase 5) ---------------------------------------------

def test_recommendation_has_four_w_structure():
    f = {"finding_type": "runaway_agent_cost", "target_id": "economic",
         "resource": "lesia:wf", "recommendation": "Cap the workflow.",
         "evidence": ["$100 over 15h"],
         "four_w": make_4w(what={"activity_type": "economic: runaway agent cost", "task": "drain"},
                           where={"repository": "lesia"})}
    block = "\n".join(format_recommendation_markdown(f))
    assert "**Observed:**" in block
    assert "WHAT:" in block and "WHERE:" in block
    assert "**Evidence:**" in block
    assert "**Recommendation:** Cap the workflow." in block
    assert "**Expected impact:**" in block


# --- integration: detectors attach populated 4W ----------------------------

def test_economic_findings_carry_populated_4w(tmp_path):
    from memory.llm_store import LLMEventStore
    from observability.economic import detect_economic_findings
    from schemas.llm_event_schema import LLMEvent

    store = LLMEventStore(str(tmp_path / "ev.db"))
    store.connect()
    for h in range(1, 11):
        ts = (datetime.now(UTC) - timedelta(hours=h)).isoformat()
        store.append(LLMEvent(timestamp=ts, provider="google", model="gemini-2.5",
                              workflow="procurement_intel.drain_queue", prompt_tokens=0,
                              completion_tokens=0, total_tokens=0, latency_ms=0.0,
                              success=True, estimated_cost=7.0), project_id="lesia")
    findings = detect_economic_findings(store, 24)
    store.disconnect()
    assert findings
    for f in findings:
        assert is_populated(f["four_w"]), f"{f['finding_type']} has unpopulated 4W"
    runaway = [f for f in findings if f["finding_type"] == "runaway_agent_cost"]
    assert runaway
    w = runaway[0]["four_w"]
    assert w["where"]["repository"] == "lesia"
    assert "queue processing" in w["what"]["activity_type"] or w["what"]["workflow"]
