"""Key→agent labels — parse, resolve, budget, and human_declared stickiness."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from economics.key_registry import (
    KeyLabel,
    key_node_id,
    load_budget,
    load_key_labels,
    resolve_key_owner,
)
from memory.graph_store import GraphStore

_NOW = datetime(2026, 6, 15, tzinfo=UTC)

_YAML = """
version: "1"
budget:
  period: monthly
  limit_usd: 200.0
  scope: all
keys:
  - provider: anthropic
    key_id: apikey_lesia
    key_hint: a1b2
    agent: repo:lesia
    agent_target: /srv/lesia
    shared: false
    evidence: "lesia/.env ends a1b2"
  - provider: openai
    key_id: ""
    agent: repo:seo-agent
"""


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "cost_advisor.yml"
    p.write_text(_YAML)
    return p


class TestLoad:
    def test_valid_entry_parsed_malformed_skipped(self, cfg_file):
        labels, errors = load_key_labels(cfg_file)
        assert len(labels) == 1
        assert labels[0].agent == "repo:lesia"
        assert any("key_id" in e for e in errors)  # the empty-key_id entry is named

    def test_missing_file_is_empty_not_error(self, tmp_path):
        labels, errors = load_key_labels(tmp_path / "nope.yml")
        assert labels == [] and errors == []

    def test_budget(self, cfg_file):
        b = load_budget(cfg_file)
        assert b["limit_usd"] == 200.0 and b["period"] == "monthly"

    def test_budget_absent(self, tmp_path):
        p = tmp_path / "c.yml"
        p.write_text("version: '1'\nkeys: []\n")
        assert load_budget(p) == {}


class TestResolve:
    def _labels(self):
        return [KeyLabel("anthropic", "apikey_lesia", "a1b2", "repo:lesia",
                         "/srv/lesia", False, "ev")]

    def test_match_by_key_id(self):
        assert resolve_key_owner("anthropic", "apikey_lesia", self._labels()).agent == "repo:lesia"

    def test_match_by_hint_suffix(self):
        assert resolve_key_owner("anthropic", "xxxxa1b2", self._labels()) is not None

    def test_provider_mismatch_is_none(self):
        assert resolve_key_owner("openai", "apikey_lesia", self._labels()) is None


class TestSticky:
    def test_key_node_human_declared_not_overwritten_by_scanner(self, tmp_path):
        store = GraphStore(str(tmp_path / "g.db"))
        store.connect()
        try:
            kid = key_node_id("anthropic", "apikey_lesia")
            store.upsert_node(target_id="external", builder_node_id=kid,
                              node_type="api_key", label="anthropic:a1b2",
                              collector_type="human_declared", now=_NOW)
            # a later scanner pass touches the same node
            store.upsert_node(target_id="external", builder_node_id=kid,
                              node_type="api_key", label="anthropic:a1b2",
                              collector_type="service_scanner", now=_NOW)
            node = next(n for n in store.get_active_nodes("external")
                        if n["builder_node_id"] == kid)
            assert node["collector_type"] == "human_declared"
        finally:
            store.disconnect()
