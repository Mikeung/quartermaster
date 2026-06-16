"""Tests for cognition/query_workflows.py — OperatorQueryWorkflow."""

from __future__ import annotations

from cognition.query_workflows import OperatorQueryWorkflow, WorkflowResult, WorkflowStep


def _snap(snap_id=1, created_at="2026-01-01T00:00:00", packages=None,
          providers=None, rt_score=0.9, rt_status="healthy", recs=None):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "recommendations": recs or [],
            "cost_observations": [],
            "runtime_health": {
                "health_score": rt_score,
                "overall_status": rt_status,
                "instability_signals": [],
            },
            "llm_detections": [{"provider": p} for p in (providers or [])],
            "scanner_results": {"results": {
                "repo_scanner": {"packages": packages or []}
            }},
            "workflows": [],
        },
    }


def _summary(overall="degrading", themes=None, concerns=None, snap_count=5):
    return {
        "overall_health": overall,
        "dominant_theme": "llm_cost_risk",
        "themes": themes or [
            {"name": "llm_cost_risk", "label": "LLM Cost Risk",
             "severity_hint": "high", "prevalence": 0.6, "evidence": ["signal"]}
        ],
        "systemic_concerns": concerns or [],
        "confidence": 0.7,
        "snapshot_count": snap_count,
    }


def _drift(score=0.35, sig_count=1, trends=None):
    return {
        "overall_drift_score": score,
        "significant_drift_count": sig_count,
        "drift_trends": trends or [
            {"dimension": "runtime_stability", "direction": "decreasing",
             "early_score": 0.9, "recent_score": 0.4, "significant": True}
        ],
    }


