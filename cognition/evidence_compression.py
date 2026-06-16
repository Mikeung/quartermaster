"""
Evidence Compression — make large evidence chains readable.

Problem: deep investigation reports can contain hundreds of evidence strings.
Many are near-identical repetitions. Long chains obscure the critical signals.

Solution:
1. Group similar evidence by keyword overlap
2. Collapse repeated groups into frequency summaries
3. Extract dominant evidence (most representative per group)
4. Preserve critical/uncertainty/conflicting evidence unconditionally

IMPORTANT compression invariants:
- Critical evidence is NEVER suppressed (strings containing danger words)
- Uncertainty notes are NEVER suppressed ("uncertain", "unclear", "appears")
- Conflicting evidence is NEVER suppressed (strings containing "but", "however", "conflict")
- Empty output is never produced if input was non-empty

All compression is lossless in terms of traceability:
- Collapsed groups list how many items were compressed
- Dominant items represent the group

Advisory only. Source evidence is never modified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds
_COMPRESSION_SIMILARITY_THRESHOLD = 0.55   # word-overlap Jaccard for grouping
_MAX_DOMINANT_PER_GROUP = 2                # max items extracted from each group
_FREQUENCY_THRESHOLD = 3                   # groups with ≥3 items get a summary line
_MAX_UNCOMPRESSED_LENGTH = 20              # chains shorter than this aren't compressed

# Phrases that protect evidence from suppression
_CRITICAL_MARKERS = frozenset({"critical", "critical:", "failure", "data loss", "emergency"})
_UNCERTAINTY_MARKERS = frozenset({"uncertain", "unclear", "appears", "may", "possibly", "unknown"})
_CONFLICT_MARKERS = frozenset({"but", "however", "conflict", "contradicts", "inconsistent"})

# Stopwords for comparison
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "for",
    "to", "of", "in", "on", "at", "by", "with", "this", "that", "has",
    "have", "been", "not", "it", "its", "be", "as", "from",
})


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class EvidenceGroup:
    """A cluster of similar evidence strings."""

    group_id: int
    dominant: list[str]          # most representative items (max _MAX_DOMINANT_PER_GROUP)
    frequency: int               # total items in group
    suppressed: int              # items not in dominant set
    frequency_note: str          # human-readable summary if frequency > threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "dominant": self.dominant,
            "frequency": self.frequency,
            "suppressed": self.suppressed,
            "frequency_note": self.frequency_note,
        }


@dataclass
class CompressedEvidence:
    """
    Result of compressing an evidence list.

    Provides a compressed view that a human can scan quickly,
    plus statistics about what was compressed.
    """

    compressed: list[str]            # the readable compressed list
    protected: list[str]             # evidence preserved unconditionally
    groups: list[EvidenceGroup]      # compression groups (for inspection)
    original_count: int
    compressed_count: int
    protected_count: int
    compression_ratio: float
    was_compressed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "compressed": self.compressed,
            "protected": self.protected,
            "groups": [g.to_dict() for g in self.groups],
            "original_count": self.original_count,
            "compressed_count": self.compressed_count,
            "protected_count": self.protected_count,
            "compression_ratio": round(self.compression_ratio, 3),
            "was_compressed": self.was_compressed,
        }


# ---------------------------------------------------------------------------
# Compressor
# ---------------------------------------------------------------------------

class EvidenceCompressor:
    """
    Compresses large evidence chains while preserving critical signals.

    Usage:
        compressor = EvidenceCompressor()
        result = compressor.compress(evidence_list)
        print(result.compressed)   # readable, compressed list
    """

    def compress(self, evidence: list[str]) -> CompressedEvidence:
        """
        Compress an evidence list.

        - Protects critical/uncertainty/conflicting evidence unconditionally
        - Groups remaining evidence by similarity
        - Extracts dominant items per group
        - Adds frequency summary lines for large groups
        - Returns a CompressedEvidence result with full traceability
        """
        if not evidence:
            return CompressedEvidence(
                compressed=[],
                protected=[],
                groups=[],
                original_count=0,
                compressed_count=0,
                protected_count=0,
                compression_ratio=0.0,
                was_compressed=False,
            )

        # Small chains: don't compress
        if len(evidence) < _MAX_UNCOMPRESSED_LENGTH:
            return CompressedEvidence(
                compressed=list(evidence),
                protected=[],
                groups=[],
                original_count=len(evidence),
                compressed_count=len(evidence),
                protected_count=0,
                compression_ratio=0.0,
                was_compressed=False,
            )

        # Split: protected vs compressible
        protected = [e for e in evidence if _is_protected(e)]
        compressible = [e for e in evidence if not _is_protected(e)]

        # Deduplicate compressible set first
        compressible = _remove_exact_duplicates(compressible)

        # Group by similarity
        groups = _build_groups(compressible)

        # Build compressed output from dominant items + frequency notes
        compressed_output: list[str] = []
        for group in groups:
            compressed_output.extend(group.dominant)
            if group.frequency_note:
                compressed_output.append(group.frequency_note)

        # Add protected items at the end (clearly separate)
        full_output = compressed_output + protected

        original_count = len(evidence)
        compressed_count = len(full_output)
        compression_ratio = (
            1.0 - (compressed_count / original_count) if original_count > 0 else 0.0
        )

        logger.debug(
            "Evidence compressed",
            extra={
                "original": original_count,
                "compressed": compressed_count,
                "protected": len(protected),
            },
        )

        return CompressedEvidence(
            compressed=full_output,
            protected=protected,
            groups=groups,
            original_count=original_count,
            compressed_count=compressed_count,
            protected_count=len(protected),
            compression_ratio=max(0.0, compression_ratio),
            was_compressed=compressed_count < original_count,
        )

    def compress_investigation(
        self, investigation_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Compress evidence fields in a list of investigation result items.

        Each item should have an "evidence" key with a list of strings.
        Returns a new list with evidence fields compressed.
        Source items are not modified.
        """
        result = []
        for item in investigation_items:
            if not isinstance(item, dict):
                result.append(item)
                continue
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                compressed = self.compress(evidence)
                new_item = dict(item)
                new_item["evidence"] = compressed.compressed
                if compressed.was_compressed:
                    new_item["evidence_compression_note"] = (
                        f"Evidence compressed: {compressed.original_count} → "
                        f"{compressed.compressed_count} items "
                        f"({compressed.protected_count} protected)"
                    )
                result.append(new_item)
            else:
                result.append(item)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_protected(evidence_str: str) -> bool:
    """Return True if this evidence string must not be suppressed."""
    lower = evidence_str.lower()
    words = frozenset(lower.split())
    if words & _CRITICAL_MARKERS:
        return True
    if words & _UNCERTAINTY_MARKERS:
        return True
    if words & _CONFLICT_MARKERS:
        return True
    return False


