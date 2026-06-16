"""
Confidence normalization — consistent confidence semantics across cognition modules.

Problem:
Different modules compute confidence differently. Without a shared semantics layer,
operators cannot compare confidence values across recommendations, severity scores,
ecosystem themes, and drift analyses.

Solution:
A normalized confidence score with explicit interpretation and evidence weighting.

CRITICAL DISTINCTION:
  Confidence = strength of supporting evidence.
  Confidence ≠ probability of correctness.

A confidence of 0.8 means: "8 of 10 possible supporting signal types are present."
It does NOT mean: "80% probability this finding is true."

This distinction must be preserved in all report output.

Inputs that increase confidence:
- more supporting evidence items (evidence density)
- temporal data available (pattern is not point-in-time)
- recurrence confirmed (pattern has appeared before)
- multiple snapshot history available

IMPORTANT:
- Deterministic only.
- No model-based confidence.
- No Bayesian inference.
- Explicit, bounded, explainable formulas only.

Advisory only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Evidence density breakpoints — number of evidence items mapped to weight
_EVIDENCE_DENSITY_WEIGHTS: list[tuple[int, float]] = [
    (0, 0.00),
    (1, 0.30),
    (2, 0.50),
    (3, 0.65),
    (4, 0.75),
    (5, 0.85),
    (7, 0.90),
    (10, 1.00),
]

# Snapshot count breakpoints — more history → higher confidence
_SNAPSHOT_COUNT_WEIGHTS: list[tuple[int, float]] = [
    (0, 0.00),
    (1, 0.40),
    (2, 0.60),
    (3, 0.70),
    (5, 0.80),
    (10, 0.90),
    (20, 1.00),
]

# Interpretation labels
_INTERPRETATION_BANDS: list[tuple[float, str]] = [
    (0.80, "strong"),
    (0.60, "moderate"),
    (0.40, "low"),
    (0.20, "very low"),
    (0.00, "insufficient"),
]


def _interpolate(value: int, breakpoints: list[tuple[int, float]]) -> float:
    """Linear interpolation over (count, weight) breakpoints."""
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    for i in range(1, len(breakpoints)):
        lo_count, lo_w = breakpoints[i - 1]
        hi_count, hi_w = breakpoints[i]
        if value <= hi_count:
            ratio = (value - lo_count) / (hi_count - lo_count)
            return lo_w + ratio * (hi_w - lo_w)
    return breakpoints[-1][1]


@dataclass
class ConfidenceScore:
    """
    A normalized confidence score with full interpretability.

    value: float in [0.0, 1.0] — the normalized confidence score
    evidence_count: int — number of distinct evidence items that contributed
    snapshot_support: bool — whether multiple snapshots contributed
    temporal_support: bool — whether temporal analysis data was available
    recurrence_support: bool — whether recurrence was confirmed
    interpretation: str — human-readable band label
    basis: str — brief explanation of how the score was computed
    """
    value: float
    evidence_count: int
    snapshot_support: bool
    temporal_support: bool
    recurrence_support: bool
    interpretation: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 3),
            "evidence_count": self.evidence_count,
            "snapshot_support": self.snapshot_support,
            "temporal_support": self.temporal_support,
            "recurrence_support": self.recurrence_support,
            "interpretation": self.interpretation,
            "basis": self.basis,
            "advisory": (
                "Confidence reflects evidence density, not probability of correctness."
            ),
        }


class ConfidenceNormalizer:
    """
    Normalize confidence values across cognition modules.

    All methods are deterministic and produce bounded [0.0, 1.0] output.
    """

    def normalize(
        self,
        raw_confidence: float,
        evidence_count: int,
        *,
        snapshot_count: int = 1,
        temporal_support: bool = False,
        recurrence_support: bool = False,
    ) -> ConfidenceScore:
        """
        Normalize a raw confidence value using evidence density weighting.

        raw_confidence: the module's own confidence estimate (0.0-1.0)
        evidence_count: number of supporting evidence items
        snapshot_count: number of snapshots that contributed
        temporal_support: whether temporal analysis was available
        recurrence_support: whether recurrence was confirmed
        """
        density_w = _interpolate(evidence_count, _EVIDENCE_DENSITY_WEIGHTS)
        snapshot_w = _interpolate(snapshot_count, _SNAPSHOT_COUNT_WEIGHTS)

        # Weighted blend: raw 40%, evidence density 35%, snapshot depth 25%
        blended = (
            raw_confidence * 0.40
            + density_w * 0.35
            + snapshot_w * 0.25
        )

        # Bonuses for additional support signals
        if temporal_support:
            blended = min(blended + 0.05, 1.0)
        if recurrence_support:
            blended = min(blended + 0.05, 1.0)

        value = max(0.0, min(1.0, blended))
        interp = self.interpret(value)

        factors = [f"raw={raw_confidence:.2f}", f"evidence={evidence_count}"]
        if temporal_support:
            factors.append("temporal")
        if recurrence_support:
            factors.append("recurrence")

        return ConfidenceScore(
            value=value,
            evidence_count=evidence_count,
            snapshot_support=snapshot_count > 1,
            temporal_support=temporal_support,
            recurrence_support=recurrence_support,
            interpretation=interp,
            basis=f"Normalized from: {', '.join(factors)}",
        )

    def from_evidence_only(self, evidence_items: list[str]) -> ConfidenceScore:
        """Compute confidence from evidence list alone, with no raw score."""
        n = len([e for e in evidence_items if e and e.strip()])
        density_w = _interpolate(n, _EVIDENCE_DENSITY_WEIGHTS)
        interp = self.interpret(density_w)
        return ConfidenceScore(
            value=density_w,
            evidence_count=n,
            snapshot_support=False,
            temporal_support=False,
            recurrence_support=False,
            interpretation=interp,
            basis=f"Derived from {n} evidence item(s) only",
        )

    def from_synthesis_inputs(
        self,
        snapshot_count: int,
        matched_pattern_count: int,
        has_runtime: bool,
        has_temporal: bool,
    ) -> ConfidenceScore:
        """
        Compute ecosystem synthesis confidence from available input streams.

        Used by EcosystemSynthesisEngine to produce consistent confidence scores.
        """
        # Base: snapshot depth
        snap_w = _interpolate(snapshot_count, _SNAPSHOT_COUNT_WEIGHTS)
        # Bonus for pattern matches (each up to 0.05)
        pattern_bonus = min(matched_pattern_count * 0.04, 0.20)
        # Bonus for additional data streams
        runtime_bonus = 0.05 if has_runtime else 0.0
        temporal_bonus = 0.05 if has_temporal else 0.0

        value = min(snap_w + pattern_bonus + runtime_bonus + temporal_bonus, 1.0)
        interp = self.interpret(value)

        factors = [f"snapshots={snapshot_count}", f"patterns={matched_pattern_count}"]
        if has_runtime:
            factors.append("runtime")
        if has_temporal:
            factors.append("temporal")

        return ConfidenceScore(
            value=value,
            evidence_count=matched_pattern_count,
            snapshot_support=snapshot_count > 1,
            temporal_support=has_temporal,
            recurrence_support=False,
            interpretation=interp,
            basis=f"Synthesis inputs: {', '.join(factors)}",
        )

    def interpret(self, score: float) -> str:
        """Map score to human-readable interpretation band."""
        for threshold, label in _INTERPRETATION_BANDS:
            if score >= threshold:
                return label
        return "insufficient"

    def confidence_note(self, score: ConfidenceScore) -> str:
        """
        Generate a one-line advisory note suitable for report footers.

        Emphasizes evidence-strength semantics, not probability language.
        """
        return (
            f"Confidence: {score.value:.2f} ({score.interpretation}) — "
            f"reflects strength of {score.evidence_count} supporting signal(s). "
            f"Not a probability of correctness."
        )
