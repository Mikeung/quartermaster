"""Tests for Phase 13C additions: cognition/investigation_quality.py
and new report generators in reports/investigation_report.py."""

from __future__ import annotations

import pytest

from cognition.investigation_quality import (
    EvidenceDepthScore,
    InvestigationQualityAssessment,
    InvestigationQualityEngine,
    InvestigationQualityFlags,
    InvestigationTriageReport,
    _quality_band,
    _score_confidence_calibration,
    _score_evidence_depth,
    _score_snapshot_coverage,
    _score_uncertainty_completeness,
)
from reports.investigation_report import (
    generate_quality_scored_report,
    generate_triage_report,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _good_result(**overrides) -> dict:
    base = {
        "kind": "recent_changes",
        "summary": "5 changes across 4 snapshots (volatility: 0.72).",
        "evidence_chain": [
            "LLM provider changed from openai to anthropic",
            "New workflow pattern: multi-provider-routing detected",
            "Docker service orchestrator restarted twice",
            "Runtime health degraded: 0.85 → 0.42",
            "Volatility score: 0.72 | Stability: 0.28 | Total changes: 7",
        ],
        "confidence": 0.65,
        "uncertainty_notes": [
            "Change detection compares key fields only (LLM providers, frameworks, docker)",
            "Sub-field changes within packages are not captured in this analysis",
        ],
        "related_snapshot_ids": [1, 2, 3, 4],
        "related_workflows": ["multi_provider"],
        "related_runtime_events": ["orchestrator restart"],
        "related_recommendations": [],
    }
    base.update(overrides)
    return base


def _weak_result(**overrides) -> dict:
    base = {
        "kind": "severity_increase",
        "summary": "Insufficient data.",
        "evidence_chain": ["some change"],
        "confidence": 0.85,
        "uncertainty_notes": [],
        "related_snapshot_ids": [1],
        "related_workflows": [],
        "related_runtime_events": [],
        "related_recommendations": ["Reduce token overhead"],
    }
    base.update(overrides)
    return base


def _empty_result() -> dict:
    return {
        "kind": "component_involvement",
        "summary": "No data.",
        "evidence_chain": [],
        "confidence": 0.0,
        "uncertainty_notes": [],
        "related_snapshot_ids": [],
        "related_workflows": [],
        "related_runtime_events": [],
        "related_recommendations": [],
    }


# ---------------------------------------------------------------------------
# InvestigationQualityFlags
# ---------------------------------------------------------------------------

class TestInvestigationQualityFlags:
    def test_all_clear_any_flag_false(self):
        flags = InvestigationQualityFlags()
        assert not flags.any_flag

    def test_any_flag_true_on_sparse(self):
        flags = InvestigationQualityFlags(sparse_evidence=True)
        assert flags.any_flag

    def test_flag_count_zero_when_clear(self):
        assert InvestigationQualityFlags().flag_count == 0

    def test_flag_count_sums_correctly(self):
        flags = InvestigationQualityFlags(sparse_evidence=True, shallow_evidence=True)
        assert flags.flag_count == 2

    def test_to_dict_includes_any_flag(self):
        flags = InvestigationQualityFlags(missing_uncertainty_notes=True)
        d = flags.to_dict()
        assert "any_flag" in d
        assert d["any_flag"] is True
        assert "flag_count" in d

    def test_to_dict_all_fields_present(self):
        d = InvestigationQualityFlags().to_dict()
        for field in [
            "sparse_evidence", "shallow_evidence", "low_snapshot_coverage",
            "confidence_miscalibrated", "missing_uncertainty_notes", "zero_confidence",
        ]:
            assert field in d


# ---------------------------------------------------------------------------
# Evidence depth scoring
# ---------------------------------------------------------------------------

class TestEvidenceDepthScore:
    def test_zero_items_score_zero(self):
        result = _score_evidence_depth([])
        assert result.score == pytest.approx(0.0)
        assert result.is_sparse

    def test_one_item_low_score(self):
        result = _score_evidence_depth(["single item here"])
        assert result.score < 0.30

    def test_three_items_adequate(self):
        result = _score_evidence_depth(["a b c d e", "x y z a b", "p q r s t"])
        assert result.score >= 0.55
        assert not result.is_sparse

    def test_strong_item_count_high_score(self):
        items = [f"item {i} with sufficient words here" for i in range(7)]
        result = _score_evidence_depth(items)
        assert result.score >= 0.85

    def test_shallow_items_penalised(self):
        # 4 of 5 items are very short
        items = ["ok", "hi", "x", "y", "substantive evidence about token overhead in pipeline"]
        result = _score_evidence_depth(items)
        assert result.is_shallow

    def test_non_shallow_items_not_penalised(self):
        items = [
            "Token overhead detected in batch processing module",
            "Provider latency spike during high-traffic window",
        ]
        result = _score_evidence_depth(items)
        assert not result.is_shallow

    def test_evidence_count_accurate(self):
        result = _score_evidence_depth(["a", "b", "c"])
        assert result.evidence_count == 3

    def test_short_item_count_accurate(self):
        result = _score_evidence_depth(["hi", "a b c d e f g"])
        assert result.short_item_count == 1


# ---------------------------------------------------------------------------
# Snapshot coverage scoring
# ---------------------------------------------------------------------------

class TestSnapshotCoverage:
    def test_zero_snapshots_zero_score(self):
        score, minimum = _score_snapshot_coverage("recent_changes", [])
        assert score == pytest.approx(0.0)
        assert minimum == 3

    def test_meets_minimum_full_score(self):
        score, _ = _score_snapshot_coverage("recent_changes", [1, 2, 3])
        assert score == pytest.approx(1.0)

    def test_partial_coverage_fractional(self):
        score, minimum = _score_snapshot_coverage("recent_changes", [1])
        assert score == pytest.approx(1 / 3)
        assert minimum == 3

    def test_single_minimum_kind_needs_one(self):
        score, minimum = _score_snapshot_coverage("recommendation_evidence", [42])
        assert score == pytest.approx(1.0)
        assert minimum == 1

    def test_unknown_kind_uses_default_of_one(self):
        score, minimum = _score_snapshot_coverage("unknown_kind", [99])
        assert minimum == 1
        assert score == pytest.approx(1.0)

    def test_extra_snapshots_still_score_1(self):
        score, _ = _score_snapshot_coverage("severity_increase", [1, 2, 3, 4, 5])
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

class TestConfidenceCalibration:
    def test_adequate_confidence_with_good_evidence_scores_1(self):
        # 5 items, confidence 0.65 — well-calibrated
        score = _score_confidence_calibration(0.65, 5)
        assert score == pytest.approx(1.0)

    def test_high_confidence_sparse_evidence_suspicious(self):
        # 1 item, confidence 0.85 — suspicious
        score = _score_confidence_calibration(0.85, 1)
        assert score < 0.60

    def test_low_confidence_zero_evidence_ok(self):
        score = _score_confidence_calibration(0.05, 0)
        assert score == pytest.approx(1.0)

    def test_high_confidence_zero_evidence_bad(self):
        score = _score_confidence_calibration(0.90, 0)
        assert score < 0.50

    def test_borderline_evidence_count_below_min(self):
        # 2 items (below min=3), confidence 0.85 → suspicious
        score = _score_confidence_calibration(0.85, 2)
        assert score < 0.60


# ---------------------------------------------------------------------------
# Uncertainty completeness
# ---------------------------------------------------------------------------

class TestUncertaintyCompleteness:
    def test_no_notes_low_score(self):
        score = _score_uncertainty_completeness([])
        assert score < 0.60

    def test_two_substantive_notes_full_score(self):
        notes = [
            "This analysis compares structural fields only — no confirmed causal claims are made",
            "Confidence reflects detection strength only, not confirmed operational certainty or causation",
        ]
        score = _score_uncertainty_completeness(notes)
        assert score == pytest.approx(1.0)

    def test_one_substantive_note_high_score(self):
        notes = ["This analysis is heuristic-based and may not reflect live runtime state"]
        score = _score_uncertainty_completeness(notes)
        assert score >= 0.80

    def test_multiple_short_notes_moderate_score(self):
        notes = ["caveat", "uncertainty"]
        score = _score_uncertainty_completeness(notes)
        assert 0.50 <= score <= 0.90


# ---------------------------------------------------------------------------
# Quality band
# ---------------------------------------------------------------------------

class TestQualityBand:
    def test_strong(self):
        assert _quality_band(0.80) == "strong"

    def test_adequate(self):
        assert _quality_band(0.60) == "adequate"

    def test_limited(self):
        assert _quality_band(0.35) == "limited"

    def test_insufficient(self):
        assert _quality_band(0.10) == "insufficient"

    def test_boundary_strong(self):
        assert _quality_band(0.75) == "strong"

    def test_boundary_adequate(self):
        assert _quality_band(0.50) == "adequate"

    def test_boundary_limited(self):
        assert _quality_band(0.25) == "limited"


# ---------------------------------------------------------------------------
# InvestigationQualityEngine.score()
# ---------------------------------------------------------------------------

class TestEngineScore:
    def test_good_result_strong_band(self):
        engine = InvestigationQualityEngine()
        assessment = engine.score(_good_result())
        assert assessment.quality_band == "strong"
        assert assessment.quality_score >= 0.75

    def test_empty_result_insufficient(self):
        engine = InvestigationQualityEngine()
        assessment = engine.score(_empty_result())
        assert assessment.quality_band in ("limited", "insufficient")

    def test_score_in_range(self):
        engine = InvestigationQualityEngine()
        for result in [_good_result(), _weak_result(), _empty_result()]:
            a = engine.score(result)
            assert 0.0 <= a.quality_score <= 1.0

    def test_weak_result_flags_set(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_weak_result())
        assert a.flags.sparse_evidence
        assert a.flags.confidence_miscalibrated
        assert a.flags.missing_uncertainty_notes

    def test_good_result_no_flags(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_good_result())
        assert not a.flags.any_flag

    def test_kind_preserved_in_assessment(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_good_result())
        assert a.kind == "recent_changes"

    def test_observations_nonempty(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_good_result())
        assert a.observations

    def test_guidance_nonempty(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_good_result())
        assert a.guidance

    def test_to_dict_complete(self):
        engine = InvestigationQualityEngine()
        d = engine.score(_good_result()).to_dict()
        for key in [
            "kind", "quality_score", "quality_band", "flags",
            "evidence_depth", "snapshot_coverage_score", "snapshot_count",
            "confidence_calibration_score", "uncertainty_completeness_score",
            "observations", "guidance", "advisory", "generated_at",
        ]:
            assert key in d

    def test_snapshot_count_accurate(self):
        engine = InvestigationQualityEngine()
        result = _good_result()
        a = engine.score(result)
        assert a.snapshot_count == len(result["related_snapshot_ids"])

    def test_evidence_depth_populated(self):
        engine = InvestigationQualityEngine()
        a = engine.score(_good_result())
        assert a.evidence_depth.evidence_count == 5
        assert isinstance(a.evidence_depth, EvidenceDepthScore)


# ---------------------------------------------------------------------------
# InvestigationQualityEngine.triage()
# ---------------------------------------------------------------------------

class TestEngineTriage:
    def test_returns_triage_report(self):
        engine = InvestigationQualityEngine()
        triage = engine.triage(_weak_result())
        assert isinstance(triage, InvestigationTriageReport)

    def test_coverage_fraction_includes_current(self):
        engine = InvestigationQualityEngine()
        triage = engine.triage(_good_result(), completed_kinds=["recent_changes"])
        assert triage.coverage_fraction == pytest.approx(1 / 6)

    def test_completed_kinds_in_remaining_not_suggested(self):
        engine = InvestigationQualityEngine()
        completed = ["recent_changes", "component_involvement"]
        triage = engine.triage(_good_result(), completed_kinds=completed)
        for sug in triage.suggestions:
            if sug.kind is not None:
                assert sug.kind not in completed

    def test_suggestions_nonempty_for_incomplete_session(self):
        engine = InvestigationQualityEngine()
        triage = engine.triage(_good_result(), completed_kinds=["recent_changes"])
        assert len(triage.suggestions) >= 1

    def test_limited_quality_generates_high_priority_suggestion(self):
        engine = InvestigationQualityEngine()
        triage = engine.triage(_weak_result())
        priorities = [s.priority for s in triage.suggestions]
        assert "high" in priorities

    def test_severity_increase_with_recs_suggests_recommendation_evidence(self):
        engine = InvestigationQualityEngine()
        result = _weak_result(kind="severity_increase", related_recommendations=["Fix token overhead"])
        triage = engine.triage(result, completed_kinds=["severity_increase"])
        kinds = [s.kind for s in triage.suggestions]
        assert "recommendation_evidence" in kinds

    def test_recent_changes_with_confidence_suggests_component_involvement(self):
        engine = InvestigationQualityEngine()
        result = _good_result(kind="recent_changes", confidence=0.60)
        triage = engine.triage(result, completed_kinds=["recent_changes"])
        kinds = [s.kind for s in triage.suggestions]
        assert "component_involvement" in kinds

    def test_remaining_kinds_complement_completed(self):
        engine = InvestigationQualityEngine()
        completed = ["recent_changes", "severity_increase"]
        triage = engine.triage(_good_result(), completed_kinds=completed)
        for kind in completed:
            assert kind not in triage.remaining_kinds

    def test_to_dict_complete(self):
        engine = InvestigationQualityEngine()
        d = engine.triage(_good_result()).to_dict()
        for key in [
            "current_kind", "quality_assessment", "suggestions",
            "completed_kinds", "remaining_kinds", "coverage_fraction",
            "advisory", "generated_at",
        ]:
            assert key in d

    def test_suggestions_capped_at_five(self):
        engine = InvestigationQualityEngine()
        triage = engine.triage(_good_result(), completed_kinds=[])
        assert len(triage.suggestions) <= 5


# ---------------------------------------------------------------------------
# InvestigationQualityEngine.batch_score()
# ---------------------------------------------------------------------------

class TestBatchScore:
    def test_batch_length_matches_input(self):
        engine = InvestigationQualityEngine()
        results = [_good_result(), _weak_result(), _empty_result()]
        pairs = engine.batch_score(results)
        assert len(pairs) == 3

    def test_batch_returns_result_assessment_tuples(self):
        engine = InvestigationQualityEngine()
        pairs = engine.batch_score([_good_result()])
        result, assessment = pairs[0]
        assert isinstance(result, dict)
        assert isinstance(assessment, InvestigationQualityAssessment)

    def test_empty_batch(self):
        engine = InvestigationQualityEngine()
        assert engine.batch_score([]) == []


# ---------------------------------------------------------------------------
# Report generators (Phase 13C additions to investigation_report.py)
# ---------------------------------------------------------------------------

class TestGenerateQualityScoredReport:
    def _quality_dict(self, result: dict) -> dict:
        return InvestigationQualityEngine().score(result).to_dict()

    def test_returns_nonempty_string(self):
        result = _good_result()
        report = generate_quality_scored_report(result, self._quality_dict(result))
        assert isinstance(report, str)
        assert len(report) > 100

    def test_contains_band(self):
        result = _good_result()
        quality = self._quality_dict(result)
        report = generate_quality_scored_report(result, quality)
        assert quality["quality_band"].upper() in report

    def test_contains_kind(self):
        result = _good_result()
        report = generate_quality_scored_report(result, self._quality_dict(result))
        assert result["kind"] in report

    def test_limited_quality_contains_warning(self):
        result = _weak_result()
        quality = self._quality_dict(result)
        report = generate_quality_scored_report(result, quality)
        assert "warning" in report.lower() or "limited" in report.lower()

    def test_advisory_footer_present(self):
        result = _good_result()
        report = generate_quality_scored_report(result, self._quality_dict(result))
        assert "Advisory" in report or "advisory" in report.lower()

    def test_guidance_included(self):
        result = _good_result()
        quality = self._quality_dict(result)
        report = generate_quality_scored_report(result, quality)
        assert len(report.split("\n")) > 10


class TestGenerateTriageReport:
    def _triage_dict(self, result: dict) -> dict:
        return InvestigationQualityEngine().triage(result).to_dict()

    def test_returns_string(self):
        result = _good_result()
        report = generate_triage_report(self._triage_dict(result))
        assert isinstance(report, str)
        assert len(report) > 50

    def test_contains_current_kind(self):
        result = _good_result()
        report = generate_triage_report(self._triage_dict(result))
        assert result["kind"] in report

    def test_contains_advisory_footer(self):
        result = _good_result()
        report = generate_triage_report(self._triage_dict(result))
        assert "Advisory" in report or "advisory" in report.lower()

    def test_contains_quality_band(self):
        result = _good_result()
        triage_dict = self._triage_dict(result)
        report = generate_triage_report(triage_dict)
        band = triage_dict["quality_assessment"]["quality_band"].upper()
        assert band in report

    def test_contains_next_steps_section(self):
        result = _good_result()
        report = generate_triage_report(self._triage_dict(result))
        assert "Next Steps" in report or "Suggested" in report
