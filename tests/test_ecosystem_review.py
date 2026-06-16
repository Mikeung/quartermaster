"""Tests for reports/ecosystem_review.py — ecosystem report generators."""

from __future__ import annotations

from reports.ecosystem_review import (
    generate_ecosystem_complexity_report,
    generate_ecosystem_drift_report,
    generate_ecosystem_review,
    generate_operational_theme_report,
    generate_systemic_concern_report,
)


def _summary(overall="degrading", themes=None, systemic=None, trends=None):
    return {
        "overall_health": overall,
        "dominant_theme": "llm_cost_risk",
        "themes": themes or [
            {"name": "llm_cost_risk", "label": "LLM Cost Risk", "description": "Cost risk",
             "severity_hint": "high", "prevalence": 0.5, "evidence": ["retry pattern matched"],
             "contributing_patterns": ["retry_amplification"], "contributing_categories": ["cost"]}
        ],
        "systemic_concerns": systemic or [
            {"title": "Compounding cost risk", "description": "Cross-cutting concern",
             "contributing_themes": ["llm_cost_risk", "runtime_instability"],
             "evidence": ["two themes co-occurring"], "severity": "high", "systemic": True}
        ],
        "trends": trends or [
            {"dimension": "llm_cost_risk", "direction": "increasing", "score": 0.6,
             "evidence": ["patterns matched"], "note": "observed trend"}
        ],
        "snapshot_count": 10,
        "confidence": 0.75,
    }


def _drift(sig_count=2, score=0.35):
    return {
        "overall_drift_score": score,
        "significant_drift_count": sig_count,
        "snapshot_count": 10,
        "window_days": 30,
        "evidence": ["runtime stability decreasing", "complexity increasing"],
        "drift_trends": [
            {"dimension": "runtime_stability", "direction": "decreasing",
             "early_score": 0.9, "recent_score": 0.5, "magnitude": 0.4,
             "significant": True, "evidence": ["score dropped"], "snapshot_count": 10},
        ],
        "instability_indicators": [
            {"name": "runtime_degradation", "active": True, "score": 0.5, "evidence": ["score low"]},
        ],
        "complexity_trend": {
            "current_score": 0.5, "previous_score": 0.3, "delta": 0.2,
            "direction": "increasing", "dimensions": ["orchestration_complexity"],
            "evidence": ["framework count increased"],
        },
    }


class TestGenerateEcosystemReview:
    def test_returns_string(self):
        md = generate_ecosystem_review(_summary())
        assert isinstance(md, str)

    def test_contains_header(self):
        md = generate_ecosystem_review(_summary())
        assert "# Ecosystem Operational Review" in md

    def test_contains_overall_health(self):
        md = generate_ecosystem_review(_summary(overall="degrading"))
        assert "DEGRADING" in md

    def test_contains_systemic_concerns(self):
        md = generate_ecosystem_review(_summary())
        assert "Systemic Concerns" in md
        assert "Compounding cost risk" in md

    def test_contains_themes(self):
        md = generate_ecosystem_review(_summary())
        assert "LLM Cost Risk" in md

    def test_contains_advisory_footer(self):
        md = generate_ecosystem_review(_summary())
        assert "Advisory only" in md

    def test_with_clusters(self):
        clusters = [
            {"name": "high_cost_llm_processing", "label": "High-Cost LLM",
             "active": True, "cluster_score": 0.7, "severity_hint": "high",
             "note": "organizational aid"}
        ]
        md = generate_ecosystem_review(_summary(), clusters=clusters)
        assert "High-Cost LLM" in md

    def test_with_drift(self):
        md = generate_ecosystem_review(_summary(), drift=_drift())
        assert "Ecosystem Drift" in md

    def test_with_consolidated(self):
        consolidated = [
            {"title": "Cost + retry concern", "severity_hint": "high",
             "member_count": 3, "description": "", "contributing_recs": [],
             "contributing_patterns": [], "shared_evidence": [], "category_tags": [],
             "confidence": 0.7, "note": ""}
        ]
        md = generate_ecosystem_review(_summary(), consolidated=consolidated)
        assert "Consolidated" in md

    def test_empty_themes(self):
        md = generate_ecosystem_review(_summary(themes=[], systemic=[]))
        assert "# Ecosystem Operational Review" in md


class TestGenerateOperationalThemeReport:
    def test_returns_string(self):
        themes = _summary()["themes"]
        md = generate_operational_theme_report(themes)
        assert isinstance(md, str)

    def test_contains_header(self):
        md = generate_operational_theme_report([])
        assert "# Operational Theme Report" in md

    def test_empty_themes_message(self):
        md = generate_operational_theme_report([])
        assert "No operational themes" in md

    def test_theme_label_present(self):
        themes = _summary()["themes"]
        md = generate_operational_theme_report(themes)
        assert "LLM Cost Risk" in md

    def test_severity_badge_present(self):
        themes = _summary()["themes"]
        md = generate_operational_theme_report(themes)
        assert "[HIGH]" in md

    def test_advisory_footer(self):
        md = generate_operational_theme_report([])
        assert "Advisory only" in md


class TestGenerateSystemicConcernReport:
    def test_returns_string(self):
        md = generate_systemic_concern_report([])
        assert isinstance(md, str)

    def test_no_concerns_message(self):
        md = generate_systemic_concern_report([])
        assert "No systemic concerns" in md

    def test_concern_title_present(self):
        concerns = _summary()["systemic_concerns"]
        md = generate_systemic_concern_report(concerns)
        assert "Compounding cost risk" in md

    def test_advisory_footer(self):
        md = generate_systemic_concern_report([])
        assert "Advisory only" in md


class TestGenerateEcosystemDriftReport:
    def test_returns_string(self):
        md = generate_ecosystem_drift_report(_drift())
        assert isinstance(md, str)

    def test_contains_header(self):
        md = generate_ecosystem_drift_report(_drift())
        assert "# Ecosystem Drift Report" in md

    def test_contains_drift_trends(self):
        md = generate_ecosystem_drift_report(_drift())
        assert "Runtime Stability" in md

    def test_significant_flag_marked(self):
        md = generate_ecosystem_drift_report(_drift(sig_count=1))
        assert "1" in md

    def test_complexity_trend_section(self):
        md = generate_ecosystem_drift_report(_drift())
        assert "Operational Complexity" in md

    def test_instability_indicators(self):
        md = generate_ecosystem_drift_report(_drift())
        assert "Active Instability Indicators" in md

    def test_advisory_footer(self):
        md = generate_ecosystem_drift_report(_drift())
        assert "Advisory only" in md


class TestGenerateComplexityReport:
    def test_returns_string(self):
        complexity = _drift()["complexity_trend"]
        md = generate_ecosystem_complexity_report(complexity)
        assert isinstance(md, str)

    def test_contains_header(self):
        complexity = _drift()["complexity_trend"]
        md = generate_ecosystem_complexity_report(complexity)
        assert "# Ecosystem Complexity Report" in md

    def test_contains_scores(self):
        complexity = _drift()["complexity_trend"]
        md = generate_ecosystem_complexity_report(complexity)
        assert "0.50" in md or "0.5" in md

    def test_advisory_footer(self):
        complexity = _drift()["complexity_trend"]
        md = generate_ecosystem_complexity_report(complexity)
        assert "Advisory only" in md
