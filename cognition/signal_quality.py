"""
Signal Quality Assessment — false positive reduction and operator fatigue control.

Purpose:
Identify weak, stale, or low-value operational signals so operators can
choose to suppress or downgrade them without losing traceability.

The goal is NOT to delete signals. It is to:
- mark signals as weak/stale/saturated
- explain why a signal was flagged
- offer a downgraded confidence estimate
- support informed suppression by the caller

Five detection dimensions:
1. Weak evidence — too few or too short evidence strings
2. Repeated low-value — high recurrence with consistently low confidence
3. Confidence decay — long-running recurrent signals accrue staleness penalty
4. Low-diversity evidence — evidence items are near-identical to each other
5. Heuristic saturation — one category dominates a batch (batch-level only)

Design rules:
- Deterministic. Same inputs → same outputs.
- No DB access. All inputs are pre-fetched scalars/lists/dicts.
- Advisory only. Suppression is a recommendation, never automatic.
- Full traceability. Every flag includes an explanation string.
- Never lose the original signal. Source recommendation is not modified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Thresholds
# -----------------------------------------------------------------------

# Evidence weakness
_WEAK_EVIDENCE_MIN_COUNT = 2          # fewer than 2 evidence items = sparse
_WEAK_EVIDENCE_MIN_WORDS = 4          # evidence item with < 4 words = short/generic

# Staleness / confidence decay
_STALE_RECURRENCE_WARN = 5            # 5+ occurrences = stale_signal = True
_STALE_RECURRENCE_CRITICAL = 15       # 15+ occurrences = maximum decay applied
_CONFIDENCE_DECAY_MAX = 0.40          # max decay fraction (40% reduction)

# Evidence diversity (pairwise Jaccard)
_LOW_DIVERSITY_OVERLAP_THRESHOLD = 0.65   # avg pairwise overlap > 0.65 = low diversity
_LOW_DIVERSITY_SAMPLE_MAX = 30            # max items to include in pairwise comparison

# Heuristic saturation (batch-level)
_SATURATION_CATEGORY_FRACTION = 0.60     # category occupying ≥60% of batch = saturated

# Quality score → suppression
_SUPPRESSION_THRESHOLD = 0.25            # quality_score < 0.25 → marked suppressed

# Stopwords for evidence diversity comparison (same as deduplication module)
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "for",
    "to", "of", "in", "on", "at", "by", "with", "this", "that", "has",
    "have", "been", "not", "it", "its", "be", "as", "from", "may",
})


# -----------------------------------------------------------------------
# Output types
# -----------------------------------------------------------------------

@dataclass
class EvidenceDiversityScore:
    """
    Measures how diverse an evidence chain is.

    High diversity (score ≈ 1.0) means evidence items are all saying different things.
    Low diversity (score ≈ 0.0) means most items are near-identical — repetitive evidence.
    """
    score: float                  # 0.0 (all same) → 1.0 (all distinct)
    item_count: int
    avg_pairwise_overlap: float   # Jaccard overlap averaged across pairs
    is_low_diversity: bool
    penalty_applied: float        # how much this reduces quality_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "item_count": self.item_count,
            "avg_pairwise_overlap": round(self.avg_pairwise_overlap, 3),
            "is_low_diversity": self.is_low_diversity,
            "penalty_applied": round(self.penalty_applied, 3),
        }


@dataclass
class SignalQualityFlags:
    """Flags set by individual detection dimensions."""
    weak_evidence: bool = False
    stale_signal: bool = False
    low_diversity_evidence: bool = False
    heuristic_saturated: bool = False
    repeated_low_value: bool = False

    @property
    def any_flag(self) -> bool:
        return (
            self.weak_evidence
            or self.stale_signal
            or self.low_diversity_evidence
            or self.heuristic_saturated
            or self.repeated_low_value
        )

    @property
    def flag_count(self) -> int:
        return sum([
            self.weak_evidence,
            self.stale_signal,
            self.low_diversity_evidence,
            self.heuristic_saturated,
            self.repeated_low_value,
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "weak_evidence": self.weak_evidence,
            "stale_signal": self.stale_signal,
            "low_diversity_evidence": self.low_diversity_evidence,
            "heuristic_saturated": self.heuristic_saturated,
            "repeated_low_value": self.repeated_low_value,
            "any_flag": self.any_flag,
            "flag_count": self.flag_count,
        }


@dataclass
class SignalQualityAssessment:
    """
    Quality assessment for a single recommendation/signal.

    advisory: Source recommendation is never modified.
    This assessment is a view that callers may use to:
    - filter display lists
    - downgrade confidence in reports
    - explain to operators why a signal may be low-value

    Suppressed means: this signal SHOULD be hidden in normal operator views.
    It is still available in full/debug views.
    Suppression is always explained via explanation[] and suppression_reason.
    """
    original_confidence: float
    adjusted_confidence: float        # confidence after staleness decay
    confidence_decay: float           # fraction of confidence removed (0.0–0.40)
    evidence_diversity: EvidenceDiversityScore
    flags: SignalQualityFlags
    quality_score: float              # 0.0–1.0 composite
    suppressed: bool                  # True = recommend hiding in normal views
    suppression_reason: str           # single sentence if suppressed, empty otherwise
    explanation: list[str]            # human-readable per-dimension findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_confidence": round(self.original_confidence, 3),
            "adjusted_confidence": round(self.adjusted_confidence, 3),
            "confidence_decay": round(self.confidence_decay, 3),
            "evidence_diversity": self.evidence_diversity.to_dict(),
            "flags": self.flags.to_dict(),
            "quality_score": round(self.quality_score, 3),
            "suppressed": self.suppressed,
            "suppression_reason": self.suppression_reason,
            "explanation": self.explanation,
        }


@dataclass
class BatchQualityReport:
    """
    Quality summary for a batch of signals processed together.

    Adds batch-level analysis (saturation detection) that cannot be performed
    per-signal in isolation.
    """
    assessments: list[tuple[dict[str, Any], SignalQualityAssessment]]
    total_input: int
    suppressed_count: int
    flagged_count: int
    dominant_category: str            # category with highest share, or ""
    saturation_detected: bool
    operator_fatigue_score: float     # 0.0–1.0; high = operator is seeing many stale/weak signals
    observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input": self.total_input,
            "suppressed_count": self.suppressed_count,
            "flagged_count": self.flagged_count,
            "dominant_category": self.dominant_category,
            "saturation_detected": self.saturation_detected,
            "operator_fatigue_score": round(self.operator_fatigue_score, 3),
            "observations": self.observations,
            "assessments": [
                {
                    "title": r.get("title", ""),
                    "quality": a.to_dict(),
                }
                for r, a in self.assessments
            ],
        }


# -----------------------------------------------------------------------
# Engine
# -----------------------------------------------------------------------

class SignalQualityEngine:
    """
    Assesses the quality of operational signals and flags low-value items.

    All inputs are pre-fetched. No DB access. Stateless and deterministic.

    Usage (per-signal):
        engine = SignalQualityEngine()
        assessment = engine.assess(rec, recurrence_count=3)

    Usage (batch — preferred, enables saturation detection):
        report = engine.assess_batch(recs, recurrence_by_title=recurrence_map)
    """

    def assess(
        self,
        recommendation: dict[str, Any],
        *,
        recurrence_count: int = 0,
        saturated_categories: frozenset[str] | None = None,
    ) -> SignalQualityAssessment:
        """
        Assess the quality of a single recommendation.

        Parameters:
        - recommendation: dict with title, category, confidence, evidence fields
        - recurrence_count: how many times this recommendation (by title prefix) has
          appeared across historical snapshots. 0 = never seen before.
        - saturated_categories: set of categories already flagged as saturated at
          the batch level. Pass None to skip saturation checking.
        """
        confidence = float(recommendation.get("confidence", 0.0))
        evidence = list(recommendation.get("evidence", []))
        category = str(recommendation.get("category", ""))
        title = str(recommendation.get("title", ""))

        flags = SignalQualityFlags()
        explanation: list[str] = []

        # --- Dimension 1: Weak evidence ---
        weak_ev, ev_explanation = _check_weak_evidence(evidence)
        flags.weak_evidence = weak_ev
        explanation.extend(ev_explanation)

        # --- Dimension 2: Repeated low-value ---
        repeated_low, rlv_explanation = _check_repeated_low_value(
            recurrence_count, confidence
        )
        flags.repeated_low_value = repeated_low
        explanation.extend(rlv_explanation)

        # --- Dimension 3: Staleness / confidence decay ---
        decay_fraction, stale, stale_explanation = _compute_confidence_decay(
            recurrence_count
        )
        flags.stale_signal = stale
        explanation.extend(stale_explanation)

        # --- Dimension 4: Evidence diversity ---
        diversity = _compute_evidence_diversity(evidence)
        flags.low_diversity_evidence = diversity.is_low_diversity
        if diversity.is_low_diversity:
            explanation.append(
                f"Evidence diversity is low ({diversity.score:.2f}) — "
                f"{diversity.item_count} items with average pairwise overlap "
                f"{diversity.avg_pairwise_overlap:.2f}. "
                "Evidence may be repetitive rather than substantive."
            )

        # --- Dimension 5: Heuristic saturation (batch-provided) ---
        saturated = (
            saturated_categories is not None
            and category in saturated_categories
        )
        flags.heuristic_saturated = saturated
        if saturated:
            explanation.append(
                f"Category '{category}' is saturated in the current signal batch — "
                "many other signals share this category, reducing the relative priority "
                "of this signal."
            )

        # --- Composite quality score ---
        quality_score = _compute_quality_score(flags, diversity, decay_fraction)
        adjusted_confidence = max(0.0, confidence * (1.0 - decay_fraction))

        suppressed = quality_score < _SUPPRESSION_THRESHOLD
        suppression_reason = ""
        if suppressed:
            reasons = []
            if flags.weak_evidence:
                reasons.append("weak evidence")
            if flags.stale_signal:
                reasons.append("stale recurring signal")
            if flags.low_diversity_evidence:
                reasons.append("low-diversity evidence")
            if flags.heuristic_saturated:
                reasons.append("saturated category")
            if flags.repeated_low_value:
                reasons.append("repeated low-value signal")
            suppression_reason = (
                f"Signal quality score ({quality_score:.2f}) below suppression threshold "
                f"({_SUPPRESSION_THRESHOLD}). Reasons: {', '.join(reasons) or 'composite score too low'}."
            )

        logger.debug(
            "Signal quality assessed",
            extra={
                "title": title[:60],
                "quality_score": round(quality_score, 3),
                "suppressed": suppressed,
                "flags": flags.flag_count,
            },
        )

        return SignalQualityAssessment(
            original_confidence=confidence,
            adjusted_confidence=adjusted_confidence,
            confidence_decay=decay_fraction,
            evidence_diversity=diversity,
            flags=flags,
            quality_score=quality_score,
            suppressed=suppressed,
            suppression_reason=suppression_reason,
            explanation=explanation,
        )

    def assess_batch(
        self,
        recommendations: list[dict[str, Any]],
        *,
        recurrence_by_title: dict[str, int] | None = None,
    ) -> BatchQualityReport:
        """
        Assess quality for a batch of recommendations.

        Enables batch-level analysis (category saturation) that is not possible
        per-signal in isolation.

        Parameters:
        - recommendations: list of recommendation dicts
        - recurrence_by_title: map of title_prefix (first 60 chars) →
          recurrence count. None = assume all are first-time signals (count=0).
        """
        if not recommendations:
            return BatchQualityReport(
                assessments=[],
                total_input=0,
                suppressed_count=0,
                flagged_count=0,
                dominant_category="",
                saturation_detected=False,
                operator_fatigue_score=0.0,
                observations=["No signals provided for quality assessment."],
            )

        # Determine saturated categories
        saturated = _find_saturated_categories(recommendations)

        # Assess each signal
        assessments: list[tuple[dict[str, Any], SignalQualityAssessment]] = []
        for rec in recommendations:
            title_key = str(rec.get("title", ""))[:60]
            recurrence = (recurrence_by_title or {}).get(title_key, 0)
            assessment = self.assess(
                rec,
                recurrence_count=recurrence,
                saturated_categories=saturated,
            )
            assessments.append((rec, assessment))

        suppressed_count = sum(1 for _, a in assessments if a.suppressed)
        flagged_count = sum(1 for _, a in assessments if a.flags.any_flag)

        # Operator fatigue score: fraction of signals with any quality issue
        fatigue = flagged_count / len(assessments) if assessments else 0.0

        # Dominant category
        dominant_cat, saturation_detected = _describe_saturation(
            recommendations, saturated
        )

        observations = _build_batch_observations(
            len(recommendations), suppressed_count, flagged_count,
            saturation_detected, dominant_cat, fatigue
        )

        logger.info(
            "Batch quality assessment complete",
            extra={
                "total": len(recommendations),
                "suppressed": suppressed_count,
                "flagged": flagged_count,
                "fatigue": round(fatigue, 3),
            },
        )

        return BatchQualityReport(
            assessments=assessments,
            total_input=len(recommendations),
            suppressed_count=suppressed_count,
            flagged_count=flagged_count,
            dominant_category=dominant_cat,
            saturation_detected=saturation_detected,
            operator_fatigue_score=fatigue,
            observations=observations,
        )

    def filter_suppressed(
        self,
        assessments: list[tuple[dict[str, Any], SignalQualityAssessment]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Split assessed recommendations into (kept, suppressed) lists.

        Returns:
        - kept: recommendations with quality_score >= suppression threshold
        - suppressed: recommendations below threshold (marked, not deleted)

        Source recommendations are not modified. Returns copies.
        """
        kept = []
        suppressed = []
        for rec, assessment in assessments:
            annotated = dict(rec)
            annotated["_quality_score"] = assessment.quality_score
            annotated["_suppressed"] = assessment.suppressed
            annotated["_suppression_reason"] = assessment.suppression_reason
            if assessment.suppressed:
                suppressed.append(annotated)
            else:
                kept.append(annotated)
        return kept, suppressed


