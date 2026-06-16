"""Tests for the meaning-layer confirmation gate (step 3).

Covers the operationally important contract:
  - the review surface: what is pending, what is already confirmed/rejected, source
    precedence (llm_draft over derived), and needs-authoring detection
  - deterministic decision application: confirm / edit / reject / author / defer,
    provenance preservation, and validation errors
  - comment-preserving promotion into operational_graph.yml (targeted line replace)
  - the loader reading a confirmed block (value + provenance into the annotation)
  - rejection memory: the generators skip a previously-rejected slot
"""

from __future__ import annotations

import yaml

from cognition.meaning_confirmation import (
    apply_decisions,
    assemble_pending,
    is_confirmed,
    rejection_keys_from_doc,
)

# --------------------------------------------------------------------------- #
# fixtures: minimal proposed / drafted / operational_graph docs                #
# --------------------------------------------------------------------------- #

def _operational_graph():
    return {"nodes": [
        # confirmed (scalar) — never pending
        {"id": "repo:quartermaster", "target": "/opt/quartermaster",
         "consequence": "if down → no scan cycle", "owner_facing": True},
        # consequence open, owner_facing confirmed true
        {"id": "repo:lesia", "target": "/srv/lesia",
         "consequence": "unknown", "owner_facing": True},
        # both open
        {"id": "repo:seo-agent", "target": "/srv/seo-agent",
         "consequence": "unknown", "owner_facing": "unknown"},
        # consequence already confirmed via a structured block
        {"id": "repo:hdt-web", "target": "/srv/hdt-web",
         "consequence": {"value": "site down", "status": "confirmed"},
         "owner_facing": True},
    ]}


def _proposed():
    return {"nodes": [
        {"id": "repo:lesia", "proposals": {
            "produces": {"field": "produces", "value": "spend records read by quartermaster",
                         "evidence": "READS_FROM edge"},
            "consequence": {"field": "consequence", "value": "if down → no spend records read by quartermaster",
                            "source": "derived", "status": "proposed", "confidence": 0.7,
                            "derivation": "templated_from_produces", "evidence": "from produces"},
        }},
    ]}


def _drafted():
    return {"nodes": [
        {"id": "repo:lesia", "drafts": {
            "consequence": {"field": "consequence", "verdict": "determined",
                            "value": "if down → no spend data → economic observability degrades",
                            "source": "llm_draft", "status": "draft", "confidence": 0.9,
                            "reasoning": "spend feed lost", "facts_used": ["READS_FROM edge"]},
        }},
        {"id": "repo:seo-agent", "drafts": {
            "owner_facing": {"field": "owner_facing", "verdict": "uncertain", "value": "",
                             "source": "llm_draft", "status": "draft", "confidence": 0.5,
                             "reasoning": "facts thin", "facts_used": []},
            "consequence": {"field": "consequence", "verdict": "cannot_determine", "value": "",
                            "source": "llm_draft", "status": "draft", "confidence": 0.0,
                            "reasoning": "no output known", "facts_used": []},
        }},
    ]}


def _pending():
    return assemble_pending(_proposed(), _drafted(), _operational_graph())


def _by_key(entries):
    return {e.key: e for e in entries}


# --------------------------------------------------------------------------- #
# is_confirmed                                                                 #
# --------------------------------------------------------------------------- #

def test_is_confirmed_scalar_and_block():
    assert is_confirmed("if down → x")
    assert not is_confirmed("unknown")
    assert not is_confirmed(None)
    assert is_confirmed({"value": "x", "status": "confirmed"})
    assert not is_confirmed({"value": "unknown"})


# --------------------------------------------------------------------------- #
# assemble_pending                                                             #
# --------------------------------------------------------------------------- #

def test_pending_excludes_confirmed():
    keys = {e.key for e in _pending()}
    # confirmed scalar + confirmed block are absent
    assert ("repo:quartermaster", "consequence") not in keys
    assert ("repo:lesia", "owner_facing") not in keys           # owner_facing True
    assert ("repo:hdt-web", "consequence") not in keys          # confirmed block


def test_pending_prefers_llm_draft_over_derived():
    e = _by_key(_pending())[("repo:lesia", "consequence")]
    assert e.source == "llm_draft"
    assert "economic observability" in e.candidate_value
    # derived skeleton retained in the evidence trail (lineage)
    assert any("derived skeleton" in ev for ev in e.evidence)
    # produces surfaced as supporting evidence
    assert any(ev.startswith("[produces]") for ev in e.evidence)


def test_pending_needs_authoring_for_cannot_determine():
    p = _by_key(_pending())
    of = p[("repo:seo-agent", "owner_facing")]
    cons = p[("repo:seo-agent", "consequence")]
    assert of.needs_authoring and of.candidate_value == ""
    assert cons.needs_authoring and cons.verdict == "cannot_determine"


