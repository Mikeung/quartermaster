"""Tests for the push policy — what earns a real-time push / P0 incident.

Pure and deterministic: evaluate() takes a finding + optional consequence framing and
returns a verdict. These assert the hard line from the task:
  - security / OOM / money / dependency are NEVER suppressed,
  - impact-free activity and the tool's OWN dev churn are silenced unless a real
    owner-facing consequence is present,
  - service-loss / restart findings are not gated (left to existing classification).
"""

from __future__ import annotations

from cognition.push_policy import (
    evaluate,
    is_intrinsically_critical,
    is_self_dev_activity,
)


def _f(ftype, target="some-repo", **kw):
    return {
        "finding_type": ftype,
        "target_id": target,
        "severity": kw.pop("severity", "MEDIUM"),
        **kw,
    }


_OWNER_FRAMING = {
    "owner_facing_lost": [{"label": "hdt-web", "consequence": "site down", "confidence": "High"}],
    "mapped_node_label": "hdt-web",
    "escalated": True, "consequence_severity": "HIGH", "base_severity": "MEDIUM",
}
_NO_IMPACT_FRAMING = {"owner_facing_lost": [], "affected_labels": [], "mapped_node_label": "x"}


class TestIntrinsic:
    def test_security_and_oom_always_push(self):
        for t in ("kernel_oom_kill", "port_exposed_publicly",
                  "credential_in_unit_file", "world_readable_env_file"):
            v = evaluate(_f(t), None)
            assert v.push and v.reason == "intrinsic", t

    def test_economic_always_push(self):
        for t in ("spend_spike", "unknown_cost_owner", "runaway_agent_cost", "agent_cost"):
            assert evaluate(_f(t, target="economic"), None).push, t

    def test_dependency_unreachable_is_intrinsic(self):
        assert evaluate(_f("dependency_unreachable", target="vps"), None).push

    def test_intrinsic_never_suppressed_even_on_self_repo(self):
        # an OOM on the quartermaster repo is still an OOM
        assert evaluate(_f("kernel_oom_kill", target="quartermaster"), None).push

    def test_helper_matches_set(self):
        assert is_intrinsically_critical(_f("spend_spike"))
        assert not is_intrinsically_critical(_f("deployment_event"))


class TestActivityGate:
    def test_activity_without_consequence_is_silenced(self):
        for t in ("deployment_event", "subsystem_rebuild", "engineering_burst", "agent_burst"):
            v = evaluate(_f(t), None)
            assert not v.push and v.reason == "no_consequence", t

    def test_activity_with_no_impact_framing_is_silenced(self):
        v = evaluate(_f("deployment_event"), _NO_IMPACT_FRAMING)
        assert not v.push and v.reason == "no_consequence"

    def test_activity_with_owner_facing_consequence_pushes(self):
        v = evaluate(_f("deployment_event", target="hdt-web"), _OWNER_FRAMING)
        assert v.push and v.reason == "owner_facing_consequence"


class TestSelfFeedbackLoop:
    def test_self_dev_activity_is_silenced(self):
        for t in ("deployment_event", "subsystem_rebuild", "engineering_burst",
                  "agent_burst", "project_activity", "agent_activity"):
            v = evaluate(_f(t, target="quartermaster"), None)
            assert not v.push and v.reason == "self_activity", t

    def test_self_dev_activity_matches_path_suffix(self):
        assert is_self_dev_activity(_f("deployment_event", target="/opt/quartermaster"))

    def test_self_activity_silenced_even_with_consequence(self):
        # the tool's own dev activity is never an operational incident, full stop —
        # checked before consequence so a stray graph mapping cannot resurrect it
        v = evaluate(_f("subsystem_rebuild", target="quartermaster"), _OWNER_FRAMING)
        assert not v.push and v.reason == "self_activity"

    def test_non_activity_on_self_repo_not_self_activity(self):
        # a security finding located in the quartermaster repo is NOT self dev activity
        assert not is_self_dev_activity(_f("credential_in_unit_file", target="quartermaster"))


class TestUnclassifiedPass:
    def test_service_and_health_findings_not_gated(self):
        # not activity types, no framing → left to existing classification (push)
        for t in ("service_disappeared", "repeated_service_restart",
                  "monitor_stale", "stable_listener_disappeared"):
            v = evaluate(_f(t, target="vps"), None)
            assert v.push and v.reason == "unclassified_pass", t


class TestDeterminism:
    def test_same_inputs_same_verdict(self):
        a = evaluate(_f("deployment_event"), None)
        b = evaluate(_f("deployment_event"), None)
        assert (a.push, a.reason) == (b.push, b.reason)