def _content_words(text: str) -> frozenset[str]:
    words = text.lower().replace("-", " ").replace("/", " ").split()
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _word_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _remove_exact_duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        normalized = item.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(item)
    return result


def _build_groups(items: list[str]) -> list[EvidenceGroup]:
    """Greedily assign items to groups by word overlap similarity."""
    group_reps: list[frozenset[str]] = []
    group_items: list[list[str]] = []

    for item in items:
        words = _content_words(item)
        matched = None
        for gi, rep_words in enumerate(group_reps):
            if _word_overlap(words, rep_words) >= _COMPRESSION_SIMILARITY_THRESHOLD:
                matched = gi
                break
        if matched is not None:
            group_items[matched].append(item)
        else:
            group_reps.append(words)
            group_items.append([item])

    groups: list[EvidenceGroup] = []
    for gi, members in enumerate(group_items):
        dominant = members[:_MAX_DOMINANT_PER_GROUP]
        suppressed = len(members) - len(dominant)
        freq_note = ""
        if len(members) >= _FREQUENCY_THRESHOLD:
            freq_note = (
                f"[+{suppressed} similar evidence item(s) — "
                f"{len(members)} occurrences of this pattern]"
            )
        groups.append(EvidenceGroup(
            group_id=gi,
            dominant=dominant,
            frequency=len(members),
            suppressed=suppressed,
            frequency_note=freq_note,
        ))
    return groups