def test_pending_excludes_rejected():
    rk = {("repo:seo-agent", "consequence")}
    keys = {e.key for e in assemble_pending(_proposed(), _drafted(), _operational_graph(), rk)}
    assert ("repo:seo-agent", "consequence") not in keys
    assert ("repo:seo-agent", "owner_facing") in keys  # only that one slot rejected


# --------------------------------------------------------------------------- #
# apply_decisions                                                             #
# --------------------------------------------------------------------------- #

def test_confirm_preserves_provenance():
    pending = _pending()
    res = apply_decisions(pending, [
        {"node": "repo:lesia", "field": "consequence", "action": "confirm"},
    ], now="2026-06-06")
    assert len(res.promotions) == 1
    p = res.promotions[0]
    assert p.provenance == "llm_draft->confirmed"
    assert p.source == "llm_draft"
    assert "economic observability" in p.value
    assert "confirmed 2026-06-06 via llm_draft->confirmed" in p.evidence


def test_edit_provenance_and_value():
    res = apply_decisions(_pending(), [
        {"node": "repo:lesia", "field": "consequence", "action": "edit",
         "edited_value": "if down → quartermaster loses the spend feed"},
    ], now="2026-06-06")
    p = res.promotions[0]
    assert p.provenance == "llm_draft->edited->confirmed"
    assert p.value == "if down → quartermaster loses the spend feed"


def test_author_cannot_determine():
    res = apply_decisions(_pending(), [
        {"node": "repo:seo-agent", "field": "consequence", "action": "author",
         "authored_value": "if down → SEO content pipeline halts"},
    ], now="2026-06-06")
    p = res.promotions[0]
    assert p.provenance == "human_authored"
    assert p.source == "human_authored"
    assert p.value == "if down → SEO content pipeline halts"


def test_reject_records_rejection_and_audit():
    res = apply_decisions(_pending(), [
        {"node": "repo:seo-agent", "field": "owner_facing", "action": "reject"},
    ], now="2026-06-06")
    assert len(res.rejections) == 1
    assert res.rejections[0].node_id == "repo:seo-agent"
    assert not res.promotions
    assert any(a.action == "reject" for a in res.audit)


def test_confirm_empty_is_an_error():
    res = apply_decisions(_pending(), [
        {"node": "repo:seo-agent", "field": "consequence", "action": "confirm"},
    ], now="2026-06-06")
    assert not res.promotions
    assert any("cannot confirm an empty" in e for e in res.errors)


def test_edit_without_value_is_error():
    res = apply_decisions(_pending(), [
        {"node": "repo:lesia", "field": "consequence", "action": "edit", "edited_value": ""},
    ], now="2026-06-06")
    assert any("edit requires" in e for e in res.errors)


def test_defer_and_unknown_action():
    res = apply_decisions(_pending(), [
        {"node": "repo:lesia", "field": "consequence", "action": "defer"},
        {"node": "repo:seo-agent", "field": "owner_facing", "action": "frobnicate"},
    ], now="2026-06-06")
    assert ("repo:lesia", "consequence") in res.deferred
    assert any("unknown action" in e for e in res.errors)


def test_apply_is_deterministic():
    decisions = [{"node": "repo:lesia", "field": "consequence", "action": "confirm"}]
    a = apply_decisions(_pending(), decisions, now="2026-06-06")
    b = apply_decisions(_pending(), decisions, now="2026-06-06")
    assert [p.__dict__ for p in a.promotions] == [p.__dict__ for p in b.promotions]


# --------------------------------------------------------------------------- #
# promotion into operational_graph.yml (comment-preserving line replace)       #
# --------------------------------------------------------------------------- #

