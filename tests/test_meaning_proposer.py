"""Tests for the deterministic meaning-layer proposer.

Covers the contract that matters operationally:
  - derivations fire only where facts support them (cron redirect, inbound READS_FROM)
  - consequence is templated ONLY from a derived produces
  - human-confirmed slots are never re-derived or overwritten (incl. the 4
    hand-authored consequences)
  - owner_facing is never auto-derived
  - the pass is deterministic (same facts → identical output)
  - topology noise (port/framework nodes) is out of scope
"""

from __future__ import annotations

import json

from cognition.meaning_proposer import propose


def _node(builder_id, target, node_type="declared", collector="human_declared"):
    return {
        "node_id": f"nid::{builder_id}",
        "builder_node_id": builder_id,
        "target_id": target,
        "node_type": node_type,
        "collector_type": collector,
        "resolved_at": None,
    }


def _ann(value, evidence="", collector="human_declared"):
    return {"value": value, "evidence": evidence, "collector_type": collector, "set_at": "t"}


def _liveness_ann(signal, detail="", evidence="", collector="human_declared"):
    return _ann(
        json.dumps({"signal": signal, "detail": detail, "max_age_hours": "unknown"}),
        evidence=evidence,
        collector=collector,
    )


def _fixture():
    """A compact mirror of the real graph: quartermaster reads from lesia; mempalace cron
    redirects to a log; quartermaster has a hand-authored consequence; nginx has nothing."""
    nodes = [
        _node("repo:quartermaster", "/opt/quartermaster"),
        _node("repo:lesia", "/srv/lesia"),
        _node("repo:mempalace", "/srv/mempalace"),
        _node("service:nginx", "vps"),
        # topology noise that must be ignored:
        _node("port:5432", "/srv/lesia", node_type="port", collector="topology_builder"),
        _node("framework:uvicorn", "/srv/lesia", node_type="framework",
              collector="topology_builder"),
    ]
    edges = [
        {
            "source_node_id": "nid::repo:quartermaster",
            "target_node_id": "nid::repo:lesia",
            "relationship": "READS_FROM",
            "confidence": 0.7,
            "resolved_at": None,
            "evidence": [
                {"source": "human_declared", "detail": "import_spend.py reads data/spend/*.jsonl"},
            ],
        },
        {
            # SCANS must NOT be treated as a producing relationship.
            "source_node_id": "nid::repo:quartermaster",
            "target_node_id": "nid::repo:mempalace",
            "relationship": "SCANS",
            "confidence": 1.0,
            "resolved_at": None,
            "evidence": [{"source": "human_declared", "detail": "quartermaster scans mempalace"}],
        },
    ]
    annotations = {
        "nid::repo:quartermaster": {
            "liveness": _liveness_ann("cron", "scheduled_scan every 6h", "crontab: scheduled_scan.py"),
            "consequence": _ann("if down → no scan cycle, no incident reports", "operator-declared"),
            "owner_facing": _ann("true", "operator-declared"),
        },
        "nid::repo:lesia": {
            "liveness": _liveness_ann("service", "lesia.service uvicorn 7600", "systemctl: lesia.service"),
            "consequence": _ann("unknown", "operator-declared"),
            "owner_facing": _ann("true", "operator-declared"),
        },
        "nid::repo:mempalace": {
            "liveness": _liveness_ann(
                "cron", "metrics_sweep_job hourly",
                "crontab: ... metrics_sweep_job() >> /var/log/seo-agent-sweep.log",
            ),
            "consequence": _ann("unknown", "operator-declared"),
            "owner_facing": _ann("unknown", "operator-declared"),
        },
        "nid::service:nginx": {
            "liveness": _liveness_ann("service", "nginx.service", "systemctl: nginx.service"),
            "consequence": _ann("unknown", "operator-declared"),
            "owner_facing": _ann("false", "operator-declared"),
        },
    }
    return nodes, edges, annotations


def _by_id(report):
    return {n.builder_node_id: n for n in report.nodes}


def _proposal(node_proposal, field):
    for p in node_proposal.proposals:
        if p.field == field:
            return p
    return None


def test_scope_excludes_topology_noise():
    report = propose(*_fixture())
    ids = {n.builder_node_id for n in report.nodes}
    assert ids == {
        "repo:quartermaster", "repo:lesia", "repo:mempalace", "service:nginx",
    }
    assert not any(i.startswith(("port:", "framework:")) for i in ids)


def test_cron_redirect_produces_and_consequence():
    report = _by_id(propose(*_fixture()))
    mem = report["repo:mempalace"]
    prod = _proposal(mem, "produces")
    assert prod is not None
    assert prod.derivation == "cron_output_redirect"
    assert "/var/log/seo-agent-sweep.log" in prod.value
    assert prod.source == "derived" and prod.status == "proposed"

    cons = _proposal(mem, "consequence")
    assert cons is not None
    assert cons.derivation == "templated_from_produces"
    assert cons.value.startswith("if down → no ")
    assert "/var/log/seo-agent-sweep.log" in cons.value


def test_inbound_reads_from_produces():
    report = _by_id(propose(*_fixture()))
    lesia = report["repo:lesia"]
    prod = _proposal(lesia, "produces")
    assert prod is not None
    assert prod.derivation == "incoming_reads_from"
    assert prod.confidence == 0.7  # inherited from the edge
    assert "repo:quartermaster" in prod.value
    assert _proposal(lesia, "consequence") is not None


def test_scans_is_not_a_producing_relationship():
    # mempalace's only inbound edge is SCANS; its produces must come from the cron
    # redirect, never from being scanned.
    report = _by_id(propose(*_fixture()))
    prod = _proposal(report["repo:mempalace"], "produces")
    assert prod.derivation == "cron_output_redirect"


def test_hand_authored_consequence_untouched():
    report = _by_id(propose(*_fixture()))
    quartermaster = report["repo:quartermaster"]
    # No consequence proposal — the slot is human-confirmed.
    assert _proposal(quartermaster, "consequence") is None
    assert "consequence" in quartermaster.untouched_human
    assert "consequence" not in quartermaster.remaining_unknown


def test_owner_facing_never_derived():
    report = propose(*_fixture())
    for n in report.nodes:
        assert _proposal(n, "owner_facing") is None
    # mempalace's owner_facing is open → it must be flagged for the LLM/human pass.
    mem = _by_id(report)["repo:mempalace"]
    assert "owner_facing" in mem.remaining_unknown


def test_no_facts_means_no_proposal():
    report = _by_id(propose(*_fixture()))
    nginx = report["service:nginx"]
    assert nginx.proposals == []
    assert "consequence" in nginx.remaining_unknown
    # owner_facing=false is human-confirmed → untouched, not "remaining unknown".
    assert "owner_facing" in nginx.untouched_human
    assert "owner_facing" not in nginx.remaining_unknown


def test_liveness_human_signals_never_overwritten():
    report = propose(*_fixture())
    for n in report.nodes:
        assert _proposal(n, "liveness") is None
        assert "liveness" in n.untouched_human


def test_deterministic_repeatable():
    a = propose(*_fixture()).to_dict()
    b = propose(*_fixture()).to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_summary_counts():
    s = propose(*_fixture()).summary()
    assert s["meaning_nodes"] == 4
    assert s["nodes_with_proposal"] == 2
    assert s["proposals_by_field"] == {"produces": 2, "consequence": 2}
