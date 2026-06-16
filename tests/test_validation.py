"""Tests for cognition/validation.py — CognitionValidator."""

from __future__ import annotations

from cognition.validation import (
    WARN_CLUSTER_ACTIVE_NO_SIGNALS,
    WARN_CONFIDENCE_OUT_OF_RANGE,
    WARN_CONFIDENCE_TOO_HIGH_SINGLE_SNAP,
    WARN_DEGRADING_HEALTH_NO_THEMES,
    WARN_DRIFT_SCORE_INCONSISTENT,
    WARN_HIGH_SEVERITY_NO_EVIDENCE,
    WARN_SYSTEMIC_SINGLE_THEME,
    WARN_THEME_NO_EVIDENCE,
    CognitionValidator,
    ConsistencyCheck,
    ValidationReport,
    ValidationWarning,
)


def _summary(overall="stable", themes=None, concerns=None, confidence=0.7, snap_count=5):
    return {
        "overall_health": overall,
        "themes": themes or [],
        "systemic_concerns": concerns or [],
        "confidence": confidence,
        "snapshot_count": snap_count,
    }


def _theme(name="llm_cost_risk", severity="high", evidence=None):
    return {
        "name": name,
        "label": "LLM Cost Risk",
        "severity_hint": severity,
        "prevalence": 0.5,
        "evidence": evidence if evidence is not None else ["signal A"],
    }


def _concern(title="Cross-cutting", severity="high", themes=None):
    return {
        "title": title,
        "severity": severity,
        "contributing_themes": themes or ["theme_a", "theme_b"],
    }


def _cluster(name="test_cluster", active=False, score=0.5):
    return {
        "name": name,
        "label": name,
        "active": active,
        "cluster_score": score,
        "member_patterns": [],
        "member_recommendations": [],
        "evidence": [],
    }


def _drift(overall=0.1, sig_count=0, trends=None):
    return {
        "overall_drift_score": overall,
        "significant_drift_count": sig_count,
        "drift_trends": trends or [],
    }


def _rec(title="test rec", impact="high", confidence=0.8, evidence=None):
    return {
        "title": title,
        "impact": impact,
        "confidence": confidence,
        "evidence": evidence if evidence is not None else ["signal"],
    }


class TestValidateSynthesisBasic:
    def test_returns_consistency_check(self):
        result = CognitionValidator().validate_synthesis(_summary())
        assert isinstance(result, ConsistencyCheck)

    def test_valid_summary_passes(self):
        summary = _summary(
            overall="stable",
            themes=[_theme()],
            confidence=0.7,
            snap_count=5,
        )
        result = CognitionValidator().validate_synthesis(summary)
        assert result.passed is True
        assert len(result.warnings) == 0

    def test_degrading_health_no_themes_warns(self):
        summary = _summary(overall="degrading", themes=[])
        result = CognitionValidator().validate_synthesis(summary)
        assert result.passed is False
        codes = {w.code for w in result.warnings}
        assert WARN_DEGRADING_HEALTH_NO_THEMES in codes

    def test_critical_health_no_themes_warns(self):
        summary = _summary(overall="critical", themes=[])
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_DEGRADING_HEALTH_NO_THEMES in codes

    def test_high_confidence_single_snapshot_warns(self):
        summary = _summary(confidence=0.95, snap_count=1)
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_TOO_HIGH_SINGLE_SNAP in codes

    def test_confidence_in_range_no_warn(self):
        summary = _summary(confidence=0.7, snap_count=5)
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_OUT_OF_RANGE not in codes

    def test_confidence_out_of_range_errors(self):
        summary = _summary(confidence=1.5)
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_OUT_OF_RANGE in codes

    def test_theme_no_evidence_errors(self):
        summary = _summary(themes=[_theme(evidence=[])])
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_THEME_NO_EVIDENCE in codes

    def test_systemic_concern_single_theme_warns(self):
        concern = _concern(themes=["only_one"])
        summary = _summary(concerns=[concern])
        result = CognitionValidator().validate_synthesis(summary)
        codes = {w.code for w in result.warnings}
        assert WARN_SYSTEMIC_SINGLE_THEME in codes


