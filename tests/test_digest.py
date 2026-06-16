"""Tests for digest generation."""

from reports.digest import (
    generate_critical_digest,
    generate_daily_digest,
    generate_morning_digest,
)


def _snapshot(snap_id: int = 1) -> dict:
    return {
        "id": snap_id,
        "created_at": "2026-01-15T08:00:00",
        "data": {
            "topology": {"node_count": 5, "edge_count": 4},
            "workflows": [{"workflow_type": "rag_pipeline", "name": "RAG Pipeline"}],
            "cost_observations": [
                {"observation": "High token usage in retry loop", "severity": "high", "component": "llm"}
            ],
            "recommendations": [
                {"title": "Add rate limiting", "summary": "Rate limiter reduces cost", "impact": "high"}
            ],
        },
    }


def _runtime_health() -> dict:
    return {
        "overall_status": "healthy",
        "health_score": 0.95,
        "resource_pressure": [],
        "instability_signals": [],
        "failed_services": [],
        "has_docker_restarts": False,
        "docker_restart_details": [],
        "indicators": [],
    }


def _severity(level: str = "moderate", score: float = 0.45) -> dict:
    return {
        "level": level,
        "score": score,
        "confidence": 0.8,
        "evidence": ["Runtime degraded", "High-cost observations present"],
        "factors": [
            {"name": "runtime_instability", "contribution": 0.1, "description": "test"},
            {"name": "cost_amplification", "contribution": 0.05, "description": "test"},
        ],
        "assessed_at": "2026-01-15T08:00:00+00:00",
    }


def _attention() -> dict:
    return {
        "attention_summary": "1 high-priority concern requires review.",
        "top_concerns": [
            {
                "title": "High LLM token usage",
                "summary": "Retry loop may amplify costs",
                "urgency": "high",
                "category": "cost",
                "priority_score": 0.75,
                "evidence": ["Retry loop detected"],
            }
        ],
        "cost_concerns": [],
        "stability_concerns": [],
        "drift_concerns": [],
        "runtime_concerns": [],
        "suppressed_count": 2,
        "generated_at": "2026-01-15T08:00:00+00:00",
    }


class TestGenerateDailyDigest:
    def test_returns_markdown_string(self):
        result = generate_daily_digest(snapshot=_snapshot())
        assert isinstance(result, str)
        assert "Daily Operational Digest" in result

    def test_includes_severity_section(self):
        result = generate_daily_digest(snapshot=_snapshot(), severity=_severity())
        assert "Operational Severity" in result
        assert "MODERATE" in result

    def test_includes_runtime_health_section(self):
        result = generate_daily_digest(snapshot=_snapshot(), runtime_health=_runtime_health())
        assert "Runtime Health" in result
        assert "healthy" in result

    def test_includes_attention_summary(self):
        result = generate_daily_digest(snapshot=_snapshot(), attention_report=_attention())
        assert "Attention Summary" in result
        assert "high-priority" in result

    def test_includes_topology(self):
        result = generate_daily_digest(snapshot=_snapshot())
        assert "Infrastructure Snapshot" in result
        assert "Nodes: 5" in result

    def test_includes_cost_risks(self):
        result = generate_daily_digest(snapshot=_snapshot())
        assert "Cost Risks" in result
        assert "HIGH" in result

    def test_includes_recurring_issues(self):
        recurring = [
            {
                "kind": "recommendation",
                "pattern": "Rotate API keys",
                "occurrences": 3,
                "severity_hint": "moderate",
                "first_seen": "2026-01-01",
                "last_seen": "2026-01-15",
                "evidence": [],
                "snapshot_ids": [1, 2, 3],
            }
        ]
        result = generate_daily_digest(snapshot=_snapshot(), recurring_issues=recurring)
        assert "Recurring Issues" in result
        assert "Rotate API keys" in result

    def test_advisory_footer_present(self):
        result = generate_daily_digest(snapshot=_snapshot())
        assert "Advisory only" in result
        assert "Observe automatically" in result

    def test_includes_fused_insights(self):
        fused = [
            {
                "kind": "retry_memory_pressure",
                "title": "Retry loop under memory pressure",
                "description": "A retry workflow is active while memory is stressed.",
                "severity": "high",
                "affected_components": ["llm_retry_loop"],
                "evidence": ["Memory: stressed"],
            }
        ]
        result = generate_daily_digest(snapshot=_snapshot(), fused_insights=fused)
        assert "Compound Operational Concerns" in result
        assert "Retry loop" in result


class TestGenerateMorningDigest:
    def test_returns_markdown_string(self):
        result = generate_morning_digest(snapshots=[_snapshot()])
        assert isinstance(result, str)
        assert "Morning Operational Digest" in result

    def test_no_snapshots_returns_gracefully(self):
        result = generate_morning_digest(snapshots=[])
        assert "No snapshot history" in result

    def test_includes_trend_section(self):
        temporal = {
            "volatility_score": 0.3,
            "stability_score": 0.7,
            "total_changes": 5,
            "window_days": 7,
            "churn_indicators": ["Framework churn: 2 changes"],
            "trend_observations": ["Stable LLM provider lineup"],
        }
        result = generate_morning_digest(
            snapshots=[_snapshot(1), _snapshot(2)],
            temporal=temporal,
        )
        assert "Infrastructure Trend" in result
        assert "volatility" in result.lower()

    def test_includes_attention_guidance(self):
        result = generate_morning_digest(
            snapshots=[_snapshot()],
            attention_report=_attention(),
        )
        assert "What Needs Your Attention" in result

    def test_advisory_footer_present(self):
        result = generate_morning_digest(snapshots=[_snapshot()])
        assert "Advisory only" in result


class TestGenerateCriticalDigest:
    def test_returns_markdown_string(self):
        result = generate_critical_digest(severity=_severity("critical", 0.85))
        assert isinstance(result, str)
        assert "CRITICAL OPERATIONAL DIGEST" in result

    def test_shows_severity_level(self):
        result = generate_critical_digest(severity=_severity("high", 0.65))
        assert "HIGH" in result

    def test_includes_severity_evidence(self):
        result = generate_critical_digest(severity=_severity())
        assert "Severity Evidence" in result
        assert "Runtime degraded" in result

    def test_includes_runtime_health_when_degraded(self):
        rh = _runtime_health()
        rh["overall_status"] = "critical"
        rh["instability_signals"] = ["Service failing: nginx"]
        result = generate_critical_digest(severity=_severity(), runtime_health=rh)
        assert "Runtime Status" in result
        assert "CRITICAL" in result

    def test_skips_healthy_runtime(self):
        result = generate_critical_digest(severity=_severity(), runtime_health=_runtime_health())
        assert "Runtime Status" not in result

    def test_includes_fused_insights(self):
        fused = [
            {
                "kind": "restart_churn_multi_agent",
                "title": "Multi-agent with restart churn",
                "description": "Agent coordination at risk.",
                "severity": "high",
                "affected_components": ["multi_agent_orchestration"],
                "evidence": ["Container restarts: 5"],
            }
        ]
        result = generate_critical_digest(
            severity=_severity("high", 0.65),
            fused_insights=fused,
        )
        assert "Compound Risks" in result
        assert "Multi-agent" in result

    def test_advisory_disclaimer_present(self):
        result = generate_critical_digest(severity=_severity())
        assert "ADVISORY ONLY" in result
        assert "no automated action" in result

    def test_attention_concerns_surfaced(self):
        attn = _attention()
        result = generate_critical_digest(severity=_severity(), attention_report=attn)
        assert "Immediate Concerns" in result
