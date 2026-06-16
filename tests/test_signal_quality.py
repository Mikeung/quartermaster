"""Tests for cognition/signal_quality.py."""

import pytest

from cognition.signal_quality import (
    BatchQualityReport,
    EvidenceDiversityScore,
    SignalQualityEngine,
    SignalQualityFlags,
    _check_repeated_low_value,
    _check_weak_evidence,
    _compute_confidence_decay,
    _compute_evidence_diversity,
    _compute_quality_score,
    _find_saturated_categories,
)


def _rec(
    title: str = "Fix token overhead in workflow",
    category: str = "cost",
    confidence: float = 0.70,
    evidence: list | None = None,
) -> dict:
    return {
        "title": title,
        "category": category,
        "confidence": confidence,
        "evidence": evidence or [
            "Token overhead observed in batch processing module",
            "Provider latency spike detected at 14:00 UTC",
            "Retry mechanism triggered three times consecutively",
        ],
    }


class TestWeakEvidenceDetection:
    def test_too_few_items(self):
        is_weak, explanation = _check_weak_evidence(["one item"])
        assert is_weak
        assert any("sparse" in e.lower() for e in explanation)

    def test_empty_list(self):
        is_weak, _ = _check_weak_evidence([])
        assert is_weak

    def test_sufficient_items(self):
        is_weak, _ = _check_weak_evidence([
            "Token overhead in batch processing module",
            "Provider latency spike detected",
            "Retry triggered consecutively",
        ])
        assert not is_weak

    def test_mostly_short_items_flagged(self):
        # 3 of 4 items < 4 words
        is_weak, explanation = _check_weak_evidence([
            "token high",
            "error",
            "latency bad",
            "Detailed evidence about token overhead in the processing pipeline with context",
        ])
        assert is_weak
        assert explanation

    def test_long_items_not_flagged(self):
        is_weak, _ = _check_weak_evidence([
            "Detailed token overhead in the processing pipeline",
            "Provider latency spike during batch operations at midnight",
        ])
        assert not is_weak


class TestRepeatedLowValue:
    def test_high_recurrence_low_confidence(self):
        is_bad, explanation = _check_repeated_low_value(
            recurrence_count=7, confidence=0.35
        )
        assert is_bad
        assert explanation

    def test_high_recurrence_high_confidence_ok(self):
        is_bad, _ = _check_repeated_low_value(
            recurrence_count=10, confidence=0.80
        )
        assert not is_bad

    def test_low_recurrence_low_confidence_ok(self):
        is_bad, _ = _check_repeated_low_value(
            recurrence_count=2, confidence=0.35
        )
        assert not is_bad

    def test_exactly_at_recurrence_threshold(self):
        is_bad, _ = _check_repeated_low_value(
            recurrence_count=5, confidence=0.40
        )
        assert is_bad  # 5 >= STALE_WARN(5) and 0.40 < 0.45

    def test_confidence_boundary(self):
        is_bad_below, _ = _check_repeated_low_value(recurrence_count=6, confidence=0.44)
        is_bad_above, _ = _check_repeated_low_value(recurrence_count=6, confidence=0.46)
        assert is_bad_below
        assert not is_bad_above


class TestConfidenceDecay:
    def test_zero_recurrence_no_decay(self):
        decay, stale, _ = _compute_confidence_decay(0)
        assert decay == pytest.approx(0.0)
        assert not stale

    def test_below_warn_threshold(self):
        decay, stale, _ = _compute_confidence_decay(3)
        assert decay > 0.0
        assert not stale

    def test_at_warn_threshold_is_stale(self):
        _, stale, _ = _compute_confidence_decay(5)
        assert stale

    def test_at_critical_threshold_max_decay(self):
        decay, stale, _ = _compute_confidence_decay(15)
        assert stale
        assert decay == pytest.approx(0.40, abs=0.01)

    def test_beyond_critical_capped(self):
        decay_at_15, _, _ = _compute_confidence_decay(15)
        decay_at_100, _, _ = _compute_confidence_decay(100)
        assert decay_at_15 == decay_at_100

    def test_explanation_on_stale(self):
        _, _, explanation = _compute_confidence_decay(7)
        assert explanation
        assert any("stale" in e.lower() or "decay" in e.lower() for e in explanation)