class TestValidateClusters:
    def test_returns_consistency_check(self):
        result = CognitionValidator().validate_clusters([])
        assert isinstance(result, ConsistencyCheck)

    def test_empty_clusters_passes(self):
        result = CognitionValidator().validate_clusters([])
        assert result.passed is True

    def test_inactive_cluster_no_warning(self):
        cluster = _cluster(active=False)
        result = CognitionValidator().validate_clusters([cluster])
        assert result.passed is True

    def test_active_cluster_no_signals_warns(self):
        cluster = _cluster(active=True)
        result = CognitionValidator().validate_clusters([cluster])
        codes = {w.code for w in result.warnings}
        assert WARN_CLUSTER_ACTIVE_NO_SIGNALS in codes

    def test_active_cluster_with_signals_passes(self):
        cluster = _cluster(active=True)
        cluster["member_patterns"] = ["retry_amplification"]
        result = CognitionValidator().validate_clusters([cluster])
        codes = {w.code for w in result.warnings}
        assert WARN_CLUSTER_ACTIVE_NO_SIGNALS not in codes

    def test_cluster_score_out_of_range_errors(self):
        cluster = _cluster(score=1.5)
        result = CognitionValidator().validate_clusters([cluster])
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_OUT_OF_RANGE in codes


class TestValidateDrift:
    def test_returns_consistency_check(self):
        result = CognitionValidator().validate_drift(_drift())
        assert isinstance(result, ConsistencyCheck)

    def test_clean_drift_passes(self):
        drift = _drift(overall=0.1, sig_count=0, trends=[])
        result = CognitionValidator().validate_drift(drift)
        assert result.passed is True

    def test_sig_count_mismatch_errors(self):
        trend = {"dimension": "runtime_stability", "significant": True}
        drift = _drift(overall=0.3, sig_count=0, trends=[trend])
        result = CognitionValidator().validate_drift(drift)
        codes = {w.code for w in result.warnings}
        assert WARN_DRIFT_SCORE_INCONSISTENT in codes

    def test_sig_count_matches_no_error(self):
        trend = {"dimension": "runtime_stability", "significant": True}
        drift = _drift(overall=0.3, sig_count=1, trends=[trend])
        result = CognitionValidator().validate_drift(drift)
        codes = {w.code for w in result.warnings}
        assert WARN_DRIFT_SCORE_INCONSISTENT not in codes

    def test_drift_score_out_of_range_errors(self):
        drift = _drift(overall=1.5)
        result = CognitionValidator().validate_drift(drift)
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_OUT_OF_RANGE in codes


class TestValidateRecommendations:
    def test_returns_consistency_check(self):
        result = CognitionValidator().validate_recommendations([])
        assert isinstance(result, ConsistencyCheck)

    def test_high_impact_with_evidence_passes(self):
        result = CognitionValidator().validate_recommendations([_rec(impact="high", evidence=["signal"])])
        assert result.passed is True

    def test_high_impact_no_evidence_warns(self):
        result = CognitionValidator().validate_recommendations([_rec(impact="high", evidence=[])])
        codes = {w.code for w in result.warnings}
        assert WARN_HIGH_SEVERITY_NO_EVIDENCE in codes

    def test_critical_impact_no_evidence_warns(self):
        result = CognitionValidator().validate_recommendations([_rec(impact="critical", evidence=[])])
        codes = {w.code for w in result.warnings}
        assert WARN_HIGH_SEVERITY_NO_EVIDENCE in codes

    def test_low_impact_no_evidence_no_warn(self):
        result = CognitionValidator().validate_recommendations([_rec(impact="low", evidence=[])])
        assert result.passed is True

    def test_confidence_out_of_range_errors(self):
        result = CognitionValidator().validate_recommendations([_rec(confidence=1.5)])
        codes = {w.code for w in result.warnings}
        assert WARN_CONFIDENCE_OUT_OF_RANGE in codes


class TestRunAll:
    def test_returns_validation_report(self):
        report = CognitionValidator().run_all()
        assert isinstance(report, ValidationReport)

    def test_no_inputs_empty_checks(self):
        report = CognitionValidator().run_all()
        assert len(report.checks) == 0

    def test_all_inputs_runs_all_checks(self):
        report = CognitionValidator().run_all(
            summary=_summary(),
            clusters=[_cluster()],
            drift=_drift(),
            recommendations=[_rec()],
        )
        assert len(report.checks) == 4

    def test_passed_count_correct(self):
        report = CognitionValidator().run_all(
            summary=_summary(overall="stable", confidence=0.7, snap_count=5),
        )
        assert report.passed_checks >= 0
        assert report.failed_checks >= 0

    def test_to_dict_structure(self):
        report = CognitionValidator().run_all(summary=_summary())
        d = report.to_dict()
        assert "checks" in d
        assert "total_warnings" in d
        assert "passed_checks" in d
        assert "failed_checks" in d
        assert "advisory" in d

    def test_markdown_returns_string(self):
        report = CognitionValidator().run_all(summary=_summary())
        md = report.markdown()
        assert isinstance(md, str)
        assert "Cognition Consistency Validation" in md

    def test_warning_to_dict(self):
        w = ValidationWarning(
            code="TEST_CODE", message="test", severity="warning",
            context={"key": "val"}, check_name="test_check"
        )
        d = w.to_dict()
        assert "code" in d
        assert "message" in d
        assert "severity" in d