# -----------------------------------------------------------------------
# Dimension implementations
# -----------------------------------------------------------------------

def _check_weak_evidence(evidence: list[str]) -> tuple[bool, list[str]]:
    """Returns (is_weak, explanation_lines)."""
    explanation = []
    is_weak = False

    if len(evidence) < _WEAK_EVIDENCE_MIN_COUNT:
        is_weak = True
        explanation.append(
            f"Evidence is sparse: only {len(evidence)} item(s). "
            f"Minimum for a well-supported signal: {_WEAK_EVIDENCE_MIN_COUNT}."
        )
        return is_weak, explanation

    short_count = sum(
        1 for e in evidence
        if len(e.split()) < _WEAK_EVIDENCE_MIN_WORDS
    )
    if short_count > 0 and short_count / len(evidence) >= 0.5:
        is_weak = True
        explanation.append(
            f"{short_count} of {len(evidence)} evidence item(s) are very short "
            f"(< {_WEAK_EVIDENCE_MIN_WORDS} words). "
            "Short evidence items often lack specific operational context."
        )

    return is_weak, explanation


def _check_repeated_low_value(
    recurrence_count: int, confidence: float
) -> tuple[bool, list[str]]:
    """Returns (is_repeated_low_value, explanation_lines)."""
    explanation = []

    if recurrence_count >= _STALE_RECURRENCE_WARN and confidence < 0.45:
        explanation.append(
            f"Signal has recurred {recurrence_count} time(s) with persistently low "
            f"confidence ({confidence:.2f}). Recurring low-confidence signals rarely "
            "resolve and contribute to operator fatigue."
        )
        return True, explanation

    return False, explanation


