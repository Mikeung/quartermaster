"""
Signal Deduplication Engine — reduce repeated operational noise.

Purpose:
Identify and group duplicate or near-duplicate signals across recommendations,
evidence chains, and cluster findings so operators see the deduplicated signal
rather than fragmented repeats.

Design rules:
- Deterministic only. Same input → same output.
- Preserve full traceability (all source signals cited in groups).
- Never silently discard evidence — collapsed signals still track sources.
- Deduplication is advisory. Source data is never modified.

Deduplication is NOT consolidation.
Consolidation (cognition/consolidation.py) groups by category + evidence keyword.
Deduplication here detects signals that say the same thing in different words.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Prefix match length — recommendations with titles sharing the first N chars
# are candidates for deduplication
_TITLE_MATCH_PREFIX = 45
_EVIDENCE_MATCH_MIN_SHARED = 2   # at least 2 shared evidence keywords = near-duplicate

# Low-value filler words to strip before comparison
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "for",
    "to", "of", "in", "on", "at", "by", "with", "this", "that", "has",
    "have", "been", "not", "it", "its", "be", "as", "from", "may",
})

# Minimum word overlap fraction for near-title matching
_TITLE_WORD_OVERLAP_MIN = 0.60


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class SignalGroup:
    """A group of signals that appear to describe the same underlying concern."""

    group_id: str
    representative_title: str
    representative_category: str
    signal_count: int
    source_titles: list[str] = field(default_factory=list)
    shared_evidence_keywords: list[str] = field(default_factory=list)
    duplicate_reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "representative_title": self.representative_title,
            "representative_category": self.representative_category,
            "signal_count": self.signal_count,
            "source_titles": self.source_titles,
            "shared_evidence_keywords": self.shared_evidence_keywords,
            "duplicate_reasoning": self.duplicate_reasoning,
        }


@dataclass
class DeduplicatedConcern:
    """
    A recommendation or concern after deduplication.

    If deduplicated=True, this concern represents multiple source signals
    collapsed into one representative. Source signals are preserved via
    source_titles and source_count.
    """

    title: str
    category: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    deduplicated: bool = False
    source_count: int = 1
    source_titles: list[str] = field(default_factory=list)
    suppressed_count: int = 0
    dedup_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "deduplicated": self.deduplicated,
            "source_count": self.source_count,
            "source_titles": self.source_titles,
            "suppressed_count": self.suppressed_count,
            "dedup_reason": self.dedup_reason,
        }


@dataclass
class DeduplicationSummary:
    """
    Result of running the deduplication engine.

    Contains the deduplicated concerns list and statistics about what was collapsed.
    """

    concerns: list[DeduplicatedConcern]
    groups: list[SignalGroup]
    input_count: int
    output_count: int
    suppressed_count: int
    dedup_ratio: float
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "concerns": [c.to_dict() for c in self.concerns],
            "groups": [g.to_dict() for g in self.groups],
            "input_count": self.input_count,
            "output_count": self.output_count,
            "suppressed_count": self.suppressed_count,
            "dedup_ratio": round(self.dedup_ratio, 3),
            "observations": self.observations,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SignalDeduplicationEngine:
    """
    Detects and groups near-duplicate operational signals.

    Deduplication is based on two signals:
    1. Title word-overlap: recommendations with ≥60% shared content words
       after stopword removal are grouped together.
    2. Evidence keyword overlap: recommendations sharing ≥2 significant
       evidence keywords are candidates for grouping.

    The highest-confidence representative from each group is kept as the
    deduplicated concern. Source titles are preserved for traceability.
    """

    def deduplicate(
        self, recommendations: list[dict[str, Any]]
    ) -> DeduplicationSummary:
        """
        Deduplicate a list of recommendation dicts.

        Each recommendation should have at minimum:
          - title: str
          - category: str
          - confidence: float
          - evidence: list[str]

        Returns a DeduplicationSummary with collapsed concerns.
        """
        if not recommendations:
            return DeduplicationSummary(
                concerns=[],
                groups=[],
                input_count=0,
                output_count=0,
                suppressed_count=0,
                dedup_ratio=0.0,
                observations=["No signals provided for deduplication."],
            )

        # Build groups
        groups = self._build_groups(recommendations)

        # Build deduplicated concerns from groups
        concerns: list[DeduplicatedConcern] = []
        total_suppressed = 0

        for group in groups:
            # Pick the highest-confidence representative
            members = [r for r in recommendations if r.get("title") in group.source_titles]
            if not members:
                continue
            rep = max(members, key=lambda r: float(r.get("confidence", 0)))
            suppressed = len(members) - 1
            total_suppressed += suppressed

            concern = DeduplicatedConcern(
                title=rep.get("title", ""),
                category=rep.get("category", ""),
                confidence=float(rep.get("confidence", 0)),
                evidence=list(rep.get("evidence", [])),
                deduplicated=suppressed > 0,
                source_count=len(members),
                source_titles=list(group.source_titles),
                suppressed_count=suppressed,
                dedup_reason=group.duplicate_reasoning if suppressed > 0 else "",
            )
            concerns.append(concern)

        # Sort: deduplicated (multi-source) first, then by confidence
        concerns.sort(key=lambda c: (-c.source_count, -c.confidence))

        input_count = len(recommendations)
        output_count = len(concerns)
        dedup_ratio = 1.0 - (output_count / input_count) if input_count > 0 else 0.0

        observations = _build_observations(input_count, output_count, total_suppressed, groups)

        logger.info(
            "Deduplication complete",
            extra={
                "input": input_count,
                "output": output_count,
                "suppressed": total_suppressed,
            },
        )

        return DeduplicationSummary(
            concerns=concerns,
            groups=groups,
            input_count=input_count,
            output_count=output_count,
            suppressed_count=total_suppressed,
            dedup_ratio=dedup_ratio,
            observations=observations,
        )

    def filter_weak_signals(
        self,
        concerns: list[DeduplicatedConcern],
        *,
        recurrence_by_title: dict[str, int] | None = None,
        return_suppressed: bool = False,
    ) -> tuple[list[DeduplicatedConcern], list[DeduplicatedConcern]]:
        """
        Apply signal quality filtering to a deduplicated concern list.

        Uses cognition.signal_quality.SignalQualityEngine to assess each concern.
        Concerns marked suppressed are separated but never deleted.

        Parameters:
        - concerns: deduplicated concerns from deduplicate()
        - recurrence_by_title: title_prefix (60 chars) → recurrence count, or None
        - return_suppressed: if True, also return the suppressed list (default False)

        Returns: (kept, suppressed) — suppressed list is empty if return_suppressed=False.

        Source concerns are not modified. Returns new concern objects annotated with
        quality metadata in their dedup_reason field if suppressed.
        """
        # Lazy import to avoid circular dependency at module level
        from cognition.signal_quality import SignalQualityEngine
        engine = SignalQualityEngine()

        recs = [c.to_dict() for c in concerns]
        batch = engine.assess_batch(recs, recurrence_by_title=recurrence_by_title)

        kept: list[DeduplicatedConcern] = []
        suppressed_list: list[DeduplicatedConcern] = []

        for concern, (_, assessment) in zip(concerns, batch.assessments, strict=False):
            if assessment.suppressed:
                annotated = DeduplicatedConcern(
                    title=concern.title,
                    category=concern.category,
                    confidence=assessment.adjusted_confidence,
                    evidence=concern.evidence,
                    deduplicated=concern.deduplicated,
                    source_count=concern.source_count,
                    source_titles=concern.source_titles,
                    suppressed_count=concern.suppressed_count,
                    dedup_reason=(
                        f"[QUALITY-SUPPRESSED] {assessment.suppression_reason} "
                        f"| Original: {concern.dedup_reason}"
                    ).strip(" |"),
                )
                suppressed_list.append(annotated)
            else:
                kept.append(concern)

        logger.debug(
            "Weak signal filter applied",
            extra={
                "input": len(concerns),
                "kept": len(kept),
                "suppressed": len(suppressed_list),
            },
        )

        return kept, (suppressed_list if return_suppressed else [])

    def deduplicate_evidence(self, evidence_list: list[str]) -> list[str]:
        """
        Remove near-duplicate evidence strings from a list.

        Strings with ≥70% word overlap after stopword removal are treated
        as duplicates; only the first occurrence is kept.
        """
        if len(evidence_list) <= 1:
            return list(evidence_list)

        kept: list[str] = []
        for candidate in evidence_list:
            cand_words = _content_words(candidate)
            duplicate = False
            for existing in kept:
                existing_words = _content_words(existing)
                overlap = _word_overlap(cand_words, existing_words)
                if overlap >= 0.70:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
        return kept

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_groups(
        self, recommendations: list[dict[str, Any]]
    ) -> list[SignalGroup]:
        """
        Assign each recommendation to a group using greedy title-word matching.

        Each unassigned recommendation starts a new group. Subsequent
        recommendations are merged into an existing group if they share
        sufficient title-word overlap.
        """
        assigned: dict[int, int] = {}   # rec_index → group_index
        group_reps: list[dict[str, Any]] = []
        group_members: list[list[int]] = []

        for i, rec in enumerate(recommendations):
            matched_group = None
            for gi, rep in enumerate(group_reps):
                if _recs_are_near_duplicate(rec, rep):
                    matched_group = gi
                    break
            if matched_group is not None:
                assigned[i] = matched_group
                group_members[matched_group].append(i)
            else:
                assigned[i] = len(group_reps)
                group_reps.append(rec)
                group_members.append([i])

        groups: list[SignalGroup] = []
        for gi, member_indices in enumerate(group_members):
            members = [recommendations[i] for i in member_indices]
            rep = members[0]
            shared_kw = _shared_evidence_keywords(members)
            reasoning = _build_group_reasoning(members, shared_kw)
            groups.append(SignalGroup(
                group_id=f"grp-{gi+1:03d}",
                representative_title=str(rep.get("title", "")),
                representative_category=str(rep.get("category", "")),
                signal_count=len(members),
                source_titles=[str(m.get("title", "")) for m in members],
                shared_evidence_keywords=shared_kw,
                duplicate_reasoning=reasoning,
            ))

        return groups


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_words(text: str) -> frozenset[str]:
    """Tokenize text into lowercase content words (stopwords removed)."""
    words = text.lower().replace("-", " ").replace("/", " ").split()
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _word_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Return Jaccard similarity of two word sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _recs_are_near_duplicate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True if two recommendations appear to describe the same concern."""
    title_a = str(a.get("title", ""))
    title_b = str(b.get("title", ""))
    words_a = _content_words(title_a)
    words_b = _content_words(title_b)
    overlap = _word_overlap(words_a, words_b)
    if overlap >= _TITLE_WORD_OVERLAP_MIN:
        return True

    # Secondary: shared evidence keywords
    ev_a = _evidence_keyword_set(a)
    ev_b = _evidence_keyword_set(b)
    shared_ev = ev_a & ev_b
    if len(shared_ev) >= _EVIDENCE_MATCH_MIN_SHARED and a.get("category") == b.get("category"):
        return True

    return False