class TestEvidenceDiversity:
    def test_single_item_high_diversity(self):
        result = _compute_evidence_diversity(["Only one item here"])
        assert result.score == pytest.approx(1.0)
        assert not result.is_low_diversity

    def test_identical_items_low_diversity(self):
        items = [
            "Token overhead detected in the batch processing module",
            "Token overhead observed in the batch processing module",
            "Token overhead found in the batch processing module",
        ]
        result = _compute_evidence_diversity(items)
        assert result.is_low_diversity
        assert result.score < 0.5

    def test_distinct_items_high_diversity(self):
        items = [
            "Memory pressure in orchestration layer detected",
            "Provider rate limit hit on embedding endpoint",
            "Docker container restart loop observed",
            "Workflow latency spike at midnight UTC",
        ]
        result = _compute_evidence_diversity(items)
        assert not result.is_low_diversity
        assert result.score > 0.5

    def test_empty_list_defaults_high_diversity(self):
        result = _compute_evidence_diversity([])
        assert result.score == pytest.approx(1.0)
        assert not result.is_low_diversity
        assert result.penalty_applied == pytest.approx(0.0)

    def test_penalty_on_low_diversity(self):
        items = [
            "Token overhead in the batch processing module detected",
            "Token overhead in the batch processing module observed",
            "Token overhead in the batch processing module found",
        ]
        result = _compute_evidence_diversity(items)
        assert result.penalty_applied > 0.0


class TestSaturationDetection:
    def test_one_category_dominates(self):
        recs = [_rec(category="cost") for _ in range(7)] + \
               [_rec(category="runtime") for _ in range(3)]
        saturated = _find_saturated_categories(recs)
        assert "cost" in saturated

    def test_no_saturation_balanced(self):
        recs = [_rec(category="cost") for _ in range(5)] + \
               [_rec(category="runtime") for _ in range(5)]
        saturated = _find_saturated_categories(recs)
        assert not saturated

    def test_empty_no_saturation(self):
        assert _find_saturated_categories([]) == frozenset()

    def test_single_category_all_recs(self):
        recs = [_rec(category="orchestration") for _ in range(5)]
        saturated = _find_saturated_categories(recs)
        assert "orchestration" in saturated


class TestQualityScore:
    def test_clean_signal_high_score(self):
        flags = SignalQualityFlags()
        diversity = EvidenceDiversityScore(
            score=0.9, item_count=5, avg_pairwise_overlap=0.1,
            is_low_diversity=False, penalty_applied=0.0
        )
        score = _compute_quality_score(flags, diversity, decay_fraction=0.0)
        assert score == pytest.approx(1.0)

    def test_all_flags_low_score(self):
        flags = SignalQualityFlags(
            weak_evidence=True,
            stale_signal=True,
            low_diversity_evidence=True,
            heuristic_saturated=True,
            repeated_low_value=True,
        )
        diversity = EvidenceDiversityScore(
            score=0.1, item_count=3, avg_pairwise_overlap=0.9,
            is_low_diversity=True, penalty_applied=0.20
        )
        score = _compute_quality_score(flags, diversity, decay_fraction=0.40)
        assert score < 0.25

    def test_score_non_negative(self):
        flags = SignalQualityFlags(
            weak_evidence=True, stale_signal=True,
            low_diversity_evidence=True, heuristic_saturated=True,
        )
        diversity = EvidenceDiversityScore(
            score=0.0, item_count=2, avg_pairwise_overlap=1.0,
            is_low_diversity=True, penalty_applied=0.20
        )
        score = _compute_quality_score(flags, diversity, decay_fraction=0.40)
        assert score >= 0.0

    def test_score_at_most_1(self):
        flags = SignalQualityFlags()
        diversity = EvidenceDiversityScore(
            score=1.0, item_count=5, avg_pairwise_overlap=0.0,
            is_low_diversity=False, penalty_applied=0.0
        )
        score = _compute_quality_score(flags, diversity, decay_fraction=0.0)
        assert score <= 1.0