def _compute_confidence_decay(recurrence_count: int) -> tuple[float, bool, list[str]]:
    """
    Returns (decay_fraction, is_stale, explanation_lines).

    decay_fraction: 0.0 → no decay; _CONFIDENCE_DECAY_MAX → full decay
    is_stale: True if recurrence_count >= _STALE_RECURRENCE_WARN
    """
    explanation = []
    is_stale = recurrence_count >= _STALE_RECURRENCE_WARN

    if recurrence_count <= 0:
        return 0.0, False, explanation

    decay = min(
        recurrence_count / _STALE_RECURRENCE_CRITICAL,
        1.0,
    ) * _CONFIDENCE_DECAY_MAX

    if is_stale:
        explanation.append(
            f"Signal has been observed {recurrence_count} time(s) "
            f"({'critically stale' if recurrence_count >= _STALE_RECURRENCE_CRITICAL else 'stale'}). "
            f"Confidence decayed by {decay:.0%} to reduce background-noise amplification."
        )
    elif recurrence_count > 1:
        explanation.append(
            f"Signal observed {recurrence_count} time(s) — minor confidence adjustment applied."
        )

    return round(decay, 4), is_stale, explanation


def _compute_evidence_diversity(evidence: list[str]) -> EvidenceDiversityScore:
    """
    Compute pairwise Jaccard similarity across evidence items.

    Low average pairwise overlap = high diversity (good).
    High average pairwise overlap = low diversity (repetitive evidence).
    """
    if len(evidence) <= 1:
        return EvidenceDiversityScore(
            score=1.0,
            item_count=len(evidence),
            avg_pairwise_overlap=0.0,
            is_low_diversity=False,
            penalty_applied=0.0,
        )

    # Sample to avoid O(n²) at large scale
    sample = evidence[:_LOW_DIVERSITY_SAMPLE_MAX]
    word_sets = [_content_words(e) for e in sample]

    overlaps = []
    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            overlaps.append(_word_overlap(word_sets[i], word_sets[j]))

    if not overlaps:
        return EvidenceDiversityScore(
            score=1.0,
            item_count=len(evidence),
            avg_pairwise_overlap=0.0,
            is_low_diversity=False,
            penalty_applied=0.0,
        )

    avg_overlap = sum(overlaps) / len(overlaps)
    diversity_score = round(1.0 - avg_overlap, 4)
    is_low = avg_overlap > _LOW_DIVERSITY_OVERLAP_THRESHOLD
    penalty = 0.20 if is_low else 0.0

    return EvidenceDiversityScore(
        score=diversity_score,
        item_count=len(evidence),
        avg_pairwise_overlap=round(avg_overlap, 4),
        is_low_diversity=is_low,
        penalty_applied=penalty,
    )


