"""Tests for cognition/deduplication.py."""

import pytest

from cognition.deduplication import (
    DeduplicationSummary,
    SignalDeduplicationEngine,
    _content_words,
    _word_overlap,
)


def _rec(title: str, category: str = "cost", confidence: float = 0.7, evidence=None) -> dict:
    return {
        "title": title,
        "category": category,
        "confidence": confidence,
        "evidence": evidence or [],
    }


class TestEmptyInput:
    def test_empty_list_returns_summary(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([])
        assert isinstance(result, DeduplicationSummary)
        assert result.input_count == 0
        assert result.output_count == 0
        assert result.concerns == []

    def test_empty_observation_says_no_signals(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([])
        assert any("no signals" in o.lower() for o in result.observations)


class TestSingleItem:
    def test_single_item_no_dedup(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([_rec("Fix memory leak in agent")])
        assert result.input_count == 1
        assert result.output_count == 1
        assert result.suppressed_count == 0
        assert not result.concerns[0].deduplicated

    def test_single_item_dedup_ratio_zero(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([_rec("Fix memory leak")])
        assert result.dedup_ratio == 0.0


class TestDistinctItems:
    def test_fully_distinct_items_no_collapse(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Memory pressure in orchestration layer"),
            _rec("Token cost spike in OpenAI provider", category="provider"),
            _rec("Latency regression in OCR pipeline", category="runtime"),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 3
        assert result.suppressed_count == 0
        assert all(not c.deduplicated for c in result.concerns)

    def test_observation_says_distinct(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([
            _rec("Token overhead in workflow"),
            _rec("Docker container restart loop"),
        ])
        assert any("distinct" in o.lower() for o in result.observations)


class TestNearDuplicates:
    def test_identical_titles_are_deduped(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Fix memory leak in orchestration layer", confidence=0.8),
            _rec("Fix memory leak in orchestration layer", confidence=0.6),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 1
        assert result.suppressed_count == 1
        assert result.concerns[0].deduplicated

    def test_high_overlap_titles_are_deduped(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Retry mechanism causing token overhead in batch processing", confidence=0.9),
            _rec("Retry mechanism causing token overhead in batch queue", confidence=0.5),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 1

    def test_representative_is_highest_confidence(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Memory pressure in orchestration layer", confidence=0.4),
            _rec("Memory pressure in orchestration batch system", confidence=0.9),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 1
        assert result.concerns[0].confidence == pytest.approx(0.9)

    def test_source_titles_preserved(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Token cost in OCR workflow is high"),
            _rec("Token cost in OCR workflow exceeds budget"),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 1
        assert len(result.concerns[0].source_titles) == 2


class TestEvidenceKeywordDedup:
    def test_same_category_with_shared_evidence_keywords_deduped(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Agent orchestration overhead", category="orchestration",
                 evidence=["agent retry overhead observed", "concurrency limit hit"]),
            _rec("Orchestration agent retry cost", category="orchestration",
                 evidence=["agent workflow concurrency timeout", "retry queue"]),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 1

    def test_different_categories_not_deduped_by_evidence_alone(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Token cost spike", category="cost",
                 evidence=["token latency overhead"]),
            _rec("Agent memory", category="orchestration",
                 evidence=["token memory agent overhead"]),
        ]
        result = engine.deduplicate(recs)
        assert result.output_count == 2


class TestDedupEvidence:
    def test_identical_evidence_removed(self):
        engine = SignalDeduplicationEngine()
        ev = [
            "Token overhead in provider observed",
            "Token overhead in provider observed",
            "Retry loop detected in workflow",
        ]
        result = engine.deduplicate_evidence(ev)
        assert len(result) == 2

    def test_near_duplicate_evidence_removed(self):
        engine = SignalDeduplicationEngine()
        ev = [
            "High latency detected in OCR processing pipeline",
            "High latency observed in OCR processing pipeline",  # very similar
            "Memory pressure in orchestration layer",
        ]
        result = engine.deduplicate_evidence(ev)
        assert len(result) == 2

    def test_distinct_evidence_preserved(self):
        engine = SignalDeduplicationEngine()
        ev = [
            "Token cost exceeds threshold",
            "Docker container restart loop detected",
            "Memory pressure growing steadily",
        ]
        result = engine.deduplicate_evidence(ev)
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        engine = SignalDeduplicationEngine()
        assert engine.deduplicate_evidence([]) == []

    def test_single_item_returned_as_is(self):
        engine = SignalDeduplicationEngine()
        assert engine.deduplicate_evidence(["one item"]) == ["one item"]


class TestSortingOrder:
    def test_multi_source_concerns_sort_first(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Unique concern A", confidence=0.95),
            _rec("Memory leak in memory layer A", confidence=0.5),
            _rec("Memory leak in memory layer B", confidence=0.7),
        ]
        result = engine.deduplicate(recs)
        assert result.concerns[0].source_count == 2

    def test_within_same_source_count_sorted_by_confidence(self):
        engine = SignalDeduplicationEngine()
        recs = [
            _rec("Alpha concern", confidence=0.4),
            _rec("Beta concern", confidence=0.9),
        ]
        result = engine.deduplicate(recs)
        assert result.concerns[0].confidence >= result.concerns[1].confidence


class TestToDict:
    def test_to_dict_is_serializable(self):
        engine = SignalDeduplicationEngine()
        result = engine.deduplicate([
            _rec("Token cost exceeded", confidence=0.8),
            _rec("Token cost limit hit", confidence=0.6),
        ])
        d = result.to_dict()
        assert "concerns" in d
        assert "groups" in d
        assert "dedup_ratio" in d
        assert isinstance(d["concerns"][0], dict)

    def test_dedup_ratio_non_negative(self):
        engine = SignalDeduplicationEngine()
        for n in [1, 2, 5, 10]:
            recs = [_rec(f"Concern {i}") for i in range(n)]
            result = engine.deduplicate(recs)
            assert result.dedup_ratio >= 0.0


class TestContentWords:
    def test_stopwords_removed(self):
        words = _content_words("the memory is leaking in the orchestration layer")
        assert "the" not in words
        assert "is" not in words
        assert "in" not in words
        assert "memory" in words
        assert "leaking" in words

    def test_short_words_filtered(self):
        words = _content_words("a LLM at high cost")
        assert "a" not in words
        assert "at" not in words

    def test_hyphen_normalized(self):
        words = _content_words("rate-limit exceeded")
        assert "rate" in words
        assert "limit" in words


class TestWordOverlap:
    def test_identical_sets(self):
        a = frozenset(["token", "cost", "spike"])
        assert _word_overlap(a, a) == pytest.approx(1.0)

    def test_disjoint_sets(self):
        a = frozenset(["token"])
        b = frozenset(["memory"])
        assert _word_overlap(a, b) == pytest.approx(0.0)

    def test_both_empty(self):
        assert _word_overlap(frozenset(), frozenset()) == pytest.approx(1.0)

    def test_one_empty(self):
        assert _word_overlap(frozenset(["a"]), frozenset()) == pytest.approx(0.0)

    def test_partial_overlap(self):
        a = frozenset(["token", "cost", "spike"])
        b = frozenset(["token", "cost", "memory"])
        # intersection = 2, union = 4 → 0.5
        assert _word_overlap(a, b) == pytest.approx(0.5)
