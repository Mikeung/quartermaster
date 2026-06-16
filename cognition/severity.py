"""
Operational severity model — formal severity classification with explicit scoring.

Severity is operational importance, not prediction.
Every severity assessment includes a score breakdown, evidence, and confidence.

Severity levels:
  informational → low → moderate → high → critical

Scoring factors (with weights):
  - runtime instability   30%
  - recommendation signal 25%
  - temporal volatility   20%
  - recurrence            15%
  - cost amplification    10%

Deterministic. Explainable. Evidence-backed. Advisory-only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SeverityLevel(str, Enum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_THRESHOLDS = [
    (0.80, SeverityLevel.CRITICAL),
    (0.60, SeverityLevel.HIGH),
    (0.40, SeverityLevel.MODERATE),
    (0.20, SeverityLevel.LOW),
]

_FACTOR_WEIGHTS = {
    "runtime_instability": 0.30,
    "recommendation_signal": 0.25,
    "temporal_volatility": 0.20,
    "recurrence": 0.15,
    "cost_amplification": 0.10,
}


@dataclass
class SeverityFactor:
    """A single factor contributing to the overall severity score."""
    name: str
    raw_value: float   # 0.0-1.0 before weighting
    weight: float
    contribution: float  # raw_value × weight
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_value": round(self.raw_value, 3),
            "weight": self.weight,
            "contribution": round(self.contribution, 3),
            "description": self.description,
        }


@dataclass
class SeverityAssessment:
    """Full operational severity assessment with traceable score breakdown."""
    level: SeverityLevel
    score: float           # 0.0-1.0
    factors: list[SeverityFactor]
    evidence: list[str]
    confidence: float      # 0.0-1.0 based on data availability
    assessed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "score": round(self.score, 3),
            "factors": [f.to_dict() for f in self.factors],
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "assessed_at": self.assessed_at,
        }


class SeverityEngine:
    """Produces an operational severity assessment from multiple intelligence inputs.

    All factors are weighted explicitly. Every factor contributes to the score
    and is included in the output for operator review.
    """

    def assess(
        self,
        runtime_health_score: float | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        temporal_volatility: float | None = None,
        recurrence_count: int = 0,
        cost_observations: list[dict[str, Any]] | None = None,
    ) -> SeverityAssessment:
        factors: list[SeverityFactor] = []
        evidence: list[str] = []
        data_points = 0

        # Factor 1: Runtime instability (30%)
        if runtime_health_score is not None:
            raw = 1.0 - runtime_health_score  # invert: 0 health → 1.0 instability
            weight = _FACTOR_WEIGHTS["runtime_instability"]
            factors.append(SeverityFactor(
                name="runtime_instability",
                raw_value=raw,
                weight=weight,
                contribution=raw * weight,
                description=f"Runtime health score: {runtime_health_score:.3f} "
                            f"(instability: {raw:.3f})",
            ))
            if raw > 0.5:
                evidence.append(f"Runtime health degraded: score {runtime_health_score:.2f}")
            data_points += 1

        # Factor 2: Recommendation signal (25%)
        if recommendations:
            recs = recommendations
            if recs:
                top_confidence = max(float(r.get("confidence", 0)) for r in recs)
                high_impact_count = sum(1 for r in recs if r.get("impact") == "high")
                raw = min(top_confidence * (1.0 + high_impact_count * 0.10), 1.0)
            else:
                raw = 0.0
            weight = _FACTOR_WEIGHTS["recommendation_signal"]
            factors.append(SeverityFactor(
                name="recommendation_signal",
                raw_value=raw,
                weight=weight,
                contribution=raw * weight,
                description=f"{len(recs)} recommendation(s); "
                            f"top confidence: {raw:.2f}; high-impact: {high_impact_count}",
            ))
            if raw > 0.6:
                evidence.append(f"High-confidence recommendations present ({raw:.2f})")
            data_points += 1
        else:
            high_impact_count = 0

        # Factor 3: Temporal volatility (20%)
        if temporal_volatility is not None:
            raw = temporal_volatility
            weight = _FACTOR_WEIGHTS["temporal_volatility"]
            factors.append(SeverityFactor(
                name="temporal_volatility",
                raw_value=raw,
                weight=weight,
                contribution=raw * weight,
                description=f"Temporal volatility score: {raw:.3f}",
            ))
            if raw > 0.4:
                evidence.append(f"Elevated temporal volatility: {raw:.2f}")
            data_points += 1

        # Factor 4: Recurrence (15%)
        recurrence_raw = min(recurrence_count / 10.0, 1.0)
        weight = _FACTOR_WEIGHTS["recurrence"]
        factors.append(SeverityFactor(
            name="recurrence",
            raw_value=recurrence_raw,
            weight=weight,
            contribution=recurrence_raw * weight,
            description=f"Recurring issues detected: {recurrence_count} patterns",
        ))
        if recurrence_count >= 2:
            evidence.append(f"Recurring issues: {recurrence_count} repeated pattern(s)")

        # Factor 5: Cost amplification (10%)
        if cost_observations:
            high_cost = [c for c in cost_observations if c.get("severity") == "high"]
            warnings = [c for c in cost_observations if c.get("severity") == "warning"]
            raw = min(len(high_cost) * 0.4 + len(warnings) * 0.2, 1.0)
            weight = _FACTOR_WEIGHTS["cost_amplification"]
            factors.append(SeverityFactor(
                name="cost_amplification",
                raw_value=raw,
                weight=weight,
                contribution=raw * weight,
                description=f"Cost observations: {len(high_cost)} high severity, {len(warnings)} warnings",
            ))
            if raw > 0.3:
                evidence.append(f"Cost risk elevated: {len(high_cost)} high-severity observations")
            data_points += 1

        total_score = sum(f.contribution for f in factors)
        total_score = min(round(total_score, 3), 1.0)

        level = SeverityLevel.INFORMATIONAL
        for threshold, lvl in _SEVERITY_THRESHOLDS:
            if total_score >= threshold:
                level = lvl
                break

        # Confidence = proportion of possible data points that were available
        max_data_points = len(_FACTOR_WEIGHTS)
        confidence = round(data_points / max_data_points, 2) if max_data_points else 0.0

        logger.info(
            "Severity assessment complete",
            extra={
                "level": level.value,
                "score": total_score,
                "confidence": confidence,
            },
        )

        return SeverityAssessment(
            level=level,
            score=total_score,
            factors=factors,
            evidence=evidence if evidence else ["No significant severity signals detected"],
            confidence=confidence,
            assessed_at=datetime.now(UTC).isoformat(),
        )


def severity_from_health_score(health_score: float) -> SeverityLevel:
    """Quick severity label from a runtime health score alone."""
    instability = 1.0 - health_score
    for threshold, level in _SEVERITY_THRESHOLDS:
        if instability >= threshold:
            return level
    return SeverityLevel.INFORMATIONAL