def _find_saturated_categories(
    recommendations: list[dict[str, Any]]
) -> frozenset[str]:
    """Return the set of categories that dominate (≥ SATURATION threshold)."""
    if not recommendations:
        return frozenset()

    counts: dict[str, int] = {}
    for rec in recommendations:
        cat = str(rec.get("category", ""))
        counts[cat] = counts.get(cat, 0) + 1

    n = len(recommendations)
    return frozenset(
        cat for cat, count in counts.items()
        if count / n >= _SATURATION_CATEGORY_FRACTION
    )


def _describe_saturation(
    recommendations: list[dict[str, Any]],
    saturated: frozenset[str],
) -> tuple[str, bool]:
    """Returns (dominant_category, saturation_detected)."""
    if not recommendations:
        return "", False

    counts: dict[str, int] = {}
    for rec in recommendations:
        cat = str(rec.get("category", ""))
        counts[cat] = counts.get(cat, 0) + 1

    dominant = max(counts, key=lambda c: counts[c]) if counts else ""
    return dominant, bool(saturated)


def _compute_quality_score(
    flags: SignalQualityFlags,
    diversity: EvidenceDiversityScore,
    decay_fraction: float,
) -> float:
    """
    Compute composite quality score 0.0–1.0.

    Deductions (cumulative, capped at 0.0):
    - Weak evidence:          -0.30
    - Repeated low-value:     -0.25
    - Stale signal:           scaled by decay_fraction (max -0.20)
    - Low diversity evidence: -0.20 (from penalty_applied)
    - Saturated category:     -0.15
    """
    score = 1.0

    if flags.weak_evidence:
        score -= 0.30
    if flags.repeated_low_value:
        score -= 0.25
    if flags.stale_signal:
        score -= decay_fraction * 0.50   # scale stale penalty by how stale
    score -= diversity.penalty_applied
    if flags.heuristic_saturated:
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 4)