_EVIDENCE_KEYWORDS = frozenset({
    "ocr", "retry", "token", "cost", "memory", "orchestration", "agent",
    "provider", "langchain", "autogen", "rag", "vector", "embedding",
    "docker", "service", "workflow", "stream", "latency", "rate", "limit",
    "error", "timeout", "batch", "concurrency", "queue",
})


def _evidence_keyword_set(rec: dict[str, Any]) -> frozenset[str]:
    """Extract evidence keywords from a recommendation's title + evidence."""
    text = str(rec.get("title", ""))
    for ev in rec.get("evidence", []):
        text += " " + str(ev)
    words = text.lower().split()
    return frozenset(w for w in words if w in _EVIDENCE_KEYWORDS)


def _shared_evidence_keywords(members: list[dict[str, Any]]) -> list[str]:
    """Find keywords present in ALL members of a group."""
    if not members:
        return []
    sets = [_evidence_keyword_set(m) for m in members]
    shared = sets[0]
    for s in sets[1:]:
        shared = shared & s
    return sorted(shared)


def _build_group_reasoning(
    members: list[dict[str, Any]], shared_kw: list[str]
) -> str:
    if len(members) <= 1:
        return ""
    if shared_kw:
        return (
            f"{len(members)} signals share keywords: {', '.join(shared_kw)}. "
            "High-confidence representative retained."
        )
    titles_preview = "; ".join(str(m.get("title", ""))[:40] for m in members[:3])
    return (
        f"{len(members)} near-duplicate titles detected: {titles_preview}. "
        "Representative selected by confidence."
    )


def _build_observations(
    input_count: int,
    output_count: int,
    suppressed: int,
    groups: list[SignalGroup],
) -> list[str]:
    obs: list[str] = []
    if suppressed == 0:
        obs.append(
            f"All {input_count} signals appear distinct — no deduplication applied."
        )
    else:
        ratio_pct = suppressed / input_count * 100 if input_count > 0 else 0
        obs.append(
            f"{suppressed} of {input_count} signals ({ratio_pct:.0f}%) appear to be "
            "near-duplicates and were collapsed into {output_count} deduplicated concerns."
            .replace("{output_count}", str(output_count))
        )
    multi_groups = [g for g in groups if g.signal_count > 1]
    if multi_groups:
        obs.append(
            f"{len(multi_groups)} signal group(s) contain multiple near-duplicate entries."
        )
    return obs