class TestWhyIsHealthDegrading:
    def test_returns_workflow_result(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        assert isinstance(result, WorkflowResult)

    def test_has_steps(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        assert len(result.steps) > 0

    def test_has_findings(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        assert len(result.findings) > 0

    def test_confidence_bounded(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        assert 0.0 <= result.confidence <= 1.0

    def test_to_dict_structure(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        d = result.to_dict()
        assert "query" in d
        assert "steps" in d
        assert "findings" in d
        assert "evidence" in d
        assert "recommendations" in d
        assert "confidence" in d
        assert "advisory" in d

    def test_with_drift(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary(), drift=_drift())
        # Drift data should contribute to findings
        assert result.confidence > 0.0

    def test_with_clusters(self):
        clusters = [{"name": "provider_risk", "label": "Provider Risk",
                     "active": True, "cluster_score": 0.7}]
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary(), clusters=clusters)
        assert len(result.steps) >= 4

    def test_stable_ecosystem(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(
            _summary(overall="stable", themes=[])
        )
        assert isinstance(result, WorkflowResult)

    def test_markdown_returns_string(self):
        result = OperatorQueryWorkflow().why_is_health_degrading(_summary())
        md = result.markdown()
        assert isinstance(md, str)
        assert "Operator Query Workflow" in md


class TestWhatChangedLastNDays:
    def test_insufficient_snapshots(self):
        result = OperatorQueryWorkflow().what_changed_last_n_days([_snap()])
        assert "insufficient" in result.findings[0].lower()
        assert result.confidence == 0.0

    def test_two_snapshots_returns_result(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = OperatorQueryWorkflow().what_changed_last_n_days(snaps)
        assert isinstance(result, WorkflowResult)
        assert len(result.steps) >= 2

    def test_package_changes_detected(self):
        s1 = _snap(1, "2026-01-01T00:00:00", packages=["langchain"])
        s2 = _snap(2, "2026-01-08T00:00:00", packages=["langchain", "autogen"])
        result = OperatorQueryWorkflow().what_changed_last_n_days([s1, s2])
        findings_text = " ".join(result.findings)
        assert "package" in findings_text.lower() or any("added" in e.lower() for e in result.evidence)

    def test_provider_changes_detected(self):
        s1 = _snap(1, "2026-01-01T00:00:00", providers=["openai"])
        s2 = _snap(2, "2026-01-08T00:00:00", providers=["openai", "anthropic"])
        result = OperatorQueryWorkflow().what_changed_last_n_days([s1, s2])
        assert any("provider" in e.lower() or "anthropic" in e.lower() for e in result.evidence)

    def test_runtime_degradation_detected(self):
        s1 = _snap(1, "2026-01-01T00:00:00", rt_score=0.9, rt_status="healthy")
        s2 = _snap(2, "2026-01-08T00:00:00", rt_score=0.3, rt_status="critical")
        result = OperatorQueryWorkflow().what_changed_last_n_days([s1, s2])
        findings_text = " ".join(result.findings)
        assert "runtime" in findings_text.lower() or "degraded" in findings_text.lower()


class TestWhatConcernsUnresolved:
    def test_empty_lifespans(self):
        result = OperatorQueryWorkflow().what_concerns_unresolved([])
        assert isinstance(result, WorkflowResult)

    def test_persistent_concerns_surface(self):
        lifespans = [
            {"title": "Enable cost tracking", "status": "persistent", "impact": "high",
             "occurrence_count": 5},
            {"title": "Add retry budget", "status": "new", "impact": "moderate",
             "occurrence_count": 1},
        ]
        result = OperatorQueryWorkflow().what_concerns_unresolved(lifespans)
        findings_text = " ".join(result.findings)
        assert "persistent" in findings_text.lower() or "1" in findings_text

    def test_resolved_items_counted(self):
        lifespans = [
            {"title": "Old concern", "status": "resolved", "impact": "low", "occurrence_count": 2},
        ]
        result = OperatorQueryWorkflow().what_concerns_unresolved(lifespans)
        findings_text = " ".join(result.findings)
        assert "resolved" in findings_text.lower()


class TestWhichWorkflowsDominateCost:
    def test_empty_inputs(self):
        result = OperatorQueryWorkflow().which_workflows_dominate_cost([], [])
        assert isinstance(result, WorkflowResult)

    def test_high_cost_workflows_identified(self):
        workflows = [
            {"name": "rag", "workflow_type": "rag_pipeline"},
            {"name": "agent", "workflow_type": "multi_agent_orchestration"},
        ]
        result = OperatorQueryWorkflow().which_workflows_dominate_cost(workflows, [])
        findings_text = " ".join(result.findings)
        assert "cost" in findings_text.lower() or "workflow" in findings_text.lower()

    def test_cost_observations_surface(self):
        cost_obs = [
            {"observation_type": "retry_amplification", "severity": "high",
             "description": "Retry amplification detected"}
        ]
        result = OperatorQueryWorkflow().which_workflows_dominate_cost([], cost_obs)
        assert any("high" in e.lower() for e in result.evidence)


class TestWhatInstabilityRecurring:
    def test_empty_recurrence(self):
        result = OperatorQueryWorkflow().what_instability_recurring([])
        assert isinstance(result, WorkflowResult)

    def test_runtime_health_surface(self):
        rt = {"health_score": 0.3, "overall_status": "critical",
              "instability_signals": ["high CPU", "swap pressure"]}
        result = OperatorQueryWorkflow().what_instability_recurring([], runtime_health=rt)
        assert any("critical" in e.lower() or "instability" in e.lower() for e in result.evidence)

    def test_recurring_items_surface(self):
        recurrence_data = [
            {"title": "Runtime instability", "status": "persistent",
             "impact": "high", "occurrence_count": 5, "kind": "runtime_failure"},
        ]
        result = OperatorQueryWorkflow().what_instability_recurring(recurrence_data)
        findings_text = " ".join(result.findings)
        assert "recurring" in findings_text.lower() or "persistent" in findings_text.lower()


class TestWhatChangedSinceStable:
    def test_insufficient_snapshots(self):
        result = OperatorQueryWorkflow().what_changed_since_stable([])
        assert "insufficient" in result.findings[0].lower()

    def test_two_snapshots_returns_result(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = OperatorQueryWorkflow().what_changed_since_stable(snaps)
        assert isinstance(result, WorkflowResult)

    def test_with_drift(self):
        snaps = [_snap(1, "2026-01-01T00:00:00"), _snap(2, "2026-01-08T00:00:00")]
        result = OperatorQueryWorkflow().what_changed_since_stable(snaps, drift=_drift())
        # Drift data should add steps
        assert len(result.steps) >= 2

    def test_package_delta_detected(self):
        s1 = _snap(1, "2026-01-01T00:00:00", packages=["a"])
        s2 = _snap(2, "2026-01-08T00:00:00", packages=["a", "b", "c", "d"])
        result = OperatorQueryWorkflow().what_changed_since_stable([s1, s2])
        assert any("package" in e.lower() for e in result.evidence)


class TestWorkflowStep:
    def test_to_dict(self):
        step = WorkflowStep(1, "test step", "test finding", ["ev1"], 1)
        d = step.to_dict()
        assert "step" in d
        assert "name" in d
        assert "finding" in d
        assert "evidence" in d