def _build_batch_observations(
    total: int,
    suppressed: int,
    flagged: int,
    saturation_detected: bool,
    dominant_cat: str,
    fatigue: float,
) -> list[str]:
    obs = []

    if suppressed > 0:
        obs.append(
            f"{suppressed} of {total} signal(s) ({suppressed/total:.0%}) "
            "fall below the quality threshold and are recommended for suppression."
        )
    if flagged > suppressed:
        obs.append(
            f"{flagged} of {total} signal(s) have at least one quality flag "
            "(weak evidence, staleness, or saturation)."
        )

    if saturation_detected and dominant_cat:
        obs.append(
            f"Category '{dominant_cat}' appears to dominate this signal batch — "
            "heuristic saturation detected. Signals in this category may be "
            "inflating operational noise."
        )

    if fatigue >= 0.70:
        obs.append(
            f"Operator fatigue score is high ({fatigue:.0%}). "
            "Most signals have quality flags — recommend reviewing signal sources "
            "or raising confidence thresholds."
        )
    elif fatigue >= 0.40:
        obs.append(
            f"Moderate operator fatigue detected ({fatigue:.0%} of signals flagged). "
            "Consider reviewing recurring low-confidence signals."
        )

    if not obs:
        obs.append(
            f"All {total} signal(s) passed quality checks — no fatigue indicators detected."
        )

    return obs


# -----------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------

def _content_words(text: str) -> frozenset[str]:
    """Tokenize into lowercase content words, removing stopwords."""
    words = text.lower().replace("-", " ").replace("/", " ").split()
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _word_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two word sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