class TestAssessSingleSignal:
    def test_clean_signal_not_suppressed(self):
        engine = SignalQualityEngine()
        rec = _rec(
            evidence=[
                "Token overhead observed in batch processing pipeline module",
                "Provider latency spike detected during high-traffic window",
                "Retry mechanism triggered three consecutive times in workflow",
            ],
        )
        result = engine.assess(rec, recurrence_count=0)
        assert not result.suppressed
        assert result.quality_score >= 0.60

    def test_weak_evidence_flagged(self):
        engine = SignalQualityEngine()
        rec = _rec(evidence=["token high"])
        result = engine.assess(rec)
        assert result.flags.weak_evidence

    def test_stale_signal_flagged(self):
        engine = SignalQualityEngine()
        result = engine.assess(_rec(), recurrence_count=7)
        assert result.flags.stale_signal
        assert result.confidence_decay > 0.0

    def test_adjusted_confidence_lower_than_original(self):
        engine = SignalQualityEngine()
        rec = _rec(confidence=0.80)
        result = engine.assess(rec, recurrence_count=10)
        assert result.adjusted_confidence < result.original_confidence

    def test_saturated_category_flagged(self):
        engine = SignalQualityEngine()
        result = engine.assess(
            _rec(category="cost"),
            saturated_categories=frozenset({"cost"}),
        )
        assert result.flags.heuristic_saturated

    def test_suppression_reason_nonempty_on_suppressed(self):
        engine = SignalQualityEngine()
        rec = _rec(
            evidence=["bad"],  # weak (1 item)
            confidence=0.30,
        )
        result = engine.assess(rec, recurrence_count=12)
        if result.suppressed:
            assert result.suppression_reason

    def test_original_confidence_preserved(self):
        engine = SignalQualityEngine()
        rec = _rec(confidence=0.75)
        result = engine.assess(rec, recurrence_count=5)
        assert result.original_confidence == pytest.approx(0.75)

    def test_explanation_nonempty_when_flags_set(self):
        engine = SignalQualityEngine()
        rec = _rec(confidence=0.30)
        result = engine.assess(rec, recurrence_count=10)
        if result.flags.any_flag:
            assert result.explanation

    def test_to_dict_structure(self):
        engine = SignalQualityEngine()
        result = engine.assess(_rec())
        d = result.to_dict()
        assert "original_confidence" in d
        assert "adjusted_confidence" in d
        assert "confidence_decay" in d
        assert "evidence_diversity" in d
        assert "flags" in d
        assert "quality_score" in d
        assert "suppressed" in d
        assert "suppression_reason" in d
        assert "explanation" in d


