"""Tests for cognition/confidence.py — ConfidenceNormalizer."""

from __future__ import annotations

from cognition.confidence import ConfidenceNormalizer, ConfidenceScore


class TestConfidenceNormalizerBasic:
    def test_returns_confidence_score(self):
        result = ConfidenceNormalizer().normalize(0.8, 3)
        assert isinstance(result, ConfidenceScore)

    def test_value_bounded(self):
        result = ConfidenceNormalizer().normalize(0.8, 5)
        assert 0.0 <= result.value <= 1.0

    def test_zero_evidence_low_confidence(self):
        result = ConfidenceNormalizer().normalize(0.9, 0)
        assert result.value < 0.5

    def test_many_evidence_higher_confidence(self):
        low = ConfidenceNormalizer().normalize(0.5, 1)
        high = ConfidenceNormalizer().normalize(0.5, 10)
        assert high.value > low.value

    def test_temporal_support_increases_confidence(self):
        without = ConfidenceNormalizer().normalize(0.7, 3, temporal_support=False)
        with_ = ConfidenceNormalizer().normalize(0.7, 3, temporal_support=True)
        assert with_.value >= without.value

    def test_recurrence_support_increases_confidence(self):
        without = ConfidenceNormalizer().normalize(0.7, 3, recurrence_support=False)
        with_ = ConfidenceNormalizer().normalize(0.7, 3, recurrence_support=True)
        assert with_.value >= without.value

    def test_snapshot_count_increases_confidence(self):
        single = ConfidenceNormalizer().normalize(0.7, 3, snapshot_count=1)
        multi = ConfidenceNormalizer().normalize(0.7, 3, snapshot_count=10)
        assert multi.value >= single.value


class TestConfidenceScoreFields:
    def test_evidence_count_stored(self):
        score = ConfidenceNormalizer().normalize(0.8, 4)
        assert score.evidence_count == 4

    def test_snapshot_support_false_for_single(self):
        score = ConfidenceNormalizer().normalize(0.8, 3, snapshot_count=1)
        assert score.snapshot_support is False

    def test_snapshot_support_true_for_multiple(self):
        score = ConfidenceNormalizer().normalize(0.8, 3, snapshot_count=3)
        assert score.snapshot_support is True

    def test_temporal_support_stored(self):
        score = ConfidenceNormalizer().normalize(0.8, 3, temporal_support=True)
        assert score.temporal_support is True

    def test_recurrence_support_stored(self):
        score = ConfidenceNormalizer().normalize(0.8, 3, recurrence_support=True)
        assert score.recurrence_support is True

    def test_interpretation_set(self):
        score = ConfidenceNormalizer().normalize(0.8, 5)
        assert score.interpretation in ("strong", "moderate", "low", "very low", "insufficient")

    def test_basis_set(self):
        score = ConfidenceNormalizer().normalize(0.8, 3)
        assert score.basis != ""

    def test_to_dict_structure(self):
        score = ConfidenceNormalizer().normalize(0.8, 3)
        d = score.to_dict()
        assert "value" in d
        assert "evidence_count" in d
        assert "interpretation" in d
        assert "advisory" in d
        assert "basis" in d


class TestInterpretation:
    def test_high_score_is_strong(self):
        interp = ConfidenceNormalizer().interpret(0.85)
        assert interp == "strong"

    def test_zero_score_is_insufficient(self):
        interp = ConfidenceNormalizer().interpret(0.0)
        assert interp == "insufficient"

    def test_moderate_score(self):
        interp = ConfidenceNormalizer().interpret(0.65)
        assert interp == "moderate"


class TestFromEvidenceOnly:
    def test_empty_evidence_zero_confidence(self):
        score = ConfidenceNormalizer().from_evidence_only([])
        assert score.value == 0.0
        assert score.evidence_count == 0

    def test_blank_items_not_counted(self):
        score = ConfidenceNormalizer().from_evidence_only(["", "  "])
        assert score.evidence_count == 0

    def test_nonempty_evidence_gives_positive_confidence(self):
        score = ConfidenceNormalizer().from_evidence_only(["signal A", "signal B", "signal C"])
        assert score.value > 0.0
        assert score.evidence_count == 3


class TestFromSynthesisInputs:
    def test_returns_score(self):
        score = ConfidenceNormalizer().from_synthesis_inputs(5, 3, True, True)
        assert isinstance(score, ConfidenceScore)
        assert 0.0 <= score.value <= 1.0

    def test_more_inputs_higher_confidence(self):
        low = ConfidenceNormalizer().from_synthesis_inputs(1, 0, False, False)
        high = ConfidenceNormalizer().from_synthesis_inputs(10, 5, True, True)
        assert high.value > low.value

    def test_no_snapshots_zero_confidence(self):
        score = ConfidenceNormalizer().from_synthesis_inputs(0, 0, False, False)
        assert score.value == 0.0


class TestConfidenceNote:
    def test_returns_string(self):
        score = ConfidenceNormalizer().normalize(0.7, 3)
        note = ConfidenceNormalizer().confidence_note(score)
        assert isinstance(note, str)

    def test_note_contains_evidence_count(self):
        score = ConfidenceNormalizer().normalize(0.7, 3)
        note = ConfidenceNormalizer().confidence_note(score)
        assert "3" in note

    def test_note_contains_not_probability(self):
        score = ConfidenceNormalizer().normalize(0.7, 3)
        note = ConfidenceNormalizer().confidence_note(score)
        assert "probability" in note.lower()
