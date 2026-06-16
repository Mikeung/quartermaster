"""
Report Refinement — executive summaries, dedup-aware compactness, noise suppression.

Purpose:
Wraps existing report generators with post-processing that:
1. Produces executive summaries (≤200 words) from verbose reports
2. Applies deduplication and evidence compression to improve signal-to-noise
3. Provides compact formatting helpers for human-readable output

Design rules:
- No ML, no embeddings, no external API calls.
- All processing is deterministic.
- Never modifies source data — produces new views only.
- Bounded language throughout.
- Advisory notes are preserved or strengthened, never removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognition.deduplication import SignalDeduplicationEngine
from cognition.evidence_compression import EvidenceCompressor

logger = logging.getLogger(__name__)

_COMPRESSOR = EvidenceCompressor()
_DEDUPLICATOR = SignalDeduplicationEngine()

# Maximum items to show in a compact summary section
_COMPACT_MAX_ITEMS = 5
_COMPACT_MAX_EVIDENCE = 3


# -----------------------------------------------------------------------
# Executive summary types
# -----------------------------------------------------------------------

@dataclass
class ExecutiveSummary:
    """
    ≤200-word operational summary suitable for a daily briefing or status email.
    """
    headline: str
    status: str              # "ok" | "warning" | "critical"
    key_points: list[str]    # 3–5 bullet points
    top_action: str          # single most important action, or empty string
    advisory: str = (
        "Advisory only. All operational decisions require human review."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "status": self.status,
            "key_points": self.key_points,
            "top_action": self.top_action,
            "advisory": self.advisory,
        }

    def markdown(self) -> str:
        lines = [
            f"## {self.headline}",
            f"**Status:** {self.status.upper()}",
            "",
        ]
        for kp in self.key_points:
            lines.append(f"- {kp}")
        if self.top_action:
            lines += ["", f"**Recommended action:** {self.top_action}"]
        lines += ["", f"_{self.advisory}_"]
        return "\n".join(lines)


@dataclass
class CompactRecommendationSet:
    """
    Deduplicated and evidence-compressed recommendation set for display.
    """
    recommendations: list[dict[str, Any]]
    input_count: int
    output_count: int
    dedup_ratio: float
    compression_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendations": self.recommendations,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "dedup_ratio": round(self.dedup_ratio, 3),
            "compression_notes": self.compression_notes,
        }


@dataclass
class OperatorFatigueReport:
    """
    Measures how much of the current recommendation set represents
    repeated, stale, or low-quality signals that may be fatiguing operators.

    A high fatigue score suggests that most signals have already been seen and
    that the operator is not getting new actionable information.

    Advisory only. Fatigue score does not trigger automatic suppression.
    """
    fatigue_score: float              # 0.0 (no fatigue) → 1.0 (all signals stale/repeated)
    fatigue_band: str                 # "low" | "moderate" | "high"
    total_signals: int
    stale_signal_count: int           # signals with recurrence >= stale threshold
    weak_signal_count: int            # signals with weak evidence
    suppression_candidates: int       # signals below quality threshold
    dominant_category: str            # most common category, or ""
    saturation_detected: bool
    observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fatigue_score": round(self.fatigue_score, 3),
            "fatigue_band": self.fatigue_band,
            "total_signals": self.total_signals,
            "stale_signal_count": self.stale_signal_count,
            "weak_signal_count": self.weak_signal_count,
            "suppression_candidates": self.suppression_candidates,
            "dominant_category": self.dominant_category,
            "saturation_detected": self.saturation_detected,
            "observations": self.observations,
            "advisory": (
                "Fatigue score is advisory. It reflects signal repetition patterns, "
                "not the operational importance of any individual signal."
            ),
        }

    def markdown(self) -> str:
        band_icon = {"low": "✓", "moderate": "⚠", "high": "✗"}.get(
            self.fatigue_band, "•"
        )
        lines = [
            f"### {band_icon} Operator Fatigue: {self.fatigue_band.upper()} "
            f"({self.fatigue_score:.0%})",
            "",
            f"- Total signals assessed: {self.total_signals}",
            f"- Stale/recurring signals: {self.stale_signal_count}",
            f"- Weak evidence signals: {self.weak_signal_count}",
            f"- Suppression candidates: {self.suppression_candidates}",
        ]
        if self.saturation_detected and self.dominant_category:
            lines.append(f"- Dominant category: {self.dominant_category} (saturation detected)")
        if self.observations:
            lines.append("")
            for o in self.observations:
                lines.append(f"> {o}")
        lines += ["", "_Advisory only. Human review required before suppressing any signal._"]
        return "\n".join(lines)


@dataclass
class QualityFilteredSet:
    """
    Recommendation set after signal quality filtering.

    Kept signals passed the quality threshold.
    Suppressed signals are retained here (never deleted) with suppression annotations.
    """
    kept: list[dict[str, Any]]
    suppressed: list[dict[str, Any]]
    total_input: int
    quality_filter_ratio: float       # fraction suppressed
    fatigue_report: OperatorFatigueReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "kept": self.kept,
            "suppressed": self.suppressed,
            "total_input": self.total_input,
            "quality_filter_ratio": round(self.quality_filter_ratio, 3),
            "fatigue_report": self.fatigue_report.to_dict(),
        }


# -----------------------------------------------------------------------
# Refinement engine
# -----------------------------------------------------------------------

class ReportRefinementEngine:
    """
    Post-processes verbose reports into compact, high-signal outputs.

    Usage:
        engine = ReportRefinementEngine()
        summary = engine.executive_summary(attention_report)
        compact = engine.compact_recommendations(raw_recommendations)
    """

    def executive_summary(
        self, attention_report: dict[str, Any]
    ) -> ExecutiveSummary:
        """
        Produce an executive summary from an attention report.

        Attention report is expected to have:
        - overall_status: str
        - high_priority: list[dict] (recommendations)
        - runtime_concerns: list[dict]
        - summary: str | None
        """
        status = attention_report.get("overall_status", "ok")
        high_priority = attention_report.get("high_priority", [])
        runtime_concerns = attention_report.get("runtime_concerns", [])
        warning_count = attention_report.get("warning_count", 0)
        critical_count = attention_report.get("critical_count", 0)

        # Build headline
        if status == "critical":
            headline = f"Operational Status: CRITICAL — {critical_count} Critical Concern(s)"
        elif status == "warning":
            headline = f"Operational Status: WARNING — {warning_count} Warning(s)"
        else:
            headline = "Operational Status: OK"

        # Key points (≤5)
        key_points: list[str] = []

        if critical_count:
            key_points.append(
                f"{critical_count} critical concern(s) require immediate attention."
            )
        if warning_count:
            key_points.append(
                f"{warning_count} warning(s) detected across the operational profile."
            )

        if high_priority:
            top = high_priority[0]
            title = top.get("title", "")
            cat = top.get("category", "")
            if title:
                key_points.append(
                    f"Top concern: {title}"
                    + (f" ({cat})" if cat else "")
                )

        if runtime_concerns:
            key_points.append(
                f"{len(runtime_concerns)} live runtime concern(s) detected."
            )

        if not key_points:
            key_points.append("No significant concerns detected in this period.")

        # Trim to 5
        key_points = key_points[:5]

        # Top action
        top_action = ""
        if high_priority:
            first = high_priority[0]
            top_action = first.get("title", "")
            if not top_action and first.get("description"):
                top_action = str(first["description"])[:120]
        elif runtime_concerns:
            top_action = str(runtime_concerns[0].get("message", ""))[:120]

        return ExecutiveSummary(
            headline=headline,
            status=status,
            key_points=key_points,
            top_action=top_action,
        )

    def compact_recommendations(
        self,
        recommendations: list[dict[str, Any]],
        max_output: int = _COMPACT_MAX_ITEMS,
    ) -> CompactRecommendationSet:
        """
        Deduplicate and evidence-compress a recommendation list.

        Returns a compact set suitable for display in a short report section.
        """
        if not recommendations:
            return CompactRecommendationSet(
                recommendations=[],
                input_count=0,
                output_count=0,
                dedup_ratio=0.0,
                compression_notes=[],
            )

        # Step 1: deduplicate
        dedup_result = _DEDUPLICATOR.deduplicate(recommendations)
        deduped = [c.to_dict() for c in dedup_result.concerns]

        # Step 2: compress evidence on each deduped rec
        compression_notes = []
        processed = []
        for rec in deduped:
            evidence = rec.get("evidence", [])
            if isinstance(evidence, list) and len(evidence) > _COMPACT_MAX_EVIDENCE:
                compressed = _COMPRESSOR.compress(evidence)
                rec = dict(rec)
                rec["evidence"] = compressed.compressed[:_COMPACT_MAX_EVIDENCE]
                if compressed.was_compressed:
                    compression_notes.append(
                        f"Evidence compressed for '{rec.get('title', '')[:40]}': "
                        f"{compressed.original_count} → {compressed.compressed_count} items"
                    )
            processed.append(rec)

        # Step 3: limit to max_output
        limited = processed[:max_output]

        input_count = len(recommendations)
        output_count = len(limited)
        dedup_ratio = 1.0 - (len(deduped) / input_count) if input_count > 0 else 0.0

        logger.debug(
            "Compact recommendations generated",
            extra={"input": input_count, "deduped": len(deduped), "output": output_count},
        )

        return CompactRecommendationSet(
            recommendations=limited,
            input_count=input_count,
            output_count=output_count,
            dedup_ratio=max(0.0, dedup_ratio),
            compression_notes=compression_notes,
        )

    def suppress_low_confidence(
        self,
        recommendations: list[dict[str, Any]],
        threshold: float = 0.35,
    ) -> list[dict[str, Any]]:
        """
        Filter out recommendations below the confidence threshold.

        This is the same threshold used in the attention guidance system.
        Returns a new list; source is not modified.
        """
        return [r for r in recommendations if float(r.get("confidence", 0)) >= threshold]

    def format_compact_section(
        self,
        title: str,
        items: list[str],
        max_items: int = _COMPACT_MAX_ITEMS,
        empty_message: str = "None detected.",
    ) -> str:
        """
        Format a compact bulleted markdown section.
        """
        lines = [f"### {title}", ""]
        if not items:
            lines.append(f"_{empty_message}_")
        else:
            for item in items[:max_items]:
                lines.append(f"- {item}")
            if len(items) > max_items:
                lines.append(f"- _(+{len(items) - max_items} more — see full report)_")
        lines.append("")
        return "\n".join(lines)

    def dedup_summary_line(self, dedup_ratio: float, input_count: int) -> str:
        """Return a one-line deduplication summary for inclusion in report footers."""
        if dedup_ratio <= 0 or input_count == 0:
            return f"All {input_count} signals appear distinct."
        suppressed = round(dedup_ratio * input_count)
        return (
            f"Deduplication: {suppressed} of {input_count} signals "
            f"({dedup_ratio:.0%}) appear to be near-duplicates and were collapsed."
        )

    def score_operator_fatigue(
        self,
        recommendations: list[dict[str, Any]],
        *,
        recurrence_by_title: dict[str, int] | None = None,
    ) -> OperatorFatigueReport:
        """
        Compute an operator fatigue score for a recommendation batch.

        Fatigue is high when most signals are stale, weak, or from a saturated category.
        This helps operators understand whether a batch contains genuinely new information
        or is mostly background noise they've already seen.

        Parameters:
        - recommendations: list of recommendation dicts
        - recurrence_by_title: title_prefix (60 chars) → recurrence count, or None
        """
        from cognition.signal_quality import SignalQualityEngine
        engine = SignalQualityEngine()

        if not recommendations:
            return OperatorFatigueReport(
                fatigue_score=0.0,
                fatigue_band="low",
                total_signals=0,
                stale_signal_count=0,
                weak_signal_count=0,
                suppression_candidates=0,
                dominant_category="",
                saturation_detected=False,
                observations=["No signals to assess."],
            )

        batch = engine.assess_batch(
            recommendations, recurrence_by_title=recurrence_by_title
        )

        stale = sum(
            1 for _, a in batch.assessments if a.flags.stale_signal
        )
        weak = sum(
            1 for _, a in batch.assessments if a.flags.weak_evidence
        )
        suppressed = batch.suppressed_count
        fatigue = batch.operator_fatigue_score

        if fatigue >= 0.70:
            band = "high"
        elif fatigue >= 0.40:
            band = "moderate"
        else:
            band = "low"

        return OperatorFatigueReport(
            fatigue_score=fatigue,
            fatigue_band=band,
            total_signals=batch.total_input,
            stale_signal_count=stale,
            weak_signal_count=weak,
            suppression_candidates=suppressed,
            dominant_category=batch.dominant_category,
            saturation_detected=batch.saturation_detected,
            observations=batch.observations,
        )

    def apply_quality_filter(
        self,
        recommendations: list[dict[str, Any]],
        *,
        recurrence_by_title: dict[str, int] | None = None,
    ) -> QualityFilteredSet:
        """
        Apply signal quality filtering to a recommendation list.

        Returns a QualityFilteredSet with:
        - kept: recommendations that passed quality threshold
        - suppressed: recommendations below threshold (annotated, never deleted)
        - fatigue_report: operator fatigue summary for the full batch

        Parameters:
        - recommendations: list of recommendation dicts
        - recurrence_by_title: title_prefix (60 chars) → recurrence count, or None

        Advisory only. Suppressed signals remain accessible — callers decide
        whether to display them.
        """
        from cognition.signal_quality import SignalQualityEngine
        engine = SignalQualityEngine()

        if not recommendations:
            empty_fatigue = OperatorFatigueReport(
                fatigue_score=0.0,
                fatigue_band="low",
                total_signals=0,
                stale_signal_count=0,
                weak_signal_count=0,
                suppression_candidates=0,
                dominant_category="",
                saturation_detected=False,
                observations=["No signals provided."],
            )
            return QualityFilteredSet(
                kept=[],
                suppressed=[],
                total_input=0,
                quality_filter_ratio=0.0,
                fatigue_report=empty_fatigue,
            )

        batch = engine.assess_batch(
            recommendations, recurrence_by_title=recurrence_by_title
        )

        kept = []
        suppressed_list = []

        for rec, assessment in batch.assessments:
            annotated = dict(rec)
            annotated["_quality_score"] = assessment.quality_score
            annotated["_adjusted_confidence"] = assessment.adjusted_confidence
            annotated["_suppressed"] = assessment.suppressed
            if assessment.suppressed:
                annotated["_suppression_reason"] = assessment.suppression_reason
                suppressed_list.append(annotated)
            else:
                kept.append(annotated)

        total = len(recommendations)
        filter_ratio = len(suppressed_list) / total if total > 0 else 0.0

        stale = sum(1 for _, a in batch.assessments if a.flags.stale_signal)
        weak = sum(1 for _, a in batch.assessments if a.flags.weak_evidence)
        fatigue = batch.operator_fatigue_score
        band = "high" if fatigue >= 0.70 else ("moderate" if fatigue >= 0.40 else "low")

        fatigue_report = OperatorFatigueReport(
            fatigue_score=fatigue,
            fatigue_band=band,
            total_signals=total,
            stale_signal_count=stale,
            weak_signal_count=weak,
            suppression_candidates=batch.suppressed_count,
            dominant_category=batch.dominant_category,
            saturation_detected=batch.saturation_detected,
            observations=batch.observations,
        )

        logger.debug(
            "Quality filter applied",
            extra={
                "total": total,
                "kept": len(kept),
                "suppressed": len(suppressed_list),
                "fatigue": round(fatigue, 3),
            },
        )

        return QualityFilteredSet(
            kept=kept,
            suppressed=suppressed_list,
            total_input=total,
            quality_filter_ratio=filter_ratio,
            fatigue_report=fatigue_report,
        )


# -----------------------------------------------------------------------
# Standalone convenience functions
# -----------------------------------------------------------------------

def make_executive_summary(attention_report: dict[str, Any]) -> ExecutiveSummary:
    """Convenience wrapper for one-off executive summary generation."""
    return ReportRefinementEngine().executive_summary(attention_report)


def make_compact_recommendations(
    recommendations: list[dict[str, Any]],
    max_output: int = _COMPACT_MAX_ITEMS,
) -> CompactRecommendationSet:
    """Convenience wrapper for one-off compact recommendation generation."""
    return ReportRefinementEngine().compact_recommendations(recommendations, max_output)
