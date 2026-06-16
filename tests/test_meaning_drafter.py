"""Tests for the LLM meaning-layer drafter.

The drafter's only non-deterministic input is the injected ``llm_fn``. These tests
pass a FAKE llm_fn — no network, no API key — and verify the deterministic parts:
fact assembly (what to draft, confirmed slots skipped), prompt scoping, response
validation, and the inert-by-construction draft outputs.
"""

from __future__ import annotations

from cognition.meaning_drafter import (
    DRAFT_STATUS,
    LLM_DRAFT_SOURCE,
    assemble_facts,
    build_prompt,
    draft,
    parse_response,
)


def _operational_graph():
    return {
        "nodes": [
            # fully confirmed — must be skipped entirely
            {"id": "repo:quartermaster", "target": "/opt/quartermaster",
             "liveness": {"signal": "cron", "detail": "scans", "evidence": "crontab"},
             "consequence": "if down → no scan cycle", "owner_facing": True},
            # consequence confirmed, owner_facing confirmed false — skip
            {"id": "service:postgresql", "target": "vps",
             "liveness": {"signal": "service", "detail": "pg", "evidence": "systemctl"},
             "consequence": "if down → HUMINT fails", "owner_facing": False},
            # owner_facing confirmed true, consequence open → draft consequence only
            {"id": "repo:hdt-web", "target": "/srv/hdt-web",
             "liveness": {"signal": "service", "detail": "Next.js site", "evidence": "systemctl"},
             "consequence": "unknown", "owner_facing": True},
            # both open → draft both
            {"id": "repo:seo-agent", "target": "/srv/seo-agent",
             "liveness": {"signal": "service", "detail": "seo-agent.service running",
                          "evidence": "systemctl"},
             "consequence": "unknown", "owner_facing": "unknown"},
            # both open + has a derived consequence skeleton → consequence is an upgrade
            {"id": "repo:mempalace", "target": "/srv/mempalace",
             "liveness": {"signal": "cron", "detail": "metrics sweep hourly",
                          "evidence": "crontab >> /var/log/seo-agent-sweep.log"},
             "consequence": "unknown", "owner_facing": "unknown"},
        ]
    }


def _proposed():
    return {
        "nodes": [
            {"id": "repo:mempalace", "target": "/srv/mempalace",
             "proposals": {
                 "produces": {"field": "produces",
                              "value": "/var/log/seo-agent-sweep.log (output file)",
                              "evidence": "redirect >> /var/log/seo-agent-sweep.log"},
                 "consequence": {"field": "consequence",
                                 "value": "if down → no /var/log/seo-agent-sweep.log (output file)",
                                 "evidence": "templated from produces"},
             }},
        ]
    }


def _edges():
    return [
        {"source_node_id": "n:tgbot", "target_node_id": "n:mempalace",
         "relationship": "USES_VENV", "resolved_at": None,
         "evidence": [{"detail": "tgbot runs under mempalace venv"}]},
    ]


def _label_of():
    return {"n:tgbot": "service:tgbot", "n:mempalace": "repo:mempalace"}


def test_assemble_skips_confirmed_and_scopes_needs():
    facts = assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())
    by_id = {f.builder_node_id: f for f in facts}
    # confirmed nodes absent
    assert "repo:quartermaster" not in by_id
    assert "service:postgresql" not in by_id
    # hdt-web: consequence only (owner_facing confirmed true)
    assert by_id["repo:hdt-web"].needs_consequence
    assert not by_id["repo:hdt-web"].needs_owner_facing
    # seo-agent: both
    assert by_id["repo:seo-agent"].needs_owner_facing
    assert by_id["repo:seo-agent"].needs_consequence
    # mempalace: skeleton present → upgrade
    assert by_id["repo:mempalace"].consequence_is_upgrade
    assert "seo-agent-sweep.log" in by_id["repo:mempalace"].consequence_skeleton


def test_facts_include_produces_and_edges():
    facts = {f.builder_node_id: f for f in
             assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())}
    mem_lines = "\n".join(facts["repo:mempalace"].fact_lines())
    assert "derived produces" in mem_lines
    assert "USES_VENV" in mem_lines  # edge fact surfaced


