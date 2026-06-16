"""Tests for cognition/evidence_compression.py."""

import pytest

from cognition.evidence_compression import (
    EvidenceCompressor,
    _is_protected,
)

_LONG_CHAIN_SIZE = 25  # above _MAX_UNCOMPRESSED_LENGTH (20)


def _make_similar_items(prefix: str, n: int) -> list[str]:
    """Make n similar evidence strings sharing many words."""
    return [f"{prefix} occurred at severity level {i} in component module" for i in range(n)]


def _make_distinct_items(n: int) -> list[str]:
    """Make n evidence strings with minimal word overlap."""
    topics = [
        "Memory pressure in orchestration layer",
        "Token cost spike from provider request",
        "Docker container restart loop detected",
        "Latency regression in OCR pipeline module",
        "Rate limit exceeded on embedding endpoint",
        "Agent retry mechanism overhead batch queue",
        "Workflow concurrency limit hit timeout error",
        "Vector search index rebuild fragmentation",
        "Cost accumulation in streaming multi-turn",
        "Scheduler stale job degradation failure",
    ]
    return [topics[i % len(topics)] + f" {i}" for i in range(n)]


class TestShortChains:
    def test_short_chain_not_compressed(self):
        compressor = EvidenceCompressor()
        chain = _make_distinct_items(10)
        result = compressor.compress(chain)
        assert not result.was_compressed
        assert result.compression_ratio == pytest.approx(0.0)

    def test_short_chain_output_equals_input(self):
        compressor = EvidenceCompressor()
        chain = ["evidence A", "evidence B", "evidence C"]
        result = compressor.compress(chain)
        assert result.compressed == chain

    def test_empty_chain_returns_empty(self):
        compressor = EvidenceCompressor()
        result = compressor.compress([])
        assert result.compressed == []
        assert not result.was_compressed
        assert result.original_count == 0


class TestProtectedEvidence:
    def test_critical_evidence_preserved(self):
        compressor = EvidenceCompressor()
        evidence = (
            _make_similar_items("token overhead occurred", _LONG_CHAIN_SIZE)
            + ["critical: system failure imminent"]
        )
        result = compressor.compress(evidence)
        assert any("critical" in e for e in result.compressed)
        assert any("critical" in e for e in result.protected)

    def test_uncertainty_evidence_preserved(self):
        compressor = EvidenceCompressor()
        evidence = (
            _make_similar_items("latency spike in module", _LONG_CHAIN_SIZE)
            + ["unclear whether this affects production"]
        )
        result = compressor.compress(evidence)
        assert any("unclear" in e for e in result.protected)

    def test_conflict_evidence_preserved(self):
        compressor = EvidenceCompressor()
        evidence = (
            _make_similar_items("cost pattern detected", _LONG_CHAIN_SIZE)
            + ["token count is high, however some requests succeed"]
        )
        result = compressor.compress(evidence)
        assert any("however" in e for e in result.protected)

    def test_all_protected_markers(self):
        assert _is_protected("critical failure in production")
        assert _is_protected("unclear whether this is real")
        assert _is_protected("appears to be a recurring pattern")
        assert _is_protected("may indicate deeper issue")
        assert _is_protected("but retries are succeeding")
        assert _is_protected("however baseline seems fine")
        assert not _is_protected("token overhead detected")


class TestCompressionRatio:
    def test_repeated_items_achieve_compression(self):
        compressor = EvidenceCompressor()
        evidence = _make_similar_items("retry overhead in batch module", _LONG_CHAIN_SIZE)
        result = compressor.compress(evidence)
        assert result.was_compressed
        assert result.compression_ratio > 0.0
        assert result.compressed_count < result.original_count

    def test_compression_ratio_non_negative(self):
        compressor = EvidenceCompressor()
        evidence = _make_distinct_items(_LONG_CHAIN_SIZE)
        result = compressor.compress(evidence)
        assert result.compression_ratio >= 0.0

    def test_original_count_correct(self):
        compressor = EvidenceCompressor()
        n = _LONG_CHAIN_SIZE
        result = compressor.compress(_make_similar_items("overhead", n))
        assert result.original_count == n


