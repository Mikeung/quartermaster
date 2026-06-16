"""Cost investigation — candidates with confidence, two resolutions, never fabricates."""

from __future__ import annotations

from datetime import UTC, datetime

from cognition.cost_investigation import investigate_bucket
from economics.connection_evidence import Connection

_TS = datetime(2026, 6, 15, 12, 0, tzinfo=UTC).isoformat()


def _conn(proc, pid, provider):
    return Connection(proc, pid, "1.2.3.4", 443, provider, _TS)


def _bucket(**kw):
    base = {"provider": "anthropic", "key_id": "apikey_x", "key_hint": "…a1b2",
            "cost_usd": 30.0, "reason": "unlabelled provider key", "shared_label": None,
            "when_first": "2026-06-14", "when_last": "2026-06-15"}
    base.update(kw)
    return base


class TestCandidates:
    def test_single_candidate_medium_and_maps_agent(self):
        inv = investigate_bucket(
            _bucket(), [_conn("python3.12", 4242, "anthropic")],
            process_to_agent={"python3.12": "lesia"},
        )
        assert len(inv["candidates"]) == 1
        c = inv["candidates"][0]
        assert c["agent"] == "lesia" and c["confidence"] == "Medium"
        assert inv["confidence"] == "Medium"
        assert "candidate" in inv["summary"].lower()

    def test_multiple_candidates_low_and_isolate_offered(self):
        inv = investigate_bucket(
            _bucket(),
            [_conn("python3.12", 1, "anthropic"), _conn("node", 2, "anthropic")],
        )
        assert len(inv["candidates"]) == 2
        assert inv["confidence"] == "Low"
        actions = {r["action"] for r in inv["resolutions"]}
        assert "isolate_agent_key" in actions

    def test_no_connection_no_fabricated_owner(self):
        inv = investigate_bucket(_bucket(), [])
        assert inv["candidates"] == []
        assert inv["confidence"] == "Low"
        assert any("no on-box process" in e for e in inv["evidence"])

    def test_unmapped_process_has_no_agent(self):
        inv = investigate_bucket(
            _bucket(), [_conn("mystery-proc", 7, "anthropic")], process_to_agent={},
        )
        assert inv["candidates"][0]["agent"] is None


class TestResolutions:
    def test_label_once_always_offered(self):
        inv = investigate_bucket(_bucket(), [])
        assert inv["resolutions"][0]["action"] == "label_key_once"
        assert "human_declared" in inv["resolutions"][0]["detail"]
        assert "NOT a new key" in inv["resolutions"][0]["detail"]

    def test_shared_bucket_offers_isolate(self):
        inv = investigate_bucket(
            _bucket(reason="shared key — cannot split 1:1", shared_label="repo:seo-agent"),
            [],
        )
        actions = {r["action"] for r in inv["resolutions"]}
        assert actions == {"label_key_once", "isolate_agent_key"}

    def test_deterministic(self):
        conns = [_conn("python3.12", 4242, "anthropic")]
        a = investigate_bucket(_bucket(), conns, process_to_agent={"python3.12": "lesia"})
        b = investigate_bucket(_bucket(), conns, process_to_agent={"python3.12": "lesia"})
        assert a == b
