"""Tests for the Cost Accountability hotfix (WHO + COST first-class).

Deterministic: each test builds its own spend and asserts on exact dimensions,
the unknown-owner path, the recommendation gate, and the real Lesia incident.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cognition.cost_accountability import (
    economic_cost,
    has_full_accountability,
    insufficient_context_finding,
    missing_dimensions,
    resolve_owner,
    unknown_cost_owner_finding,
)
from cognition.four_w import (
    UNKNOWN,
    four_w_pairs,
    get_4w,
    make_4w,
    make_cost,
    make_who,
    render_4w_telegram,
)
from config import observability_config as cfg
from memory.finding_store import (
    _SEVERITY_RATIONALE,
    ACTIONABILITY_MAP,
    OPERATIONAL_RELEVANCE_MAP,
    operator_posture,
)
from memory.llm_store import LLMEventStore
from observability.economic import detect_economic_findings
from schemas.llm_event_schema import LLMEvent

NEW_TYPES = ["unknown_cost_owner", "insufficient_context"]


# --- structure: WHO + COST are first-class ---------------------------------

def test_make_4w_includes_who_and_cost_when_supplied():
    w = make_4w(who=make_who(agent="lesia"), what={"activity_type": "x"},
                where={"repository": "lesia"}, cost=make_cost(spend=10.0))
    assert set(w) == {"who", "what", "where", "when", "which", "cost"}
    assert set(w["who"]) == {"agent", "owner", "automation"}
    assert set(w["cost"]) == {"spend", "burn_rate", "cumulative_cost", "currency", "unknown_reason"}


def test_make_4w_omits_who_cost_when_absent():
    # findings with no economic/ownership dimension keep the four-dimension shape
    w = make_4w(what={"activity_type": "x"}, where={"repository": "r"})
    assert set(w) == {"what", "where", "when", "which"}


def test_four_w_pairs_renders_who_first_cost_last():
    w = make_4w(who=make_who(agent="lesia", owner="Lesia"),
                what={"activity_type": "economic: runaway agent cost", "task": "drain"},
                where={"repository": "lesia"},
                which={"model": ["gemini"], "provider": ["google"]},
                cost=make_cost(spend=67.22, burn_rate=6.55, cumulative_cost=100.21))
    labels = [lbl for lbl, _ in four_w_pairs(w)]
    assert labels[0] == "WHO" and labels[-1] == "COST"
    d = dict(four_w_pairs(w))
    assert "Lesia" in d["WHO"]
    assert "$67.22" in d["COST"] and "6.55" in d["COST"] and "100.21" in d["COST"]


def test_cost_unknown_renders_explicit_with_reason():
    w = make_4w(who=make_who(agent=UNKNOWN), what={"activity_type": "x"},
                where={"service": "LLM/API spend"},
                cost=economic_cost(spend=None, unknown_reason="no attribution"))
    d = dict(four_w_pairs(w))
    assert d["COST"].startswith("UNKNOWN") and "no attribution" in d["COST"]


def test_telegram_block_has_who_and_cost():
    w = make_4w(who=make_who(agent="lesia"), what={"activity_type": "x"},
                where={"repository": "lesia"}, cost=make_cost(spend=10.0))
    block = render_4w_telegram(w)
    assert "<b>WHO:</b>" in block and "<b>COST:</b>" in block


# --- owner resolution ------------------------------------------------------

def test_resolve_owner_uses_map_then_agent_then_unknown(monkeypatch):
    # Self-contained: set the owner map for the test rather than depending on the
    # shipped default (which is empty in the OSS distribution).
    from config import observability_config as _cfg
    monkeypatch.setattr(_cfg, "COST_OWNER_MAP", {"demo-agent": "Demo Owner"})
    assert resolve_owner("demo-agent") == "Demo Owner"   # configured
    assert resolve_owner("other") == "other"             # best-effort = agent name
    assert resolve_owner(None) == UNKNOWN                # explicit unknown


# --- accountability gate ---------------------------------------------------

def test_full_accountability_true_when_all_present():
    w = make_4w(who=make_who(agent="lesia", owner="Lesia"),
                what={"activity_type": "economic: spend spike"},
                where={"repository": "lesia"},
                when={"first_seen": "2026-05-30T00:00:00+00:00"},
                which={"model": ["gemini"], "provider": ["google"]},
                cost=make_cost(spend=50.0))
    assert has_full_accountability(w)
    assert missing_dimensions(w) == []


def test_missing_who_detected_even_for_literal_unknown():
    # a literal "unknown" owner must NOT pass the gate
    w = make_4w(who=make_who(agent="unknown", owner="unknown"),
                what={"activity_type": "x"}, where={"repository": "r"},
                when={"first_seen": "t"}, which={"model": ["m"]},
                cost=make_cost(spend=1.0))
    assert "WHO" in missing_dimensions(w)


def test_missing_cost_detected():
    w = make_4w(who=make_who(agent="lesia"), what={"activity_type": "x"},
                where={"repository": "lesia"}, when={"first_seen": "t"},
                which={"model": ["m"]})
    assert "COST" in missing_dimensions(w)


# --- new finding constructors ----------------------------------------------

@pytest.mark.parametrize("ftype", NEW_TYPES)
def test_new_finding_types_registered(ftype):
    assert ftype in OPERATIONAL_RELEVANCE_MAP
    assert ftype in ACTIONABILITY_MAP
    assert ftype in _SEVERITY_RATIONALE
    assert ftype in cfg.NOTIFICATION_PRIORITY
    assert operator_posture({"finding_type": ftype, "severity": "HIGH"}) in {
        "immediate_attention", "investigate", "monitor", "informational_only"}


def test_unknown_cost_owner_finding_shape():
    f = unknown_cost_owner_finding(total_cost=72.0, window_hours=24,
                                   providers=["google"], models=["gemini-2.5-pro"],
                                   first_ts="2026-05-30T01:00:00+00:00",
                                   last_ts="2026-05-30T12:00:00+00:00")
    assert f["finding_type"] == "unknown_cost_owner" and f["severity"] == "HIGH"
    d = dict(four_w_pairs(get_4w(f)))
    assert d["WHO"] == UNKNOWN
    assert "$72.00" in d["COST"]               # COST is always known
    assert cfg.NOTIFICATION_PRIORITY["unknown_cost_owner"] == "P0"


def test_insufficient_context_names_missing():
    src = {"finding_type": "spend_spike", "resource": "daily_spend", "four_w": {}}
    f = insufficient_context_finding(source=src, missing=["WHO", "COST"])
    assert f["finding_type"] == "insufficient_context"
    assert "WHO" in f["title"] and "COST" in f["title"]


# --- end-to-end: detector attaches WHO + COST ------------------------------

def _store_with(tmp_path, rows):
    store = LLMEventStore(str(tmp_path / "ev.db"))
    store.connect()
    for r in rows:
        store.append(LLMEvent(timestamp=r["ts"], provider=r["provider"], model=r["model"],
                              workflow=r["workflow"], prompt_tokens=0, completion_tokens=0,
                              total_tokens=0, latency_ms=0.0, success=True,
                              estimated_cost=r["cost"]), project_id=r.get("project_id"))
    return store


def test_attributed_spend_has_full_accountability(tmp_path):
    rows = [{"ts": (datetime.now(UTC) - timedelta(hours=h)).isoformat(),
             "provider": "google", "model": "gemini-2.5", "workflow": "procurement_intel.drain_queue",
             "project_id": "lesia", "cost": 7.0} for h in range(1, 11)]
    store = _store_with(tmp_path, rows)
    findings = detect_economic_findings(store, 24)
    store.disconnect()
    core = [f for f in findings if f["finding_type"] in
            {"spend_spike", "abnormal_burn_rate", "runaway_agent_cost", "economic_anomaly"}]
    assert core
    for f in core:
        assert has_full_accountability(get_4w(f)), f"{f['finding_type']} lacks accountability"
        assert "withheld" not in (f.get("recommendation") or "")


def test_unattributed_spend_raises_unknown_owner_and_gates(tmp_path):
    rows = [{"ts": (datetime.now(UTC) - timedelta(hours=h)).isoformat(),
             "provider": "google", "model": "gemini-2.5-pro", "workflow": "mystery_loop",
             "project_id": None, "cost": 6.0} for h in range(1, 13)]
    store = _store_with(tmp_path, rows)
    findings = detect_economic_findings(store, 24)
    store.disconnect()
    types = [f["finding_type"] for f in findings]
    assert "unknown_cost_owner" in types
    assert "insufficient_context" in types
    # every gated core finding had its recommendation withheld
    for f in findings:
        if f["finding_type"] in {"spend_spike", "abnormal_burn_rate",
                                 "runaway_agent_cost", "economic_anomaly"}:
            assert "withheld" in (f.get("recommendation") or "")


# --- Phase 6: the real Lesia Gemini incident can now be explained ----------

def test_real_lesia_incident_is_fully_explained(tmp_path):
    ledger = Path("data/spend/lesia_p7_audit.jsonl")
    if not ledger.exists():
        pytest.skip("Lesia spend ledger not present")
    raw = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    n = len(raw)
    # re-time the audit rows into the recent window so detection fires
    rows = []
    for i, r in enumerate(raw):
        ts = datetime.now(UTC) - timedelta(minutes=(n - i) * 45)
        rows.append({"ts": ts.isoformat(), "provider": r["provider"], "model": r["model"],
                     "workflow": r["workflow"], "project_id": r.get("project_id"),
                     "cost": r["estimated_cost"]})
    store = _store_with(tmp_path, rows)
    findings = detect_economic_findings(store, 24)
    store.disconnect()

    runaway = [f for f in findings if f["finding_type"] == "runaway_agent_cost"]
    assert runaway, "the Gemini runaway must be detected"
    w = get_4w(runaway[0])
    d = dict(four_w_pairs(w))
    # WHO / WHAT / WHERE / WHEN / WHICH / COST all answered:
    assert "lesia" in d["WHO"].lower()
    assert "queue" in d["WHAT"].lower() or "drain_queue" in d["WHAT"].lower()
    assert "lesia" in d["WHERE"].lower()
    assert "–" in d["WHEN"]
    assert "gemini" in d["WHICH"].lower()
    assert "$" in d["COST"]
    assert has_full_accountability(w)