def test_promote_into_graph_preserves_file_and_loads():
    from cognition.meaning_confirmation import Promotion
    from scripts.confirm_meaning_layer import _promote_into_graph
    from scripts.load_operational_graph import _field_value_and_evidence

    text = (
        "version: \"1\"\n"
        "# a comment that must survive\n"
        "nodes:\n"
        "  - id: repo:lesia\n"
        "    target: /srv/lesia\n"
        "    liveness:\n"
        "      signal: service\n"
        "      detail: lesia.service\n"
        "    consequence: unknown\n"
        "    owner_facing: true\n"
        "  - id: repo:seo-agent\n"
        "    target: /srv/seo-agent\n"
        "    consequence: unknown\n"
        "    owner_facing: unknown\n"
    )
    prom = Promotion(node_id="repo:lesia", target="/srv/lesia", field="consequence",
                     value="if down → quartermaster loses spend feed", source="llm_draft",
                     provenance="llm_draft->confirmed", evidence="confirmed 2026-06-06",
                     confirmed_at="2026-06-06")
    new_text = _promote_into_graph(text, prom)
    # comment + the other node's scalar are untouched
    assert "# a comment that must survive" in new_text
    assert "  - id: repo:seo-agent" in new_text
    # it is valid YAML and the block carries provenance
    doc = yaml.safe_load(new_text)
    lesia = next(n for n in doc["nodes"] if n["id"] == "repo:lesia")
    assert isinstance(lesia["consequence"], dict)
    assert lesia["consequence"]["status"] == "confirmed"
    assert lesia["consequence"]["provenance"] == "llm_draft->confirmed"
    # the loader resolves it to (value, evidence-with-provenance)
    value, ev = _field_value_and_evidence(lesia["consequence"])
    assert value == "if down → quartermaster loses spend feed"
    assert "provenance=llm_draft->confirmed" in ev
    # the still-pending seo-agent scalar is unchanged
    seo = next(n for n in doc["nodes"] if n["id"] == "repo:seo-agent")
    assert seo["consequence"] == "unknown"


def test_promote_refuses_to_overwrite_block_scalar():
    from cognition.meaning_confirmation import Promotion
    from scripts.confirm_meaning_layer import _promote_into_graph
    text = (
        "nodes:\n"
        "  - id: repo:x\n"
        "    consequence: >\n"
        "      already authored multi-line\n"
        "    owner_facing: true\n"
    )
    prom = Promotion("repo:x", "vps", "consequence", "v", "derived",
                     "derived->confirmed", "ev", "2026-06-06")
    try:
        _promote_into_graph(text, prom)
        raise AssertionError("expected refusal to overwrite block scalar")
    except ValueError as e:
        assert "non-scalar" in str(e) or "block" in str(e)


# --------------------------------------------------------------------------- #
# loader: confirmed-block round trip                                           #
# --------------------------------------------------------------------------- #

def test_loader_field_value_and_evidence_forms():
    from scripts.load_operational_graph import _field_value_and_evidence
    # legacy scalar
    v, ev = _field_value_and_evidence("if down → x")
    assert v == "if down → x" and ev == "operator-declared"
    # confirmed block
    v, ev = _field_value_and_evidence(
        {"value": "if down → y", "status": "confirmed", "source": "derived",
         "provenance": "derived->confirmed", "confirmed_at": "2026-06-06", "evidence": "basis: z"})
    assert v == "if down → y"
    assert "status=confirmed" in ev and "provenance=derived->confirmed" in ev and "basis: z" in ev


# --------------------------------------------------------------------------- #
# rejection memory in the generators                                          #
# --------------------------------------------------------------------------- #

def test_rejection_keys_parsing():
    doc = {"rejections": [
        {"node": "repo:seo-agent", "field": "consequence"},
        {"node": "repo:x", "field": "owner_facing"},
        {"field": "incomplete"},  # missing node — ignored
    ]}
    assert rejection_keys_from_doc(doc) == {
        ("repo:seo-agent", "consequence"), ("repo:x", "owner_facing")}
    assert rejection_keys_from_doc(None) == set()


def test_proposer_skips_rejected_slot():
    from cognition.meaning_proposer import propose
    nodes = [{"node_id": "n:mem", "builder_node_id": "repo:mempalace",
              "target_id": "/srv/mempalace", "node_type": "declared",
              "collector_type": "human_declared", "resolved_at": None}]
    annotations = {"n:mem": {
        "liveness": {"value": '{"signal":"cron"}', "evidence": "crontab >> /var/log/x.log",
                     "collector_type": "human_declared"},
        "consequence": {"value": "unknown", "collector_type": "human_declared"},
        "owner_facing": {"value": "unknown", "collector_type": "human_declared"},
    }}
    rk = {("repo:mempalace", "consequence")}
    rep = propose(nodes, [], annotations, rejection_keys=rk)
    node = rep.nodes[0]
    assert all(p.field != "consequence" for p in node.proposals)
    assert "consequence" in node.previously_rejected


def test_drafter_skips_rejected_slot():
    from cognition.meaning_drafter import assemble_facts
    og = {"nodes": [{"id": "repo:seo-agent", "target": "/srv/seo-agent",
                     "liveness": {"signal": "service", "detail": "x", "evidence": "y"},
                     "consequence": "unknown", "owner_facing": "unknown"}]}
    rk = {("repo:seo-agent", "consequence")}
    facts = assemble_facts(og, {"nodes": []}, [], {}, rejection_keys=rk)
    nf = {f.builder_node_id: f for f in facts}["repo:seo-agent"]
    assert nf.needs_owner_facing       # still drafted
    assert not nf.needs_consequence    # rejected → skipped
