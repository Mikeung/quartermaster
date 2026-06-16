"""Tests for SeverityEngine."""

from cognition.severity import SeverityEngine, SeverityLevel, severity_from_health_score


class TestSeverityEngine:
    def test_no_inputs_returns_informational(self):
        assessment = SeverityEngine().assess()
        assert assessment.level == SeverityLevel.INFORMATIONAL
        assert assessment.score < 0.20

    def test_perfect_health_low_severity(self):
        assessment = SeverityEngine().assess(runtime_health_score=1.0)
        assert assessment.score < 0.40

    def test_zero_health_elevates_severity(self):
        assessment = SeverityEngine().assess(runtime_health_score=0.0)
        assert assessment.score >= 0.30  # 30% weight fully activated
        # score 0.30 falls in LOW band (0.20–0.40); above INFORMATIONAL
        assert assessment.level != SeverityLevel.INFORMATIONAL

    def test_critical_threshold(self):
        assessment = SeverityEngine().assess(
            runtime_health_score=0.0,
            recommendations=[{"confidence": 1.0, "impact": "high"}] * 5,
            temporal_volatility=1.0,
            recurrence_count=10,
            cost_observations=[
                {"severity": "high"},
                {"severity": "high"},
                {"severity": "warning"},
            ],
        )
        assert assessment.level == SeverityLevel.CRITICAL
        assert assessment.score >= 0.80

    def test_recurrence_contributes_to_score(self):
        low = SeverityEngine().assess(recurrence_count=0)
        high = SeverityEngine().assess(recurrence_count=8)
        assert high.score > low.score

    def test_cost_observations_contribute(self):
        no_cost = SeverityEngine().assess()
        with_cost = SeverityEngine().assess(
            cost_observations=[{"severity": "high"}, {"severity": "warning"}]
        )
        assert with_cost.score > no_cost.score

    def test_factors_are_present_in_output(self):
        assessment = SeverityEngine().assess(
            runtime_health_score=0.7,
            recurrence_count=2,
        )
        factor_names = {f.name for f in assessment.factors}
        assert "runtime_instability" in factor_names
        assert "recurrence" in factor_names

    def test_confidence_reflects_data_availability(self):
        sparse = SeverityEngine().assess(recurrence_count=0)
        # Only recurrence always present (data_points=0), so confidence = 0/5 = 0.0
        assert sparse.confidence < 0.5

        full = SeverityEngine().assess(
            runtime_health_score=0.8,
            recommendations=[{"confidence": 0.5, "impact": "low"}],
            temporal_volatility=0.2,
            recurrence_count=0,
            cost_observations=[{"severity": "warning"}],
        )
        # 4 of 5 factors have data: runtime, recommendations, temporal, cost (recurrence always present)
        assert full.confidence == 0.8

    def test_to_dict_structure(self):
        assessment = SeverityEngine().assess(runtime_health_score=0.8, recurrence_count=1)
        d = assessment.to_dict()
        assert "level" in d
        assert "score" in d
        assert "factors" in d
        assert "evidence" in d
        assert "confidence" in d
        assert "assessed_at" in d

    def test_factors_sum_matches_total_score(self):
        assessment = SeverityEngine().assess(
            runtime_health_score=0.5,
            temporal_volatility=0.3,
            recurrence_count=2,
        )
        factor_sum = sum(f.contribution for f in assessment.factors)
        assert abs(assessment.score - round(factor_sum, 3)) < 0.001

    def test_score_capped_at_one(self):
        assessment = SeverityEngine().assess(
            runtime_health_score=0.0,
            recommendations=[{"confidence": 1.0, "impact": "high"}] * 10,
            temporal_volatility=1.0,
            recurrence_count=100,
            cost_observations=[{"severity": "high"}] * 10,
        )
        assert assessment.score <= 1.0


class TestSeverityFromHealthScore:
    def test_perfect_health_is_informational(self):
        assert severity_from_health_score(1.0) == SeverityLevel.INFORMATIONAL

    def test_zero_health_is_critical(self):
        assert severity_from_health_score(0.0) == SeverityLevel.CRITICAL

    def test_moderate_health(self):
        # instability = 0.5 → should be HIGH (>= 0.60 threshold) or MODERATE
        level = severity_from_health_score(0.4)
        assert level in (SeverityLevel.HIGH, SeverityLevel.CRITICAL)

    def test_low_instability(self):
        level = severity_from_health_score(0.9)
        assert level in (SeverityLevel.INFORMATIONAL, SeverityLevel.LOW)
