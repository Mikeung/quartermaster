"""Tests for the recommendations ("what to check") layer — cognition/check_mapper.

Discipline mirrors the consequence mapper: opt-in (graph_store=None -> None),
never raises, deterministic, and NEVER invents — an unmapped finding_type or an
unbindable placeholder yields no step rather than a guess.
"""

from __future__ import annotations

import textwrap

from cognition.check_mapper import get_check_steps, load_playbook


# A throwaway in-memory graph store with declared dependents for one node.
class _FakeGraph:
    def __init__(self, nodes=None, edges=None):
        self._nodes = nodes or []
        self._edges = edges or []

    def get_active_nodes(self, target_id=None):
        return list(self._nodes)

    def get_active_edges(self, target_id=None):
        return list(self._edges)

    def get_nodes_by_label(self, label, case_sensitive=False):
        return [n for n in self._nodes if n["label"].lower() == label.lower()]


def _oom(resource="node"):
    return {"finding_type": "kernel_oom_kill", "resource": resource, "target_id": "vps",
            "scope": "host", "collector_type": "survivability_scanner", "severity": "HIGH",
            "evidence": ["Memory RSS at kill: 3700 MB"]}


def _restart(unit="redis-server.service"):
    return {"finding_type": "repeated_service_restart", "resource": unit,
            "target_id": "vps", "scope": "host", "collector_type": "runtime_scanner"}


def _wre(path="/srv/seo-agent/.env"):
    return {"finding_type": "world_readable_env_file", "resource": path,
            "target_id": "vps", "scope": "host", "collector_type": "security_scanner"}


def _cred(unit="seo-agent.service"):
    return {"finding_type": "credential_in_unit_file", "resource": unit,
            "target_id": "vps", "scope": "host", "collector_type": "security_scanner"}


# --- contract --------------------------------------------------------------

def test_none_graph_store_skips():
    assert get_check_steps(_oom(), None) is None


def test_unmapped_type_yields_no_recommendation():
    # No rule for agent_burst -> None (valid, not invented).
    assert get_check_steps({"finding_type": "agent_burst", "resource": "lesia",
                            "target_id": "lesia"}, _FakeGraph()) is None


def test_never_raises_on_garbage_finding():
    assert get_check_steps({}, _FakeGraph()) is None
    assert get_check_steps({"finding_type": "kernel_oom_kill"}, _FakeGraph()) is not None


# --- the four seeded rules -------------------------------------------------

def test_oom_rule_renders_expected_steps():
    res = get_check_steps(_oom("next-server"), _FakeGraph())
    assert res is not None and res["finding_type"] == "kernel_oom_kill"
    checks = " ".join(s["check"] for s in res["steps"])
    # the diagnostic path we actually walked on 2026-06-08
    assert "constraint=CONSTRAINT_MEMCG" in checks      # scope
    assert "docker stats" in checks                     # pressure source
    assert "MemoryMax" in checks or "HostConfig.Memory" in checks  # containment
    assert "swapon" in checks or "free -h" in checks    # swap state
    # {process} bound from resource and substituted into the rationale
    assert any("next-server" in s["why"] for s in res["steps"])


def test_oom_preserves_go_template_braces():
    # the docker inspect Go template must survive intact (not mangled to {.Name})
    res = get_check_steps(_oom(), _FakeGraph())
    checks = " ".join(s["check"] for s in res["steps"])
    assert "{{.Name}}" in checks and "{{.HostConfig.Memory}}" in checks


def test_restart_rule_binds_unit_and_service():
    res = get_check_steps(_restart("redis-server.service"), _FakeGraph())
    checks = " ".join(s["check"] for s in res["steps"])
    assert "journalctl -u redis-server.service" in checks
    assert "redis-server" in checks  # {service} normalised


def test_world_readable_binds_file_path():
    res = get_check_steps(_wre("/srv/seo-agent/.env"), _FakeGraph())
    checks = " ".join(s["check"] for s in res["steps"])
    assert "/srv/seo-agent/.env" in checks
    assert "stat -c" in checks


def test_credential_binds_unit():
    res = get_check_steps(_cred("seo-agent.service"), _FakeGraph())
    checks = " ".join(s["check"] for s in res["steps"])
    assert "systemctl cat seo-agent.service" in checks


# --- dependents binding via the graph --------------------------------------

def test_dependents_step_appears_only_when_graph_has_dependents():
    # Without dependents, the {dependents} step is skipped.
    no_dep = get_check_steps(_restart(), _FakeGraph())
    assert not any("dependents" in s["check"].lower() for s in no_dep["steps"])

    # Build a graph where a redis node has one dependent (lesia).
    nodes = [
        {"node_id": "n_redis", "label": "redis-server", "target_id": "vps",
         "builder_node_id": "vps:redis-server"},
        {"node_id": "n_lesia", "label": "lesia", "target_id": "/srv/lesia",
         "builder_node_id": "repo:lesia"},
    ]
    edges = [{"source_node_id": "n_lesia", "target_node_id": "n_redis",
              "relationship": "DEPENDS_ON"}]
    res = get_check_steps(_restart("redis-server.service"), _FakeGraph(nodes, edges))
    dep_steps = [s for s in res["steps"] if "lesia" in s["check"]]
    assert dep_steps, "dependents step should render with the dependent label bound"


# --- determinism + operator-editability ------------------------------------

def test_deterministic():
    g = _FakeGraph()
    assert get_check_steps(_oom(), g) == get_check_steps(_oom(), g)


def test_unknown_placeholder_step_is_skipped(tmp_path):
    # A rule referencing a value we cannot bind must drop the step, not guess.
    pb = tmp_path / "pb.yml"
    pb.write_text(textwrap.dedent("""
        version: "1"
        rules:
          kernel_oom_kill:
            steps:
              - check: "Bindable: inspect {process}."
                why: "ok"
              - check: "Unbindable: look at {nonexistent_placeholder}."
                why: "should be skipped"
    """))
    res = get_check_steps(_oom("node"), _FakeGraph(), playbook_path=pb)
    assert len(res["steps"]) == 1
    assert "inspect node" in res["steps"][0]["check"]


def test_playbook_has_the_four_seeded_rules():
    rules = load_playbook()
    for ft in ("kernel_oom_kill", "repeated_service_restart",
               "world_readable_env_file", "credential_in_unit_file"):
        assert ft in rules
