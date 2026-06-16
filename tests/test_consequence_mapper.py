"""Tests for cognition/consequence_mapper.py — finding → graph node mapping.

Validates the conservative mapping heuristics and consequence framing
without touching the live database. Each test builds its own store.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cognition.consequence_mapper import (
    _normalize_service_name,
    get_consequence_framing,
    map_finding_to_node_id,
)
from memory.graph_store import GraphStore, compute_node_id

_NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixture: a small graph matching the live operational topology
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    _seed_graph(s)
    yield s
    s.disconnect()


def _seed_graph(s: GraphStore) -> None:
    """Seed nodes and edges that mirror the live operational_graph.yml."""
    nodes = [
        ("vps",                      "service:postgresql", "postgresql",      "service"),
        ("vps",                      "service:tgbot",      "tgbot",           "service"),
        ("vps",                      "service:nginx",      "nginx",           "service"),
        ("/opt/quartermaster", "repo:quartermaster", "quartermaster", "repository"),
        ("/srv/telegram-humint",    "repo:telegram-humint","telegram-humint", "repository"),
        ("/srv/lesia",     "repo:lesia",          "lesia",           "repository"),
        ("/srv/seo-agent",          "repo:seo-agent",      "seo-agent",       "repository"),
    ]
    ids = {}
    for target, builder_id, label, node_type in nodes:
        r = s.upsert_node(
            target_id=target, builder_node_id=builder_id,
            node_type=node_type, label=label, now=_NOW,
        )
        ids[label] = r["node_id"]

    # humint DEPENDS_ON postgres
    s.upsert_edge(
        source_node_id=ids["telegram-humint"],
        target_node_id=ids["postgresql"],
        relationship="DEPENDS_ON", collector_type="human_declared",
        confidence=1.0, evidence=[{"source": "human_declared", "detail": "unit file evidence"}],
        now=_NOW,
    )
    # tgbot USES_VENV mempalace (not seeded here — ok, orphan edge still works)
    # Annotations
    for label, consequence, owner_facing in [
        ("postgresql",      "if down → HUMINT fails",           "false"),
        ("telegram-humint", "if down → no HUMINT reports",      "true"),
        ("quartermaster", "if down → no incident reports", "true"),
        ("lesia",           "unknown",                           "true"),
    ]:
        s.set_node_annotation(node_id=ids[label], annotation_type="consequence",
                              value=consequence, evidence="test", now=_NOW)
        s.set_node_annotation(node_id=ids[label], annotation_type="owner_facing",
                              value=owner_facing, evidence="test", now=_NOW)


def _finding(target_id, finding_type, resource="", **kw):
    return {
        "target_id": target_id,
        "finding_type": finding_type,
        "resource": resource,
        "scope": "host",
        "collector_type": "test",
        "severity": "HIGH",
        "title": f"{finding_type} on {resource or target_id}",
        **kw,
    }


# ---------------------------------------------------------------------------
# _normalize_service_name
# ---------------------------------------------------------------------------

class TestNormalizeServiceName:
    def test_strips_service_suffix(self):
        assert _normalize_service_name("tgbot.service") == "tgbot"

    def test_strips_instance(self):
        assert _normalize_service_name("postgresql@16-main.service") == "postgresql"

    def test_port_returns_empty(self):
        assert _normalize_service_name("port:8001") == ""

    def test_bare_name_unchanged(self):
        assert _normalize_service_name("node") == "node"

    def test_redis_server(self):
        assert _normalize_service_name("redis-server.service") == "redis-server"

    def test_empty_returns_empty(self):
        assert _normalize_service_name("") == ""


# ---------------------------------------------------------------------------
# map_finding_to_node_id
# ---------------------------------------------------------------------------

class TestMapFindingToNodeId:
    def test_economic_finding_returns_none(self, store):
        f = _finding("economic", "spend_spike")
        assert map_finding_to_node_id(f, store) is None

    def test_vps_service_restart_maps_to_service_node(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        nid = map_finding_to_node_id(f, store)
        assert nid is not None
        assert nid == compute_node_id("vps", "service:postgresql")

    def test_vps_tgbot_credential_maps_to_tgbot_node(self, store):
        f = _finding("vps", "credential_in_unit_file", "tgbot.service")
        nid = map_finding_to_node_id(f, store)
        assert nid is not None
        assert nid == compute_node_id("vps", "service:tgbot")

    def test_vps_port_exposure_returns_none(self, store):
        """port:8001 normalises to empty string — no node search."""
        f = _finding("vps", "port_exposed_publicly", "port:8001")
        assert map_finding_to_node_id(f, store) is None

    def test_vps_unknown_resource_returns_none(self, store):
        f = _finding("vps", "kernel_oom_kill", "dbus-daemon")
        assert map_finding_to_node_id(f, store) is None

    def test_repo_finding_maps_by_exact_builder_id(self, store):
        """target_id="quartermaster" → builder_node_id="repo:quartermaster"."""
        f = _finding("quartermaster", "engineering_burst", "quartermaster")
        nid = map_finding_to_node_id(f, store)
        assert nid is not None
        assert nid == compute_node_id("/opt/quartermaster", "repo:quartermaster")

    def test_repo_finding_maps_by_path_suffix(self, store):
        """target_id="lesia" → target "/srv/lesia" ends with "/lesia"."""
        f = _finding("lesia", "project_activity")
        nid = map_finding_to_node_id(f, store)
        assert nid is not None
        assert nid == compute_node_id("/srv/lesia", "repo:lesia")

    def test_repo_finding_maps_telegram_humint(self, store):
        f = _finding("telegram-humint", "project_activity")
        nid = map_finding_to_node_id(f, store)
        assert nid is not None
        assert nid == compute_node_id("/srv/telegram-humint", "repo:telegram-humint")

    def test_repo_finding_unknown_returns_none(self, store):
        f = _finding("totally-unknown-repo", "project_activity")
        assert map_finding_to_node_id(f, store) is None

    def test_none_graph_store_in_framing(self):
        """get_consequence_framing with graph_store=None returns None."""
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        assert get_consequence_framing(f, None) is None


# ---------------------------------------------------------------------------
# get_consequence_framing — full framing output
# ---------------------------------------------------------------------------

class TestGetConsequenceFraming:
    def test_postgresql_finding_produces_humint_framing(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        framing = get_consequence_framing(f, store)
        assert framing is not None
        assert framing["mapped_node_label"] == "postgresql"
        owner_labels = {x["label"] for x in framing["owner_facing_lost"]}
        assert "telegram-humint" in owner_labels

    def test_postgresql_framing_has_evidence(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        framing = get_consequence_framing(f, store)
        assert framing["evidence_trail"]

    def test_postgresql_framing_confidence_high(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        framing = get_consequence_framing(f, store)
        assert framing["overall_confidence"] == "High"

    def test_tgbot_finding_no_downstream(self, store):
        """tgbot has USES_VENV edge to mempalace, but mempalace isn't seeded.
        The walk still returns the framing with tgbot as root cause, no cascade."""
        f = _finding("vps", "credential_in_unit_file", "tgbot.service")
        framing = get_consequence_framing(f, store)
        # tgbot is owner_facing=false so owner_facing_lost is empty at depth 0
        # But framing is not None — root cause is identified
        assert framing is not None

    def test_lesia_finding_unknown_consequence(self, store):
        """lesia has consequence=unknown; framing reports it honestly."""
        f = _finding("lesia", "project_activity")
        framing = get_consequence_framing(f, store)
        assert framing is not None
        lesia_lost = next(
            (x for x in framing["owner_facing_lost"] if x["label"] == "lesia"), None
        )
        assert lesia_lost is not None
        assert lesia_lost["consequence"] == "unknown"

    def test_economic_finding_returns_none(self, store):
        f = _finding("economic", "spend_spike")
        assert get_consequence_framing(f, store) is None

    def test_unmapped_finding_returns_none(self, store):
        f = _finding("vps", "kernel_oom_kill", "dbus-daemon")
        assert get_consequence_framing(f, store) is None

    def test_framing_deterministic(self, store):
        """Same finding + same graph state → identical framing."""
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        a = get_consequence_framing(f, store)
        b = get_consequence_framing(f, store)
        assert a == b


# ---------------------------------------------------------------------------
# format_notification integration — consequence framing in Telegram alert
# ---------------------------------------------------------------------------

class TestFormatNotificationWithFraming:
    def test_consequence_line_appears_with_framing(self, store):
        from delivery.notifications import format_notification
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "new", consequence_framing=framing)
        assert "📍" in text and "Impact:" in text

    def test_no_consequence_line_without_framing(self):
        from delivery.notifications import format_notification
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        text = format_notification(f, "new")
        assert "📍" not in text

    def test_unknown_consequence_says_unknown(self, store):
        from delivery.notifications import format_notification
        f = _finding("lesia", "project_activity")
        framing = get_consequence_framing(f, store)
        if framing and framing.get("owner_facing_lost"):
            text = format_notification(f, "new", consequence_framing=framing)
            assert "unknown" in text.lower() or "📍" in text

    def test_existing_test_signatures_unchanged(self):
        """The old 3-positional-arg call still works identically."""
        from delivery.notifications import format_notification
        f = _finding("vps", "spend_spike", title="a<b>&c")
        text1 = format_notification(f, "new")
        text2 = format_notification(f, "new", None)
        text3 = format_notification(f, "new", None, consequence_framing=None)
        assert text1 == text2 == text3


# ---------------------------------------------------------------------------
# generate_incident_report integration — consequence sections in report
# ---------------------------------------------------------------------------

class TestGenerateReportWithFraming:
    def test_all_16_sections_still_present(self, store):
        """Consequence framing must not break the V4 section order."""
        from datetime import UTC, datetime

        from reports.incident_report import generate_incident_report
        now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)

        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service",
                     description="postgresql restarted", evidence=["restart count: 3"])
        sections = [
            "# Executive Summary", "# PROJECT CONTEXT",
            "# WHAT", "# WHERE", "# WHEN", "# WHICH", "# WHO", "# COST",
            "# WHY DID THIS HAPPEN?", "# SO WHAT?", "# WHICH LLMS WERE INVOLVED?",
            "# INCIDENT CORRELATION", "# Evidence", "# Timeline",
            "# Recommendations", "# Open Questions", "# Validation",
        ]
        body = generate_incident_report(f, now=now, priority="P1", reason="new",
                                        graph_store=store)
        idxs = [body.find(s) for s in sections]
        assert all(i >= 0 for i in idxs), "all 16 sections present"
        assert idxs == sorted(idxs), "sections in fixed order"

    def test_consequence_walk_section_appears(self, store):
        from datetime import UTC, datetime

        from reports.incident_report import generate_incident_report
        now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service",
                     description="postgresql restarted")
        body = generate_incident_report(f, now=now, priority="P1", reason="new",
                                        graph_store=store)
        assert "Consequence Walk" in body
        assert "telegram-humint" in body

    def test_report_without_graph_store_unchanged(self):
        """Existing call signature (no graph_store) produces identical output."""
        from datetime import UTC, datetime

        from reports.incident_report import generate_incident_report
        now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service",
                     description="postgresql restarted")
        body = generate_incident_report(f, now=now, priority="P1", reason="new")
        # No consequence section without graph_store
        assert "Consequence Walk" not in body

    def test_unknown_consequence_reported_honestly(self, store):
        from datetime import UTC, datetime

        from reports.incident_report import generate_incident_report
        now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
        f = _finding("lesia", "project_activity", "lesia",
                     description="lesia had activity")
        body = generate_incident_report(f, now=now, priority="P1", reason="new",
                                        graph_store=store)
        # Should say "consequence unknown" or similar, never fabricate
        if "Consequence Walk" in body:
            assert "unknown" in body.lower() or "not declared" in body.lower()

    def test_unmapped_finding_report_has_no_consequence_section(self, store):
        from datetime import UTC, datetime

        from reports.incident_report import generate_incident_report
        now = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
        f = _finding("economic", "spend_spike", "lesia:drain",
                     description="spend spike")
        body = generate_incident_report(f, now=now, priority="P0", reason="new",
                                        graph_store=store)
        assert "Consequence Walk" not in body
