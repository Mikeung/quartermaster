"""Tests for deterministic explainability functions: reasoning_trace, operator_posture,
and the finding_events persistence layer."""

import sqlite3
from pathlib import Path

from memory.finding_store import (
    ACTIONABILITY_MAP,
    OPERATIONAL_RELEVANCE_MAP,
    FindingStore,
    compute_finding_id,
    operator_posture,
    reasoning_trace,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _store(tmp_path: Path) -> FindingStore:
    s = FindingStore(str(tmp_path / "test.db"))
    s.connect()
    return s


def _finding(
    finding_type: str = "kernel_oom_kill",
    severity: str = "HIGH",
    occurrence_count: int = 1,
    first_seen: str = "2026-05-23T00:00:00+00:00",
    last_seen: str = "2026-05-23T00:00:00+00:00",
    resource: str = "node",
) -> dict:
    return {
        "finding_type": finding_type,
        "severity": severity,
        "occurrence_count": occurrence_count,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "resource": resource,
        "evidence": [],
    }


def _upsert(store: FindingStore, finding_type: str = "kernel_oom_kill",
            severity: str = "HIGH", resource: str = "node") -> tuple[str, dict]:
    fid = compute_finding_id("vps", finding_type, resource, "host", "test_collector")
    row = store.upsert(
        finding_id=fid,
        target_id="vps",
        finding_type=finding_type,
        resource=resource,
        scope="host",
        severity=severity,
        collector_type="test_collector",
        title=f"Test {finding_type}",
    )
    return fid, row


# ── operator_posture() ────────────────────────────────────────────────────────


class TestOperatorPosture:
    def test_critical_always_immediate(self):
        f = _finding(severity="CRITICAL")
        assert operator_posture(f) == "immediate_attention"

    def test_high_high_actionability_immediate(self):
        # kernel_oom_kill: HIGH actionability
        f = _finding(finding_type="kernel_oom_kill", severity="HIGH")
        assert ACTIONABILITY_MAP["kernel_oom_kill"] == "high"
        assert operator_posture(f) == "immediate_attention"

    def test_high_medium_actionability_investigate(self):
        # repeated_service_restart: medium actionability
        f = _finding(finding_type="repeated_service_restart", severity="HIGH")
        assert ACTIONABILITY_MAP["repeated_service_restart"] == "medium"
        assert operator_posture(f) == "investigate"

    def test_medium_high_actionability_investigate(self):
        # monitor_stale: medium severity, high actionability
        f = _finding(finding_type="monitor_stale", severity="MEDIUM")
        assert ACTIONABILITY_MAP["monitor_stale"] == "high"
        assert operator_posture(f) == "investigate"

    def test_medium_medium_actionable_relevance_investigate(self):
        # repeated_service_restart: medium actionability, actionable relevance
        f = _finding(finding_type="repeated_service_restart", severity="MEDIUM")
        assert OPERATIONAL_RELEVANCE_MAP["repeated_service_restart"] == "actionable"
        assert operator_posture(f) == "investigate"

    def test_medium_medium_informational_relevance_monitor(self):
        # env_file_world_readable: medium actionability, informational relevance
        f = _finding(finding_type="world_readable_env_file", severity="MEDIUM")
        assert ACTIONABILITY_MAP["world_readable_env_file"] == "medium"
        assert OPERATIONAL_RELEVANCE_MAP["world_readable_env_file"] == "informational"
        assert operator_posture(f) == "monitor"

    def test_coverage_gap_informational_only(self):
        f = _finding(finding_type="coverage_gap", severity="LOW")
        assert ACTIONABILITY_MAP["coverage_gap"] == "low"
        assert operator_posture(f) == "informational_only"

    def test_unknown_type_defaults_gracefully(self):
        f = _finding(finding_type="unknown_new_type", severity="LOW")
        result = operator_posture(f)
        assert result in ("immediate_attention", "investigate", "monitor", "informational_only")

    def test_all_registered_finding_types_return_valid_posture(self):
        valid_postures = {"immediate_attention", "investigate", "monitor", "informational_only"}
        for ftype in ACTIONABILITY_MAP:
            for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                f = _finding(finding_type=ftype, severity=sev)
                result = operator_posture(f)
                assert result in valid_postures, f"{ftype}/{sev} returned '{result}'"


# ── reasoning_trace() ────────────────────────────────────────────────────────


class TestReasoningTrace:
    def test_returns_string(self):
        assert isinstance(reasoning_trace(_finding()), str)

    def test_trace_contains_rationale(self):
        f = _finding(finding_type="kernel_oom_kill")
        trace = reasoning_trace(f)
        assert "OOM" in trace or "kernel" in trace.lower() or "memory" in trace.lower()

    def test_trace_mentions_recurrence_when_count_gt_1(self):
        f = _finding(
            occurrence_count=5,
            first_seen="2026-05-20T00:00:00+00:00",
            last_seen="2026-05-23T00:00:00+00:00",
        )
        trace = reasoning_trace(f)
        assert "5" in trace or "times" in trace.lower()

    def test_trace_mentions_suppression_when_suppressed(self):
        # Suppressed: count >= 3 AND elapsed >= 24h
        f = _finding(
            occurrence_count=4,
            first_seen="2026-05-21T00:00:00+00:00",
            last_seen="2026-05-23T00:00:00+00:00",
        )
        trace = reasoning_trace(f)
        assert "suppressed" in trace.lower() or "stable known" in trace.lower()

    def test_no_suppression_mention_when_not_suppressed(self):
        f = _finding(occurrence_count=1)
        trace = reasoning_trace(f)
        assert "suppressed" not in trace.lower()

    def test_all_registered_types_produce_non_empty_trace(self):
        for ftype in ACTIONABILITY_MAP:
            f = _finding(finding_type=ftype)
            trace = reasoning_trace(f)
            assert len(trace) > 10, f"{ftype} returned empty/short trace"

    def test_unknown_type_gracefully_described(self):
        f = _finding(finding_type="mystery_type")
        trace = reasoning_trace(f)
        assert "mystery_type" in trace

    def test_trace_is_deterministic(self):
        f = _finding()
        assert reasoning_trace(f) == reasoning_trace(f)


# ── finding_events table ──────────────────────────────────────────────────────


class TestFindingEvents:
    def test_created_event_emitted_on_new_finding(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store)
        events = store.get_finding_events(fid)
        assert len(events) == 1
        assert events[0]["event_type"] == "created"
        assert "severity=HIGH" in events[0]["detail"]

    def test_escalated_event_emitted_on_severity_increase(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store, severity="LOW")
        _upsert_with_id(store, fid, severity="HIGH")
        events = store.get_finding_events(fid)
        types = [e["event_type"] for e in events]
        assert "escalated" in types
        escalation = next(e for e in events if e["event_type"] == "escalated")
        assert "LOW" in escalation["detail"] and "HIGH" in escalation["detail"]

    def test_no_event_on_same_severity_update(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store, severity="HIGH")
        _upsert_with_id(store, fid, severity="HIGH")
        events = store.get_finding_events(fid)
        event_types = [e["event_type"] for e in events]
        assert event_types.count("escalated") == 0

    def test_resolved_event_emitted_on_mark_resolved(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store)
        count = store.mark_resolved(set(), target_id="vps", collector_type="test_collector")
        assert count == 1
        events = store.get_finding_events(fid)
        types = [e["event_type"] for e in events]
        assert "resolved" in types

    def test_reactivated_event_on_resolution_then_reappearance(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store)
        store.mark_resolved(set(), target_id="vps", collector_type="test_collector")
        _upsert_with_id(store, fid, severity="HIGH")
        events = store.get_finding_events(fid)
        types = [e["event_type"] for e in events]
        assert "reactivated" in types

    def test_events_ordered_chronologically(self, tmp_path):
        store = _store(tmp_path)
        fid, _ = _upsert(store, severity="LOW")
        _upsert_with_id(store, fid, severity="HIGH")
        store.mark_resolved(set(), target_id="vps", collector_type="test_collector")
        events = store.get_finding_events(fid)
        assert events[0]["event_type"] == "created"
        assert events[-1]["event_type"] == "resolved"

    def test_get_finding_events_empty_for_unknown_id(self, tmp_path):
        store = _store(tmp_path)
        events = store.get_finding_events("fnd_does_not_exist")
        assert events == []

    def test_events_table_exists_in_db(self, tmp_path):
        _store(tmp_path)  # creates the db; we inspect its schema directly below
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "finding_events" in tables
        conn.close()


def _upsert_with_id(store: FindingStore, finding_id: str, severity: str) -> dict:
    """Re-upsert a finding with the same finding_id (for testing escalation/reactivation)."""
    return store.upsert(
        finding_id=finding_id,
        target_id="vps",
        finding_type="kernel_oom_kill",
        resource="node",
        scope="host",
        severity=severity,
        collector_type="test_collector",
        title="Test OOM",
    )