def test_prompt_requests_only_needed_fields():
    facts = {f.builder_node_id: f for f in
             assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())}
    _sys, user = build_prompt(facts["repo:hdt-web"])
    assert "owner_facing" not in user  # confirmed → not requested
    assert "consequence" in user
    _sys2, user2 = build_prompt(facts["repo:seo-agent"])
    assert "owner_facing" in user2 and "consequence" in user2


def test_parse_validates_verdicts_and_clamps_confidence():
    facts = {f.builder_node_id: f for f in
             assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())}
    nf = facts["repo:seo-agent"]
    drafts, errors = parse_response(nf, {
        "owner_facing": {"verdict": "FALSE", "confidence": 2.5, "reasoning": "internal",
                         "facts_used": ["liveness detail: seo-agent.service running"]},
        "consequence": {"verdict": "determined", "value": "if down → no SEO worker",
                        "confidence": 0.6, "reasoning": "x", "facts_used": ["a"]},
    })
    assert errors == []
    of = next(d for d in drafts if d.field == "owner_facing")
    assert of.verdict == "false" and of.confidence == 1.0  # clamped
    assert of.source == LLM_DRAFT_SOURCE and of.status == DRAFT_STATUS


def test_parse_rejects_bad_verdict_and_empty_determined():
    facts = {f.builder_node_id: f for f in
             assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())}
    nf = facts["repo:seo-agent"]
    _drafts, errors = parse_response(nf, {
        "owner_facing": {"verdict": "maybe", "confidence": 0.5},
        "consequence": {"verdict": "determined", "value": "", "confidence": 0.5},
    })
    assert any("invalid owner_facing verdict" in e for e in errors)
    assert any("value empty" in e for e in errors)


def test_cannot_determine_is_accepted_with_empty_value():
    facts = {f.builder_node_id: f for f in
             assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())}
    nf = facts["repo:seo-agent"]
    drafts, errors = parse_response(nf, {
        "owner_facing": {"verdict": "uncertain", "confidence": 0.2, "reasoning": "thin",
                         "facts_used": []},
        "consequence": {"verdict": "cannot_determine", "value": "", "confidence": 0.1,
                        "reasoning": "facts don't say what seo-agent outputs", "facts_used": []},
    })
    assert errors == []
    of = next(d for d in drafts if d.field == "owner_facing")
    cons = next(d for d in drafts if d.field == "consequence")
    assert of.verdict == "uncertain" and of.value == ""
    assert cons.verdict == "cannot_determine" and cons.value == ""


def test_draft_isolates_llm_failure_per_node():
    facts = assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())

    def flaky(system, user):
        if "node id: repo:seo-agent" in user:
            raise RuntimeError("boom")
        return {"owner_facing": {"verdict": "false", "confidence": 0.5, "reasoning": "r",
                                 "facts_used": []},
                "consequence": {"verdict": "cannot_determine", "value": "", "confidence": 0.1,
                                "reasoning": "r", "facts_used": []}}

    report = draft(facts, flaky, model="fake")
    by_id = {n.builder_node_id: n for n in report.nodes}
    assert any("boom" in e for e in by_id["repo:seo-agent"].errors)
    # other nodes still drafted despite one failure
    assert by_id["repo:hdt-web"].drafts


def test_full_draft_with_fake_llm_is_inert():
    facts = assemble_facts(_operational_graph(), _proposed(), _edges(), _label_of())

    def fake(system, user):
        resp = {}
        if "owner_facing" in user:
            resp["owner_facing"] = {"verdict": "false", "confidence": 0.7,
                                    "reasoning": "internal log only", "facts_used": ["x"]}
        if "consequence" in user:
            resp["consequence"] = {"verdict": "determined",
                                   "value": "if down → no metrics collected → unmonitored",
                                   "confidence": 0.6, "reasoning": "y", "facts_used": ["x"]}
        return resp

    report = draft(facts, fake, model="fake")
    for n in report.nodes:
        for d in n.drafts:
            assert d.source == LLM_DRAFT_SOURCE
            assert d.status == DRAFT_STATUS
    s = report.summary()
    assert s["consequence_drafts"] >= 1
    assert s["errors"] == 0