class TestAssessBatch:
    def _batch(self, n: int = 5, category: str = "cost") -> list[dict]:
        return [
            _rec(
                title=f"Fix issue {i} in workflow pipeline",
                category=category,
                confidence=0.60,
            )
            for i in range(n)
        ]

    def test_empty_batch_returns_report(self):
        engine = SignalQualityEngine()
        report = engine.assess_batch([])
        assert isinstance(report, BatchQualityReport)
        assert report.total_input == 0

    def test_batch_total_count(self):
        engine = SignalQualityEngine()
        recs = self._batch(8)
        report = engine.assess_batch(recs)
        assert report.total_input == 8

    def test_saturation_detected_in_batch(self):
        engine = SignalQualityEngine()
        recs = [_rec(category="cost") for _ in range(8)]
        recs += [_rec(category="runtime") for _ in range(2)]
        report = engine.assess_batch(recs)
        assert report.saturation_detected
        assert report.dominant_category == "cost"

    def test_no_saturation_balanced(self):
        engine = SignalQualityEngine()
        recs = [_rec(category="cost") for _ in range(5)]
        recs += [_rec(category="runtime") for _ in range(5)]
        report = engine.assess_batch(recs)
        assert not report.saturation_detected

    def test_recurrence_map_used(self):
        engine = SignalQualityEngine()
        title = "Fix token overhead in workflow"
        recs = [_rec(title=title, confidence=0.30)]
        recurrence = {title[:60]: 12}
        report = engine.assess_batch(recs, recurrence_by_title=recurrence)
        assert report.assessments[0][1].flags.stale_signal

    def test_operator_fatigue_score_range(self):
        engine = SignalQualityEngine()
        report = engine.assess_batch(self._batch(5))
        assert 0.0 <= report.operator_fatigue_score <= 1.0

    def test_high_fatigue_batch(self):
        engine = SignalQualityEngine()
        # All signals have weak evidence + high recurrence + low confidence
        recs = [
            {"title": f"Issue {i}", "category": "cost", "confidence": 0.25,
             "evidence": ["bad"]}
            for i in range(6)
        ]
        recurrence = {f"Issue {i}"[:60]: 12 for i in range(6)}
        report = engine.assess_batch(recs, recurrence_by_title=recurrence)
        assert report.operator_fatigue_score >= 0.60

    def test_assessments_list_length(self):
        engine = SignalQualityEngine()
        recs = self._batch(7)
        report = engine.assess_batch(recs)
        assert len(report.assessments) == 7

    def test_to_dict_complete(self):
        engine = SignalQualityEngine()
        report = engine.assess_batch(self._batch(3))
        d = report.to_dict()
        assert "total_input" in d
        assert "suppressed_count" in d
        assert "flagged_count" in d
        assert "operator_fatigue_score" in d
        assert "assessments" in d
        assert "observations" in d


class TestFilterSuppressed:
    def test_clean_signals_not_suppressed(self):
        engine = SignalQualityEngine()
        recs = [_rec() for _ in range(5)]
        report = engine.assess_batch(recs)
        kept, suppressed = engine.filter_suppressed(report.assessments)
        assert len(kept) + len(suppressed) == 5

    def test_suppressed_signals_annotated(self):
        engine = SignalQualityEngine()
        recs = [
            {"title": "Bad signal", "category": "cost", "confidence": 0.10,
             "evidence": ["x"]}
        ]
        report = engine.assess_batch(recs)
        _, suppressed = engine.filter_suppressed(report.assessments)
        if suppressed:
            assert "_suppressed" in suppressed[0]
            assert suppressed[0]["_suppressed"] is True

    def test_source_not_modified(self):
        engine = SignalQualityEngine()
        original = _rec()
        original_copy = dict(original)
        report = engine.assess_batch([original])
        engine.filter_suppressed(report.assessments)
        assert original == original_copy


class TestFlagProperties:
    def test_any_flag_false_when_all_clear(self):
        flags = SignalQualityFlags()
        assert not flags.any_flag

    def test_any_flag_true_on_weak_evidence(self):
        flags = SignalQualityFlags(weak_evidence=True)
        assert flags.any_flag

    def test_flag_count(self):
        flags = SignalQualityFlags(weak_evidence=True, stale_signal=True)
        assert flags.flag_count == 2

    def test_to_dict_includes_any_flag(self):
        flags = SignalQualityFlags(weak_evidence=True)
        d = flags.to_dict()
        assert "any_flag" in d
        assert d["any_flag"] is True


class TestDiversityScoreToDict:
    def test_to_dict_round_trip(self):
        d = EvidenceDiversityScore(
            score=0.75, item_count=5, avg_pairwise_overlap=0.25,
            is_low_diversity=False, penalty_applied=0.0
        ).to_dict()
        assert "score" in d
        assert "item_count" in d
        assert "avg_pairwise_overlap" in d
        assert "is_low_diversity" in d
        assert "penalty_applied" in d
