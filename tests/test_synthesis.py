"""Tests for cognition/synthesis.py — EcosystemSynthesisEngine."""

from __future__ import annotations

from cognition.synthesis import (
    EcosystemSummary,
    EcosystemSynthesisEngine,
)


def _snap(snap_id: int, created_at: str, recs=None, rt=None, cost_obs=None, packages=None, providers=None, workflows=None):
    return {
        "id": snap_id,
        "created_at": created_at,
        "data": {
            "recommendations": recs or [],
            "cost_observations": cost_obs or [],
            "runtime_health": rt or {},
            "llm_detections": [{"provider": p} for p in (providers or [])],
            "scanner_results": {"results": {"repo_scanner": {"packages": packages or []}}},
            "workflows": workflows or [],
        },
    }


def _rec(title: str, category: str = "cost", impact: str = "high", confidence: float = 0.8):
    return {"title": title, "category": category, "impact": impact,
            "confidence": confidence, "urgency": "review", "evidence": [f"evidence {title}"],
            "suggested_investigation": ""}


def _rt(score: float = 0.9, status: str = "healthy"):
    return {"health_score": score, "overall_status": status,
            "instability_signals": [], "failed_services": [], "resource_pressure": []}


def _pattern(name: str, matched: bool = True):
    return {"name": name, "matched": matched, "matching_evidence": [], "severity_hint": "moderate",
            "description": "", "operational_impact": "", "mitigation_guidance": "", "confidence_notes": ""}


SNAP1 = _snap(1, "2026-01-01T00:00:00",
              recs=[_rec("Enable cost tracking")],
              rt=_rt(0.5, "degraded"),
              packages=["tenacity", "langchain", "autogen"],
              providers=["openai"],
              workflows=[{"name": "rag", "workflow_type": "rag_pipeline", "confidence": 0.8, "evidence": []}])

SNAP2 = _snap(2, "2026-01-08T00:00:00",
              recs=[_rec("Enable cost tracking"), _rec("Add retry budget")],
              rt=_rt(0.4, "degraded"),
              packages=["tenacity", "langchain"],
              providers=["openai"])


class TestEcosystemSynthesisEngineBasic:
    def test_empty_snapshots_returns_summary(self):
        result = EcosystemSynthesisEngine().synthesize([])
        assert isinstance(result, EcosystemSummary)
        assert result.overall_health == "unknown"
        assert result.confidence == 0.0

    def test_returns_ecosystem_summary(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1, SNAP2])
        assert isinstance(result, EcosystemSummary)

    def test_to_dict_structure(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1])
        d = result.to_dict()
        assert "themes" in d
        assert "systemic_concerns" in d
        assert "trends" in d
        assert "dominant_theme" in d
        assert "overall_health" in d
        assert "confidence" in d
        assert "snapshot_count" in d
        assert "advisory" in d

    def test_snapshot_count(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1, SNAP2])
        assert result.snapshot_count == 2


class TestThemeExtraction:
    def test_runtime_instability_theme(self):
        rt = {"health_score": 0.3, "overall_status": "critical",
              "instability_signals": ["high CPU usage", "swap pressure"],
              "failed_services": [], "resource_pressure": []}
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            runtime_health=rt,
        )
        theme_names = {t.name for t in result.themes}
        assert "runtime_instability" in theme_names

    def test_llm_cost_risk_theme(self):
        patterns = [
            _pattern("retry_amplification"),
            _pattern("cost_blind_rag"),
        ]
        result = EcosystemSynthesisEngine().synthesize([SNAP1], patterns=patterns)
        theme_names = {t.name for t in result.themes}
        assert "llm_cost_risk" in theme_names

    def test_themes_have_evidence(self):
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            runtime_health=_rt(0.3, "critical"),
        )
        for theme in result.themes:
            assert len(theme.evidence) > 0

    def test_theme_to_dict(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1, SNAP2])
        if result.themes:
            d = result.themes[0].to_dict()
            assert "name" in d
            assert "label" in d
            assert "prevalence" in d
            assert "severity_hint" in d

    def test_themes_sorted_by_prevalence(self):
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            runtime_health=_rt(0.3, "critical"),
        )
        prevalences = [t.prevalence for t in result.themes]
        assert prevalences == sorted(prevalences, reverse=True)


class TestSystemicConcerns:
    def test_systemic_concern_detected_when_themes_co_occur(self):
        patterns = [_pattern("retry_amplification"), _pattern("framework_stacking")]
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            patterns=patterns,
            runtime_health=_rt(0.3, "critical"),
        )
        if len(result.themes) >= 2:
            theme_names = {t.name for t in result.themes}
            if "llm_cost_risk" in theme_names and "runtime_instability" in theme_names:
                assert len(result.systemic_concerns) >= 1

    def test_systemic_concern_to_dict(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1, SNAP2])
        for concern in result.systemic_concerns:
            d = concern.to_dict()
            assert "title" in d
            assert "contributing_themes" in d
            assert "severity" in d
            assert concern.systemic is True


class TestEcosystemTrends:
    def test_trends_always_present(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1])
        assert len(result.trends) > 0

    def test_trend_to_dict(self):
        result = EcosystemSynthesisEngine().synthesize([SNAP1])
        d = result.trends[0].to_dict()
        assert "dimension" in d
        assert "direction" in d
        assert "score" in d

    def test_runtime_trend_with_degraded_health(self):
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1], runtime_health=_rt(0.3, "critical")
        )
        rt_trend = next((t for t in result.trends if t.dimension == "runtime_stability"), None)
        assert rt_trend is not None
        assert rt_trend.score < 0.5


class TestOverallHealth:
    def test_healthy_ecosystem(self):
        snap = _snap(1, "2026-01-01T00:00:00", rt=_rt(0.95, "healthy"))
        result = EcosystemSynthesisEngine().synthesize([snap])
        assert result.overall_health in ("stable", "elevated", "degrading")

    def test_degraded_ecosystem(self):
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            runtime_health=_rt(0.2, "critical"),
        )
        assert result.overall_health in ("degrading", "critical")

    def test_confidence_increases_with_more_data(self):
        single = EcosystemSynthesisEngine().synthesize([SNAP1])
        multi = EcosystemSynthesisEngine().synthesize([SNAP1, SNAP2])
        assert multi.confidence >= single.confidence


class TestDominantTheme:
    def test_dominant_theme_set_when_themes_present(self):
        result = EcosystemSynthesisEngine().synthesize(
            [SNAP1, SNAP2],
            runtime_health=_rt(0.3, "critical"),
        )
        if result.themes:
            assert result.dominant_theme is not None
