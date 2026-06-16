"""
Investigation quality assessment — scores investigation results for reliability
and provides triage guidance for follow-on investigations.

Purpose: operators need to know how much to trust a result, and what to
investigate next. This module answers both questions deterministically.

All scoring is evidence-based and explainable.
No LLM calls, no ML, no autonomous actions.
Advisory only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Evidence thresholds
_EVIDENCE_MIN_ITEMS = 3       # below this → sparse
_EVIDENCE_STRONG_ITEMS = 6    # at or above → strong
_EVIDENCE_MIN_WORDS = 5       # items below this word count → shallow

# Snapshot coverage minimums by investigation kind
_SNAPSHOT_MINIMUMS: dict[str, int] = {
    "severity_increase": 2,
    "recent_changes": 3,
    "workflow_instability": 3,
    "component_involvement": 3,
    "recommendation_evidence": 1,
    "concern_contribution": 1,
}

# Confidence calibration thresholds
_CONFIDENCE_SUSPICIOUS = 0.80  # high confidence + sparse evidence → possible over-confidence

# Score band thresholds
_BAND_STRONG = 0.75
_BAND_ADEQUATE = 0.50
_BAND_LIMITED = 0.25

# Dimension weights
_W_EVIDENCE = 0.35
_W_SNAPSHOT = 0.30
_W_CALIBRATION = 0.20
_W_UNCERTAINTY = 0.15


@dataclass
class InvestigationQualityFlags:
    """Per-dimension boolean quality flags."""

    sparse_evidence: bool = False
    shallow_evidence: bool = False
    low_snapshot_coverage: bool = False
    confidence_miscalibrated: bool = False
    missing_uncertainty_notes: bool = False
    zero_confidence: bool = False

    @property
    def any_flag(self) -> bool:
        return any([
            self.sparse_evidence, self.shallow_evidence,
            self.low_snapshot_coverage, self.confidence_miscalibrated,
            self.missing_uncertainty_notes, self.zero_confidence,
        ])

    @property
    def flag_count(self) -> int:
        return sum([
            self.sparse_evidence, self.shallow_evidence,
            self.low_snapshot_coverage, self.confidence_miscalibrated,
            self.missing_uncertainty_notes, self.zero_confidence,
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "sparse_evidence": self.sparse_evidence,
            "shallow_evidence": self.shallow_evidence,
            "low_snapshot_coverage": self.low_snapshot_coverage,
            "confidence_miscalibrated": self.confidence_miscalibrated,
            "missing_uncertainty_notes": self.missing_uncertainty_notes,
            "zero_confidence": self.zero_confidence,
            "any_flag": self.any_flag,
            "flag_count": self.flag_count,
        }


@dataclass
class EvidenceDepthScore:
    """Detailed breakdown of evidence depth."""

    evidence_count: int
    short_item_count: int
    score: float
    is_sparse: bool
    is_shallow: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_count": self.evidence_count,
            "short_item_count": self.short_item_count,
            "score": round(self.score, 3),
            "is_sparse": self.is_sparse,
            "is_shallow": self.is_shallow,
        }


@dataclass
class InvestigationQualityAssessment:
    """Full quality assessment for a single investigation result."""

    kind: str
    quality_score: float       # 0.0–1.0
    quality_band: str          # "strong" | "adequate" | "limited" | "insufficient"
    flags: InvestigationQualityFlags
    evidence_depth: EvidenceDepthScore
    snapshot_coverage_score: float
    snapshot_count: int
    snapshot_minimum: int
    confidence_calibration_score: float
    uncertainty_completeness_score: float
    observations: list[str]
    guidance: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "quality_score": round(self.quality_score, 3),
            "quality_band": self.quality_band,
            "flags": self.flags.to_dict(),
            "evidence_depth": self.evidence_depth.to_dict(),
            "snapshot_coverage_score": round(self.snapshot_coverage_score, 3),
            "snapshot_count": self.snapshot_count,
            "snapshot_minimum": self.snapshot_minimum,
            "confidence_calibration_score": round(self.confidence_calibration_score, 3),
            "uncertainty_completeness_score": round(self.uncertainty_completeness_score, 3),
            "observations": self.observations,
            "guidance": self.guidance,
            "generated_at": self.generated_at,
            "advisory": (
                "Quality scoring is advisory. "
                "Low scores suggest limited data — not confirmed inaccuracy."
            ),
        }


@dataclass
class InvestigationTriageSuggestion:
    """A single next-step suggestion for follow-on investigation."""

    priority: str       # "high" | "medium" | "low"
    kind: str | None    # investigation kind to run next (None = general guidance)
    rationale: str
    context_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "kind": self.kind,
            "rationale": self.rationale,
            "context_hint": self.context_hint,
        }


@dataclass
class InvestigationTriageReport:
    """Quality assessment + next-step triage for an investigation session."""

    current_kind: str
    quality_assessment: InvestigationQualityAssessment
    suggestions: list[InvestigationTriageSuggestion]
    completed_kinds: list[str]
    remaining_kinds: list[str]
    coverage_fraction: float
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_kind": self.current_kind,
            "quality_assessment": self.quality_assessment.to_dict(),
            "suggestions": [s.to_dict() for s in self.suggestions],
            "completed_kinds": self.completed_kinds,
            "remaining_kinds": self.remaining_kinds,
            "coverage_fraction": round(self.coverage_fraction, 3),
            "generated_at": self.generated_at,
            "advisory": (
                "Triage suggestions are advisory. "
                "Run additional investigations based on operator judgment."
            ),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class InvestigationQualityEngine:
    """
    Scores investigation results for quality and provides triage guidance.

    Accepts investigation result dicts (from InvestigationResult.to_dict()).
    No coupling to InvestigationResult dataclass — works on plain dicts.
    All scoring deterministic. No LLM, no ML.
    """

    def score(self, result: dict[str, Any]) -> InvestigationQualityAssessment:
        """Score a single investigation result for quality."""
        kind = result.get("kind", "")
        evidence = result.get("evidence_chain", [])
        confidence = float(result.get("confidence", 0.0))
        uncertainty = result.get("uncertainty_notes", [])
        snap_ids = result.get("related_snapshot_ids", [])

        ev_depth = _score_evidence_depth(evidence)
        snap_coverage, snap_min = _score_snapshot_coverage(kind, snap_ids)
        conf_calibration = _score_confidence_calibration(confidence, ev_depth.evidence_count)
        unc_completeness = _score_uncertainty_completeness(uncertainty)

        flags = InvestigationQualityFlags(
            sparse_evidence=ev_depth.is_sparse,
            shallow_evidence=ev_depth.is_shallow,
            low_snapshot_coverage=snap_coverage < 0.50,
            confidence_miscalibrated=conf_calibration < 0.60,
            missing_uncertainty_notes=len(uncertainty) == 0,
            zero_confidence=(confidence == 0.0),
        )

        score = max(0.0, min(1.0,
            ev_depth.score * _W_EVIDENCE
            + snap_coverage * _W_SNAPSHOT
            + conf_calibration * _W_CALIBRATION
            + unc_completeness * _W_UNCERTAINTY
        ))

        band = _quality_band(score)
        observations = _build_observations(kind, flags, ev_depth, snap_ids, confidence)
        guidance = _build_guidance(band, flags)

        logger.debug(
            "Investigation quality scored",
            extra={"kind": kind, "score": score, "band": band},
        )
        return InvestigationQualityAssessment(
            kind=kind,
            quality_score=score,
            quality_band=band,
            flags=flags,
            evidence_depth=ev_depth,
            snapshot_coverage_score=snap_coverage,
            snapshot_count=len(snap_ids),
            snapshot_minimum=snap_min,
            confidence_calibration_score=conf_calibration,
            uncertainty_completeness_score=unc_completeness,
            observations=observations,
            guidance=guidance,
        )

    def triage(
        self,
        result: dict[str, Any],
        completed_kinds: list[str] | None = None,
    ) -> InvestigationTriageReport:
        """
        Provide triage: what should the operator investigate next?

        completed_kinds: investigation kinds already run this session.
        If not provided, only the current result's kind is marked completed.
        """
        from cognition.investigation import VALID_KINDS

        completed = list(completed_kinds or [result.get("kind", "")])
        remaining = sorted(VALID_KINDS - set(completed))
        coverage = len(completed) / max(len(VALID_KINDS), 1)

        quality = self.score(result)
        suggestions = _build_triage_suggestions(result, quality, completed, remaining)

        return InvestigationTriageReport(
            current_kind=result.get("kind", ""),
            quality_assessment=quality,
            suggestions=suggestions,
            completed_kinds=completed,
            remaining_kinds=remaining,
            coverage_fraction=coverage,
        )

    def batch_score(
        self,
        results: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], InvestigationQualityAssessment]]:
        """Score a list of investigation results. Returns (result, assessment) pairs."""
        return [(r, self.score(r)) for r in results]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------

def _score_evidence_depth(evidence: list[Any]) -> EvidenceDepthScore:
    count = len(evidence)
    short_count = sum(
        1 for item in evidence
        if len(str(item).split()) < _EVIDENCE_MIN_WORDS
    )

    if count == 0:
        score = 0.0
    elif count == 1:
        score = 0.15
    elif count == 2:
        score = 0.40
    elif count == 3:
        score = 0.60
    elif count <= 5:
        score = 0.75
    elif count < _EVIDENCE_STRONG_ITEMS:
        score = 0.90
    else:
        score = 1.0

    # Penalize if >50% of items are short
    if count > 0 and (short_count / count) > 0.5:
        score = max(0.0, score - 0.20)

    return EvidenceDepthScore(
        evidence_count=count,
        short_item_count=short_count,
        score=score,
        is_sparse=count < _EVIDENCE_MIN_ITEMS,
        is_shallow=(count > 0 and (short_count / count) > 0.5),
    )


def _score_snapshot_coverage(kind: str, snap_ids: list[int]) -> tuple[float, int]:
    """Returns (coverage_score, minimum_needed)."""
    minimum = _SNAPSHOT_MINIMUMS.get(kind, 1)
    count = len(snap_ids)
    if count == 0:
        return 0.0, minimum
    if count >= minimum:
        return 1.0, minimum
    return count / minimum, minimum


def _score_confidence_calibration(confidence: float, evidence_count: int) -> float:
    """Checks confidence is appropriate given evidence volume."""
    if evidence_count == 0:
        # Zero evidence → confidence should be near-zero
        return 1.0 if confidence < 0.10 else 0.30
    if evidence_count < _EVIDENCE_MIN_ITEMS and confidence > _CONFIDENCE_SUSPICIOUS:
        # Very few evidence items but high confidence → suspicious
        return 0.40
    return 1.0


def _score_uncertainty_completeness(uncertainty: list[str]) -> float:
    if not uncertainty:
        return 0.40
    substantive = sum(1 for n in uncertainty if len(n.split()) >= 10)
    if substantive >= 2:
        return 1.0
    if substantive == 1:
        return 0.85
    if len(uncertainty) >= 2:
        return 0.75
    return 0.65


def _quality_band(score: float) -> str:
    if score >= _BAND_STRONG:
        return "strong"
    if score >= _BAND_ADEQUATE:
        return "adequate"
    if score >= _BAND_LIMITED:
        return "limited"
    return "insufficient"


def _build_observations(
    kind: str,
    flags: InvestigationQualityFlags,
    ev_depth: EvidenceDepthScore,
    snap_ids: list[int],
    confidence: float,
) -> list[str]:
    obs = [
        f"Kind: {kind}. Evidence items: {ev_depth.evidence_count}. "
        f"Snapshots referenced: {len(snap_ids)}. Confidence: {confidence:.2f}."
    ]
    if flags.sparse_evidence:
        obs.append(
            f"Evidence is sparse ({ev_depth.evidence_count} item(s), "
            f"minimum {_EVIDENCE_MIN_ITEMS}). "
            "More snapshot history may improve coverage."
        )
    if flags.shallow_evidence:
        obs.append(
            f"{ev_depth.short_item_count}/{ev_depth.evidence_count} evidence "
            "item(s) are short (<5 words) — may lack detail."
        )
    if flags.low_snapshot_coverage:
        min_needed = _SNAPSHOT_MINIMUMS.get(kind, 1)
        obs.append(
            f"Low snapshot coverage: {len(snap_ids)} referenced "
            f"(minimum {min_needed} for '{kind}')."
        )
    if flags.confidence_miscalibrated:
        obs.append(
            f"Confidence ({confidence:.2f}) appears high relative to evidence volume. "
            "Treat with appropriate skepticism."
        )
    if flags.missing_uncertainty_notes:
        obs.append("No uncertainty notes — all investigation results should acknowledge limitations.")
    return obs


def _build_guidance(band: str, flags: InvestigationQualityFlags) -> list[str]:
    guidance = []
    if band == "insufficient":
        guidance.append(
            "Insufficient evidence to be actionable. "
            "Collect more snapshot history before acting on these findings."
        )
    elif band == "limited":
        guidance.append(
            "Limited evidence — treat as preliminary indicators, not conclusions."
        )
    if flags.sparse_evidence:
        guidance.append(
            "Expand snapshot window or increase scan frequency to improve evidence coverage."
        )
    if flags.confidence_miscalibrated:
        guidance.append(
            "Confidence appears uncalibrated — verify findings directly against recent snapshots."
        )
    if not guidance:
        if band == "strong":
            guidance.append(
                "Evidence quality is sufficient to act on these findings with standard operator review."
            )
        else:
            guidance.append(
                "Evidence is adequate — findings are directionally reliable but not definitive."
            )
    return guidance


# ---------------------------------------------------------------------------
# Triage rules
# ---------------------------------------------------------------------------

def _build_triage_suggestions(
    result: dict[str, Any],
    quality: InvestigationQualityAssessment,
    completed: list[str],
    remaining: list[str],
) -> list[InvestigationTriageSuggestion]:
    kind = result.get("kind", "")
    confidence = float(result.get("confidence", 0.0))
    suggestions: list[InvestigationTriageSuggestion] = []
    seen_kinds: set[str | None] = set()

    def _add(sug: InvestigationTriageSuggestion) -> None:
        if sug.kind in completed:
            return
        if sug.kind in seen_kinds:
            return
        seen_kinds.add(sug.kind)
        suggestions.append(sug)

    # Quality-first: if result is limited/insufficient, warn immediately
    if quality.quality_band in ("limited", "insufficient"):
        _add(InvestigationTriageSuggestion(
            priority="high",
            kind=None,
            rationale=(
                f"Investigation quality is {quality.quality_band} — "
                "additional snapshot history would improve reliability. "
                "Consider waiting for more scans before acting on findings."
            ),
            context_hint=(
                "Increase 'days' or 'max_snapshots' parameters on the next investigation run."
            ),
        ))

    # Kind-specific follow-on rules
    if kind == "severity_increase":
        if result.get("related_recommendations"):
            _add(InvestigationTriageSuggestion(
                priority="high",
                kind="recommendation_evidence",
                rationale=(
                    "Severity increase identified new recommendations — "
                    "trace their evidence to understand what triggered the change."
                ),
                context_hint=(
                    "Use the 'title' parameter to target the most recently added recommendation."
                ),
            ))
        if confidence > 0.40 and "recent_changes" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="recent_changes",
                rationale=(
                    "Understanding what changed before severity increased "
                    "provides the change sequence."
                ),
                context_hint="Extend 'days' window to cover the period before severity first changed.",
            ))

    elif kind == "recent_changes":
        if confidence > 0.35 and "component_involvement" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="high",
                kind="component_involvement",
                rationale=(
                    "Recent changes detected — component involvement reveals "
                    "which parts are repeatedly affected."
                ),
                context_hint="No additional context needed — engine uses all available snapshots.",
            ))
        if result.get("related_runtime_events") and "workflow_instability" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="workflow_instability",
                rationale=(
                    "Runtime events correlate with recent changes — "
                    "workflow instability investigation may surface the affected workflow."
                ),
                context_hint=(
                    "Use the 'workflow_type' parameter if a specific workflow was flagged."
                ),
            ))

    elif kind == "component_involvement":
        if confidence > 0.40 and "severity_increase" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="severity_increase",
                rationale=(
                    "Recurring components identified — severity increase investigation "
                    "shows how these components contributed to operational degradation."
                ),
                context_hint="Expand snapshot window to cover the recurring component's history.",
            ))
        if "concern_contribution" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="low",
                kind="concern_contribution",
                rationale=(
                    "Recurring component patterns found — concern contribution "
                    "decomposes their weighted impact on operational severity."
                ),
                context_hint="No additional context needed.",
            ))

    elif kind == "recommendation_evidence":
        if "severity_increase" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="severity_increase",
                rationale=(
                    "Understanding when severity first increased contextualises this recommendation's history."
                ),
                context_hint="Extend snapshot window to cover the recommendation's first appearance.",
            ))

    elif kind == "workflow_instability":
        if result.get("related_workflows") and "concern_contribution" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="concern_contribution",
                rationale=(
                    "Workflow instability detected — severity contribution shows "
                    "its weighted operational impact."
                ),
                context_hint="No additional context needed.",
            ))
        if "component_involvement" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="low",
                kind="component_involvement",
                rationale=(
                    "Component involvement reveals which infrastructure elements "
                    "correlate with this workflow's instability."
                ),
                context_hint="No additional context needed.",
            ))

    elif kind == "concern_contribution":
        if result.get("related_recommendations") and "recommendation_evidence" in remaining:
            _add(InvestigationTriageSuggestion(
                priority="medium",
                kind="recommendation_evidence",
                rationale=(
                    "Top concern identified — tracing its evidence provides "
                    "specificity beyond the contribution score."
                ),
                context_hint=(
                    "Use the 'title' parameter with the highest-contributing recommendation title."
                ),
            ))

    # Coverage-based fallback: if few kinds have been run, suggest a broadly useful one
    if len(completed) < 3 and remaining:
        priority_fallback = [
            k for k in [
                "recent_changes", "component_involvement",
                "severity_increase", "concern_contribution",
            ]
            if k in remaining and k not in seen_kinds
        ]
        if priority_fallback:
            next_kind = priority_fallback[0]
            _add(InvestigationTriageSuggestion(
                priority="low",
                kind=next_kind,
                rationale=(
                    f"Investigation coverage is low ({len(completed)}/6 kinds run). "
                    f"'{next_kind}' provides broad operational context."
                ),
                context_hint="Use default parameters — no specific context needed.",
            ))

    # Sort by priority
    _order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: _order.get(s.priority, 3))
    return suggestions[:5]