class TestFrequencyNotes:
    def test_large_group_has_frequency_note(self):
        compressor = EvidenceCompressor()
        # 5 very similar items → group with frequency note
        evidence = _make_similar_items("memory pressure in container module layer", 5)
        # Make chain long enough to trigger compression
        evidence += _make_distinct_items(_LONG_CHAIN_SIZE - 5)
        result = compressor.compress(evidence)
        # At least one group note should appear
        freq_notes = [e for e in result.compressed if e.startswith("[+")]
        assert len(freq_notes) >= 1

    def test_small_group_has_no_frequency_note(self):
        compressor = EvidenceCompressor()
        # 2 similar items → below _FREQUENCY_THRESHOLD (3) → no note
        evidence = _make_similar_items("memory pressure", 2)
        evidence += _make_distinct_items(_LONG_CHAIN_SIZE - 2)
        result = compressor.compress(evidence)
        groups = result.groups
        small_groups = [g for g in groups if g.frequency == 2]
        for g in small_groups:
            assert g.frequency_note == ""


class TestCompressInvestigation:
    def test_investigation_items_compressed(self):
        compressor = EvidenceCompressor()
        items = [
            {
                "title": "Token overhead",
                "evidence": _make_similar_items("retry overhead module batch", _LONG_CHAIN_SIZE),
            },
            {
                "title": "Memory leak",
                "evidence": ["small chain"],
            },
        ]
        result = compressor.compress_investigation(items)
        assert len(result) == 2
        compressed_item = result[0]
        assert "evidence_compression_note" in compressed_item
        uncompressed_item = result[1]
        assert "evidence_compression_note" not in uncompressed_item

    def test_non_dict_items_pass_through(self):
        compressor = EvidenceCompressor()
        result = compressor.compress_investigation(["not a dict", 42])
        assert result == ["not a dict", 42]

    def test_source_items_not_modified(self):
        compressor = EvidenceCompressor()
        original_evidence = _make_similar_items("token module overhead", _LONG_CHAIN_SIZE)
        item = {"title": "Cost spike", "evidence": list(original_evidence)}
        compressor.compress_investigation([item])
        assert item["evidence"] == original_evidence


class TestToDict:
    def test_to_dict_structure(self):
        compressor = EvidenceCompressor()
        evidence = _make_similar_items("latency in pipeline module", _LONG_CHAIN_SIZE)
        result = compressor.compress(evidence)
        d = result.to_dict()
        assert "compressed" in d
        assert "protected" in d
        assert "groups" in d
        assert "original_count" in d
        assert "compressed_count" in d
        assert "compression_ratio" in d
        assert "was_compressed" in d

    def test_group_to_dict_structure(self):
        compressor = EvidenceCompressor()
        evidence = _make_similar_items("token module overhead", _LONG_CHAIN_SIZE)
        result = compressor.compress(evidence)
        if result.groups:
            g = result.groups[0].to_dict()
            assert "group_id" in g
            assert "dominant" in g
            assert "frequency" in g
            assert "suppressed" in g


class TestIsProtected:
    def test_critical_word_triggers_protection(self):
        assert _is_protected("This is a critical failure")

    def test_uncertainty_word_triggers_protection(self):
        assert _is_protected("This appears to be a pattern")
        assert _is_protected("The system may be overloaded")

    def test_conflict_word_triggers_protection(self):
        assert _is_protected("Rate limit hit, however some succeed")
        assert _is_protected("Cost is high but throughput is fine")

    def test_normal_evidence_not_protected(self):
        assert not _is_protected("Token overhead detected in batch processing")
        assert not _is_protected("Latency spike occurred at 14:00 UTC")
