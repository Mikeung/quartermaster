"""Tests for the real-time notification pipeline (PRIORITY ZERO).

Deterministic: injected clock, injected capturing sender, temp state files.
No real Telegram traffic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from config import observability_config as cfg
from delivery.notifications import (
    NotificationPipeline,
    classify,
    format_notification,
    is_quiet_hour,
)

DAY = datetime(2026, 5, 30, 14, 0, tzinfo=UTC)     # outside quiet hours
NIGHT = datetime(2026, 5, 30, 3, 0, tzinfo=UTC)    # inside quiet hours (22:00-08:00)


def _finding(ftype, sev="HIGH", resource="r", target="t", title=None, **extra):
    return {
        "target_id": target, "finding_type": ftype, "resource": resource,
        "scope": "s", "collector_type": "c", "severity": sev,
        "title": title or f"{ftype} happened", "evidence": [f"ev for {ftype}"],
        **extra,
    }


@pytest.fixture
def pipe_factory(tmp_path):
    def make():
        captured: list[str] = []
        p = NotificationPipeline(
            send_fn=lambda t: captured.append(t) or True,
            persist=True,
            state_path=tmp_path / "state.json",
            log_path=tmp_path / "log.jsonl",
            incident_root=tmp_path,   # isolate incident files; git_sync off by default
        )
        return p, captured
    return make


# --- classification --------------------------------------------------------

def test_classify_known_and_default():
    assert classify({"finding_type": "runaway_agent_cost"}) == "P0"
    assert classify({"finding_type": "spend_spike"}) == "P0"
    assert classify({"finding_type": "credential_in_unit_file"}) == "P1"
    assert classify({"finding_type": "project_activity"}) == "P2"
    # unmapped -> default P2 (push is an explicit allowlist)
    assert classify({"finding_type": "totally_unknown_type"}) == cfg.NOTIFY_DEFAULT_PRIORITY == "P2"


# --- core send + dedup -----------------------------------------------------

def test_p0_sends_then_dedupes(pipe_factory):
    p, cap = pipe_factory()
    f = [_finding("runaway_agent_cost")]
    r1 = p.process(f, now=DAY)
    assert r1.p0_sent == 1 and len(cap) == 1

    # same finding, same state, +1h -> suppressed as duplicate (no second message)
    p2, cap2 = pipe_factory()  # re-reads persisted state file
    r2 = p2.process(f, now=DAY + timedelta(hours=1))
    assert r2.p0_sent == 0
    assert len(cap2) == 0
    assert any(d.reason == "duplicate" for d in r2.suppressed)


def test_escalation_bypasses_cooldown(pipe_factory):
    p, cap = pipe_factory()
    p.process([_finding("economic_anomaly", sev="MEDIUM")], now=DAY)
    p2, cap2 = pipe_factory()
    # same finding identity, higher severity within cooldown -> re-alert
    r = p2.process([_finding("economic_anomaly", sev="HIGH")], now=DAY + timedelta(hours=1))
    assert r.p0_sent == 1
    assert any(d.reason == "escalated" for d in r.sent)


def test_cooldown_elapsed_renotifies(pipe_factory):
    p, _ = pipe_factory()
    p.process([_finding("spend_spike")], now=DAY)
    p2, cap2 = pipe_factory()
    later = DAY + timedelta(hours=cfg.NOTIFY_COOLDOWN_HOURS_P0 + 1)
    r = p2.process([_finding("spend_spike")], now=later)
    assert r.p0_sent == 1
    assert any(d.reason == "cooldown_elapsed" for d in r.sent)


# --- quiet hours -----------------------------------------------------------

def test_quiet_hours_window():
    assert is_quiet_hour(NIGHT) is True
    assert is_quiet_hour(DAY) is False


def test_p0_bypasses_quiet_hours_p1_defers(pipe_factory):
    p, cap = pipe_factory()
    findings = [_finding("runaway_agent_cost"), _finding("credential_in_unit_file", sev="HIGH")]
    r = p.process(findings, now=NIGHT)
    assert r.p0_sent == 1                       # P0 still fires overnight
    assert r.p1_sent == 0                       # P1 deferred
    assert any(d.reason == "quiet_hours_deferred" for d in r.suppressed)


# --- storm prevention ------------------------------------------------------

def test_rate_cap_aggregates_overflow(pipe_factory):
    p, cap = pipe_factory()
    n = cfg.NOTIFY_MAX_P0_PER_RUN + 4
    findings = [_finding("runaway_agent_cost", resource=f"wf{i}") for i in range(n)]
    r = p.process(findings, now=DAY)
    # cap individual messages + exactly one aggregate message
    assert len(cap) == cfg.NOTIFY_MAX_P0_PER_RUN + 1
    assert any("MORE EVENTS" in m for m in cap)
    # every overflow finding is recorded so it won't re-fire next run
    assert len(r.sent) == n


def test_p1_collapses_to_single_digest(pipe_factory):
    p, cap = pipe_factory()
    findings = [_finding("credential_in_unit_file", resource=f"svc{i}", sev="HIGH") for i in range(5)]
    r = p.process(findings, now=DAY)
    assert r.p1_sent == 5
    digests = [m for m in cap if "P1 digest" in m]
    assert len(digests) == 1


# --- failure handling + prime ---------------------------------------------

def test_send_failure_not_recorded(tmp_path):
    # failing sender -> finding NOT recorded, so it retries next run
    p = NotificationPipeline(send_fn=lambda t: False, persist=True,
                             state_path=tmp_path / "s.json", log_path=tmp_path / "l.jsonl",
                             incident_root=tmp_path)
    r = p.process([_finding("spend_spike")], now=DAY)
    assert r.send_failures >= 1
    assert r.p0_sent == 0
    p2 = NotificationPipeline(send_fn=lambda t: True, persist=True,
                              state_path=tmp_path / "s.json", log_path=tmp_path / "l.jsonl",
                              incident_root=tmp_path)
    r2 = p2.process([_finding("spend_spike")], now=DAY + timedelta(minutes=5))
    assert r2.p0_sent == 1   # retried because the failure wasn't recorded


def test_prime_marks_seen_without_sending(pipe_factory):
    p, cap = pipe_factory()
    findings = [_finding("runaway_agent_cost"), _finding("spend_spike")]
    n = p.prime(findings, now=DAY)
    assert n == 2
    assert len(cap) == 0                        # nothing sent on prime
    p2, cap2 = pipe_factory()
    r = p2.process(findings, now=DAY + timedelta(minutes=1))
    assert r.p0_sent == 0                       # primed -> suppressed
    assert len(cap2) == 0


def test_input_dedupe_same_id_once(pipe_factory):
    p, cap = pipe_factory()
    f = _finding("runaway_agent_cost")
    r = p.process([dict(f), dict(f), dict(f)], now=DAY)   # 3 copies, same identity
    assert r.p0_sent == 1
    assert len(cap) == 1


# --- push policy gate (silence impact-free activity) -----------------------

def test_activity_without_consequence_is_suppressed(pipe_factory):
    # deployment_event is P0 in config, but with no owner-facing consequence and no
    # graph context it must NOT push — demoted to the daily report.
    p, cap = pipe_factory()
    r = p.process([_finding("deployment_event", sev="MEDIUM")], now=DAY)
    assert r.p0_sent == 0 and len(cap) == 0
    assert any(d.reason == "no_consequence" for d in r.suppressed)


def test_subsystem_rebuild_without_consequence_suppressed(pipe_factory):
    p, cap = pipe_factory()
    r = p.process([_finding("subsystem_rebuild", sev="MEDIUM")], now=DAY)
    assert r.p0_sent == 0 and len(cap) == 0
    assert any(d.reason == "no_consequence" for d in r.suppressed)


def test_engineering_burst_without_consequence_suppressed(pipe_factory):
    p, cap = pipe_factory()
    r = p.process([_finding("engineering_burst", sev="MEDIUM")], now=DAY)
    assert r.p0_sent == 0 and len(cap) == 0


def test_self_dev_activity_suppressed(pipe_factory):
    # the tool's own dev/git activity is never an operational incident
    p, cap = pipe_factory()
    r = p.process([_finding("deployment_event", target="quartermaster")], now=DAY)
    assert r.p0_sent == 0 and len(cap) == 0
    assert any(d.reason == "self_activity" for d in r.suppressed)


def test_security_finding_still_pushes(pipe_factory):
    # intrinsic critical: the gate never suppresses a security finding
    p, cap = pipe_factory()
    r = p.process([_finding("port_exposed_publicly", sev="HIGH")], now=DAY)
    assert r.p0_sent == 1 and len(cap) == 1


def test_oom_finding_still_pushes(pipe_factory):
    # intrinsic critical: resource exhaustion always pages
    p, cap = pipe_factory()
    r = p.process([_finding("kernel_oom_kill", sev="CRITICAL")], now=DAY)
    assert r.p0_sent == 1 and len(cap) == 1


def test_no_incident_written_for_suppressed_activity(pipe_factory, tmp_path):
    # demoted activity must not generate a P0 incident report on disk
    p, _ = pipe_factory()
    p.process([_finding("deployment_event", resource="deploy1", sev="MEDIUM")], now=DAY)
    # incident_root is tmp_path; no dated dir / report should be written
    day_dir = tmp_path / DAY.strftime("%Y-%m-%d")
    assert not day_dir.exists()


# --- formatting ------------------------------------------------------------

def test_format_notification_structure():
    text = format_notification(_finding("runaway_agent_cost", title="Runaway $100"), "new")
    assert "P0" in text and "RUNAWAY AGENT COST" in text
    assert "Runaway $100" in text
    # internal dedup reasons (new, cooldown_elapsed, ...) are never user-facing
    assert "why:" not in text


def test_format_escapes_html():
    text = format_notification(_finding("spend_spike", title="a<b>&c"), "new")
    assert "&lt;b&gt;" in text and "&amp;" in text
