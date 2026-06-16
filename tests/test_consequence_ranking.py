"""Tests for consequence-aware severity ranking.

Validates:
  - A finding with owner-facing loss outranks an identical-type finding with none
  - A finding with structural cascade gets MEDIUM floor (regardless of base LOW)
  - A finding that maps to no node is unchanged
  - Consequence severity never lowers the base severity
  - The notification badge shows escalation [BASE → EFFECTIVE] when escalated
  - The notification badge is unchanged [BASE] when not escalated
  - "cooldown_elapsed" reason is gone from user-facing when framing is present
  - "escalated" reason maps to "severity escalated" when framing is present
  - "reactivated" reason maps to "returned after resolving" when framing is present
  - Legacy format (no framing) is unchanged: "why: reason" still appears
  - Determinism: same finding + same graph → same framing dict
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cognition.consequence_mapper import (
    _compute_consequence_rank,
    _max_severity,
    get_consequence_framing,
)
from delivery.notifications import _effective_severity, format_notification
from memory.graph_store import GraphStore

_NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)

_T_VPS = "vps"
_T_HUMINT = "/root/humint"
_T_LESIA = "/root/lesia"
_T_REDIS = "/root/redis"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = GraphStore(str(tmp_path / "test.db"))
    s.connect()
    _seed(s)
    yield s
    s.disconnect()


def _seed(s: GraphStore) -> None:
    """Seed a graph where postgresql → humint (owner_facing), redis → nothing."""
    ids = {}
    for target, builder_id, label, node_type in [
        (_T_VPS,    "service:postgresql", "postgresql", "service"),
        (_T_HUMINT, "repo:humint",        "humint",     "repository"),
        (_T_VPS,    "service:redis",      "redis",      "service"),
        (_T_LESIA,  "repo:lesia",         "lesia",      "repository"),
    ]:
        r = s.upsert_node(
            target_id=target, builder_node_id=builder_id,
            node_type=node_type, label=label, now=_NOW,
        )
        ids[label] = r["node_id"]

    # humint DEPENDS_ON postgres (hard)
    s.upsert_edge(
        source_node_id=ids["humint"],
        target_node_id=ids["postgresql"],
        relationship="DEPENDS_ON", collector_type="human_declared",
        confidence=1.0,
        evidence=[{"source": "human_declared", "detail": "unit file confirms dep"}],
        now=_NOW,
    )
    # Annotations
    for label, consequence, owner_facing in [
        ("postgresql", "if down → HUMINT fails",    "false"),
        ("humint",     "if down → no HUMINT reports", "true"),
        ("redis",      "unknown",                   "false"),
        ("lesia",      "unknown",                   "true"),
    ]:
        s.set_node_annotation(node_id=ids[label], annotation_type="consequence",
                              value=consequence, evidence="test", now=_NOW)
        s.set_node_annotation(node_id=ids[label], annotation_type="owner_facing",
                              value=owner_facing, evidence="test", now=_NOW)


def _finding(target_id, finding_type, resource, severity="MEDIUM", **kw):
    return {
        "target_id": target_id, "finding_type": finding_type,
        "resource": resource, "scope": "host", "collector_type": "test",
        "severity": severity,
        "title": f"{finding_type} on {resource or target_id}",
        **kw,
    }


# ---------------------------------------------------------------------------
# _compute_consequence_rank unit tests
# ---------------------------------------------------------------------------

class TestComputeConsequenceRank:
    def test_owner_facing_loss_gives_high_floor(self):
        owner_lost = [{"label": "humint", "consequence": "goes dark"}]
        tier, eff, escalated = _compute_consequence_rank(owner_lost, [], "LOW")
        assert tier == "owner_facing_loss"
        assert eff == "HIGH"
        assert escalated is True

    def test_structural_cascade_gives_medium_floor(self):
        tier, eff, escalated = _compute_consequence_rank([], ["some-svc"], "LOW")
        assert tier == "structural_cascade"
        assert eff == "MEDIUM"
        assert escalated is True

    def test_no_cascade_is_unchanged(self):
        tier, eff, escalated = _compute_consequence_rank([], [], "MEDIUM")
        assert tier == "no_cascade"
        assert eff == "MEDIUM"
        assert escalated is False

    def test_high_base_stays_high_on_owner_facing(self):
        tier, eff, escalated = _compute_consequence_rank(
            [{"label": "x"}], [], "HIGH"
        )
        assert eff == "HIGH"
        assert escalated is False  # already at floor

    def test_critical_not_lowered_by_cascade(self):
        tier, eff, escalated = _compute_consequence_rank([], ["svc"], "CRITICAL")
        assert eff == "CRITICAL"
        assert escalated is False  # CRITICAL > MEDIUM, no change

    def test_empty_base_severity(self):
        tier, eff, escalated = _compute_consequence_rank(
            [{"label": "x"}], [], ""
        )
        assert eff == "HIGH"
        assert escalated is True  # "" < HIGH

    def test_max_severity_never_lowers(self):
        assert _max_severity("HIGH", "LOW") == "HIGH"
        assert _max_severity("LOW", "HIGH") == "HIGH"
        assert _max_severity("CRITICAL", "HIGH") == "CRITICAL"
        assert _max_severity("MEDIUM", "MEDIUM") == "MEDIUM"


# ---------------------------------------------------------------------------
# Framing: ranking fields present and correct
# ---------------------------------------------------------------------------

class TestFramingRankFields:
    def test_postgresql_finding_escalates_from_medium(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service",
                     severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        assert framing is not None
        assert framing["tier"] == "owner_facing_loss"
        assert framing["base_severity"] == "MEDIUM"
        assert framing["consequence_severity"] == "HIGH"
        assert framing["escalated"] is True

    def test_postgresql_finding_high_base_stays_high(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service",
                     severity="HIGH")
        framing = get_consequence_framing(f, store)
        assert framing["base_severity"] == "HIGH"
        assert framing["consequence_severity"] == "HIGH"
        assert framing["escalated"] is False

    def test_postgresql_finding_critical_base_stays_critical(self, store):
        f = _finding("vps", "kernel_oom_kill", "postgresql@16-main.service",
                     severity="CRITICAL")
        framing = get_consequence_framing(f, store)
        # CRITICAL base, owner_facing → effective = max(CRITICAL, HIGH) = CRITICAL
        assert framing["consequence_severity"] == "CRITICAL"
        assert framing["escalated"] is False

    def test_redis_finding_no_cascade_unchanged(self, store):
        """redis has no dependents in the graph — no escalation."""
        f = _finding("vps", "repeated_service_restart", "redis.service",
                     severity="HIGH")
        framing = get_consequence_framing(f, store)
        # redis maps to the redis node; no edges pointing TO redis → no cascade
        assert framing is not None
        assert framing["tier"] == "no_cascade"
        assert framing["escalated"] is False
        assert framing["consequence_severity"] == "HIGH"  # unchanged

    def test_economic_finding_returns_none(self, store):
        f = _finding("economic", "spend_spike", "lesia", severity="HIGH")
        assert get_consequence_framing(f, store) is None

    def test_framing_deterministic(self, store):
        f = _finding("vps", "repeated_service_restart", "postgresql@16-main.service")
        a = get_consequence_framing(f, store)
        b = get_consequence_framing(f, store)
        assert a == b


# ---------------------------------------------------------------------------
# Two same-type findings ranked differently
# ---------------------------------------------------------------------------

class TestSameTypeDifferentRank:
    def test_postgresql_ranks_higher_than_redis_same_type(self, store):
        """repeated_service_restart on postgresql (kills humint, owner_facing)
        vs the same type on redis (no owner_facing downstream).
        Effective severity of postgres finding must be >= redis finding."""
        postgres_f = _finding("vps", "repeated_service_restart",
                               "postgresql@16-main.service", severity="MEDIUM")
        redis_f = _finding("vps", "repeated_service_restart",
                            "redis.service", severity="MEDIUM")

        pg_framing = get_consequence_framing(postgres_f, store)
        redis_framing = get_consequence_framing(redis_f, store)

        pg_eff = pg_framing["consequence_severity"] if pg_framing else "MEDIUM"
        redis_eff = redis_framing["consequence_severity"] if redis_framing else "MEDIUM"

        from cognition.consequence_mapper import _SEV_RANK
        assert _SEV_RANK.get(pg_eff, 0) > _SEV_RANK.get(redis_eff, 0), (
            f"postgresql ({pg_eff}) should outrank redis ({redis_eff})"
        )


# ---------------------------------------------------------------------------
# _effective_severity helper
# ---------------------------------------------------------------------------

class TestEffectiveSeverity:
    def test_uses_consequence_when_available(self):
        framing = {"consequence_severity": "CRITICAL", "escalated": True}
        assert _effective_severity("HIGH", framing) == "CRITICAL"

    def test_uses_base_when_no_framing(self):
        assert _effective_severity("HIGH", None) == "HIGH"

    def test_uses_base_when_framing_has_no_consequence_severity(self):
        assert _effective_severity("HIGH", {}) == "HIGH"


# ---------------------------------------------------------------------------
# format_notification: badge and reason cleanup
# ---------------------------------------------------------------------------

class TestFormatNotificationRanking:
    def test_badge_shows_escalation_when_escalated(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        assert framing and framing["escalated"]
        text = format_notification(f, "cooldown_elapsed", consequence_framing=framing)
        assert "MEDIUM → HIGH" in text

    def test_badge_unchanged_when_not_escalated(self, store):
        f = _finding("vps", "repeated_service_restart", "redis.service", severity="HIGH")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "cooldown_elapsed", consequence_framing=framing)
        assert "[HIGH]" in text
        assert "→" not in text

    def test_cooldown_elapsed_gone_with_framing(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "cooldown_elapsed", consequence_framing=framing)
        assert "cooldown_elapsed" not in text
        assert "why:" not in text

    def test_escalated_reason_becomes_user_friendly(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "escalated", consequence_framing=framing)
        assert "severity escalated" in text
        assert "cooldown_elapsed" not in text

    def test_reactivated_reason_becomes_user_friendly(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "reactivated", consequence_framing=framing)
        assert "returned after resolving" in text

    def test_new_reason_silent_with_framing(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        text = format_notification(f, "new", consequence_framing=framing)
        assert "why:" not in text
        assert "new" not in text.lower().split("impact")[0]  # not in the header area

    def test_internal_reason_never_shown_without_framing(self):
        """Internal dedup reasons are NEVER user-facing — with or without framing.
        The 'why: reason' line was killed unconditionally (no machinery leaks)."""
        f = _finding("economic", "spend_spike", "lesia", severity="HIGH")
        text = format_notification(f, "new")
        assert "why:" not in text

    def test_cooldown_elapsed_never_shown_with_none_framing(self):
        f = _finding("economic", "spend_spike", "lesia", severity="HIGH")
        text = format_notification(f, "cooldown_elapsed", consequence_framing=None)
        assert "cooldown_elapsed" not in text
        assert "why:" not in text

    def test_no_node_finding_no_internal_reason(self):
        """Economic finding maps to no node (framing=None); still no 'why:' line."""
        f = _finding("economic", "spend_spike", "lesia", severity="HIGH",
                     title="Big spend $50")
        text = format_notification(f, "cooldown_elapsed")
        assert "cooldown_elapsed" not in text
        assert "why:" not in text
        assert "📍" not in text

    def test_determinism(self, store):
        f = _finding("vps", "repeated_service_restart",
                     "postgresql@16-main.service", severity="MEDIUM")
        framing = get_consequence_framing(f, store)
        t1 = format_notification(f, "cooldown_elapsed", consequence_framing=framing)
        t2 = format_notification(f, "cooldown_elapsed", consequence_framing=framing)
        assert t1 == t2
