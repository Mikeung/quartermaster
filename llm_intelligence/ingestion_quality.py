"""
Ingestion Quality Scoring — assess the operational usefulness of ingested LLM events.

Purpose:
Help operators understand whether their instrumentation is producing useful data,
without requiring them to increase telemetry volume.

Measures:
1. Field completeness — are all expected fields populated?
2. Token quality — are token counts non-zero and consistent?
3. Latency quality — is latency_ms captured (non-zero)?
4. Workflow naming quality — are workflow names meaningful?
5. Provider consistency — are provider names standardized?
6. Metadata utilization — is metadata being used helpfully?
7. Error type coverage — are failures classified?

Quality score: 0.0 (unusable) to 1.0 (excellent).
Interpretation bands:
  0.0 – 0.40 : poor   — critical fields missing
  0.40 – 0.70: fair   — basic data present, improvements available
  0.70 – 0.90: good   — most fields captured well
  0.90 – 1.0 : excellent — minimal improvement needed

Design rules:
- Deterministic: same inputs → same score
- Bounded language: quality score suggests confidence level, not guarantee
- Advisory only: no automatic remediation
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


# Workflow quality signals
_GENERIC_WORKFLOW_NAMES = frozenset({
    "default", "unknown", "test", "demo", "example", "my-workflow",
    "workflow", "llm-call", "call", "invoke", "run", "execute",
    "main", "handler", "process",
})
_WORKFLOW_SEPARATOR_RE = re.compile(r"[/\-_]")
_MIN_WORKFLOW_SEGMENTS = 2

# Provider name normalization signals
_RAW_PROVIDER_NAMES = frozenset({
    "openai-client", "langchain_openai", "langchain-anthropic",
    "httpx", "requests", "aiohttp",
})

# Score weights (must sum to 1.0)
_WEIGHTS = {
    "field_completeness": 0.30,
    "token_quality": 0.25,
    "latency_quality": 0.15,
    "workflow_naming": 0.15,
    "error_coverage": 0.10,
    "metadata_utilization": 0.05,
}


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class QualityDimension:
    """Score and observations for one quality dimension."""

    name: str
    score: float          # 0.0 – 1.0
    observations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 3),
            "observations": self.observations,
            "warnings": self.warnings,
        }


@dataclass
class IngestionQualityReport:
    """Full ingestion quality assessment for a set of LLM events."""

    quality_score: float
    quality_band: str           # "poor" | "fair" | "good" | "excellent"
    total_events_assessed: int
    dimensions: list[QualityDimension]
    integration_warnings: list[str]
    improvement_suggestions: list[str]
    generated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_score": round(self.quality_score, 3),
            "quality_band": self.quality_band,
            "total_events_assessed": self.total_events_assessed,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "integration_warnings": self.integration_warnings,
            "improvement_suggestions": self.improvement_suggestions,
            "generated_at": self.generated_at,
            "advisory": (
                "Quality score is an estimate based on statistical patterns in the event data. "
                "It suggests areas for improvement — not a definitive measure of instrumentation correctness."
            ),
        }

    def markdown(self) -> str:
        band_icon = {"poor": "✗", "fair": "△", "good": "✓", "excellent": "★"}.get(
            self.quality_band, "?"
        )
        lines = [
            "# Ingestion Quality Report",
            "",
            f"**Quality Score:** {self.quality_score:.2f} / 1.00  "
            f"| **Band:** {band_icon} {self.quality_band.upper()}",
            f"**Events Assessed:** {self.total_events_assessed:,}",
            "",
            "## Dimension Scores",
            "",
            "| Dimension | Score | Status |",
            "|---|---|---|",
        ]
        for d in self.dimensions:
            icon = "✓" if d.score >= 0.70 else ("△" if d.score >= 0.40 else "✗")
            lines.append(f"| {d.name} | {d.score:.2f} | {icon} |")

        if self.integration_warnings:
            lines += ["", "## Warnings", ""]
            for w in self.integration_warnings:
                lines.append(f"- ⚠ {w}")

        if self.improvement_suggestions:
            lines += ["", "## Improvement Suggestions", ""]
            for s in self.improvement_suggestions:
                lines.append(f"- {s}")

        lines += [
            "",
            "---",
            "_Quality score is advisory. It reflects patterns in the observed events_",
            "_and suggests instrumentation improvements. Operator review recommended._",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class IngestionQualityScorer:
    """
    Scores the operational quality of ingested LLM event data.

    Accepts pre-aggregated stats from the LLM event store rather than
    raw event rows to keep this layer stateless.

    Pre-aggregated inputs expected:
    - provider_stats: list of {provider, total_events, error_count, avg_latency_ms, avg_prompt_tokens, avg_completion_tokens}
    - workflow_stats: list of {workflow, total_events, avg_prompt_tokens, avg_completion_tokens, error_count}
    - total_events: total event count
    - events_with_metadata: count with non-empty metadata
    - events_with_error_type: count of failure events that have error_type set
    - total_failures: total events where success=False
    """

    def score(
        self,
        *,
        provider_stats: list[dict[str, Any]],
        workflow_stats: list[dict[str, Any]],
        total_events: int,
        events_with_metadata: int = 0,
        events_with_error_type: int = 0,
        total_failures: int = 0,
    ) -> IngestionQualityReport:
        """Compute an ingestion quality report from pre-aggregated stats."""
        if total_events == 0:
            return _empty_report()

        from datetime import UTC, datetime

        dimensions: list[QualityDimension] = []

        d_completeness = self._score_field_completeness(provider_stats, workflow_stats)
        d_tokens = self._score_token_quality(provider_stats, workflow_stats, total_events)
        d_latency = self._score_latency_quality(provider_stats, total_events)
        d_workflow = self._score_workflow_naming(workflow_stats)
        d_errors = self._score_error_coverage(total_failures, events_with_error_type)
        d_metadata = self._score_metadata_utilization(events_with_metadata, total_events)

        dimensions = [d_completeness, d_tokens, d_latency, d_workflow, d_errors, d_metadata]

        # Weighted composite score
        score = sum(
            _WEIGHTS[d.name.lower().replace(" ", "_")] * d.score
            for d in dimensions
        )
        score = max(0.0, min(1.0, score))
        band = _score_band(score)

        warnings = self._build_warnings(dimensions)
        suggestions = self._build_suggestions(dimensions, score)

        logger.info(
            "Ingestion quality scored",
            extra={
                "quality_score": round(score, 3),
                "band": band,
                "events": total_events,
            },
        )

        return IngestionQualityReport(
            quality_score=score,
            quality_band=band,
            total_events_assessed=total_events,
            dimensions=dimensions,
            integration_warnings=warnings,
            improvement_suggestions=suggestions,
            generated_at=datetime.now(UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    def _score_field_completeness(
        self,
        provider_stats: list[dict[str, Any]],
        workflow_stats: list[dict[str, Any]],
    ) -> QualityDimension:
        observations = []
        warnings = []
        score = 1.0

        if not provider_stats:
            return QualityDimension(
                name="Field Completeness",
                score=0.0,
                observations=["No provider data available — field completeness cannot be assessed."],
                warnings=["No provider stats found — events may not be ingested correctly."],
            )

        unknown_providers = sum(
            1 for p in provider_stats if p.get("provider", "") in ("unknown", "", "test")
        )
        if unknown_providers > 0:
            observations.append(f"{unknown_providers} event group(s) have unknown/test provider names.")
            score -= 0.15

        unknown_workflows = sum(
            1 for w in workflow_stats
            if w.get("workflow", "").lower() in _GENERIC_WORKFLOW_NAMES
        )
        if unknown_workflows > 0:
            observations.append(f"{unknown_workflows} workflow group(s) use generic names.")
            score -= 0.10

        if not observations:
            observations.append("Provider and workflow names appear well-populated.")

        return QualityDimension(
            name="Field Completeness",
            score=max(0.0, score),
            observations=observations,
            warnings=warnings,
        )

    def _score_token_quality(
        self,
        provider_stats: list[dict[str, Any]],
        workflow_stats: list[dict[str, Any]],
        total_events: int,
    ) -> QualityDimension:
        observations = []
        warnings = []
        score = 1.0

        zero_prompt = [
            p.get("provider", "?") for p in provider_stats
            if (p.get("avg_prompt_tokens") or 0) == 0 and (p.get("total_events") or 0) > 5
        ]
        if zero_prompt:
            warnings.append(
                f"Provider(s) {zero_prompt} appear to have zero average prompt tokens — "
                "token capture may be missing."
            )
            score -= 0.30 * (len(zero_prompt) / max(len(provider_stats), 1))

        zero_completion = [
            w.get("workflow", "?") for w in workflow_stats
            if (w.get("avg_completion_tokens") or 0) == 0
            and (w.get("avg_prompt_tokens") or 0) > 0
            and (w.get("total_events") or 0) > 5
        ]
        if zero_completion:
            observations.append(
                f"{len(zero_completion)} workflow(s) show zero completion tokens — "
                "may be embedding or streaming workflows."
            )
            score -= 0.10

        if not warnings:
            observations.append("Token counts appear to be captured consistently.")

        return QualityDimension(
            name="Token Quality",
            score=max(0.0, score),
            observations=observations,
            warnings=warnings,
        )

    def _score_latency_quality(
        self,
        provider_stats: list[dict[str, Any]],
        total_events: int,
    ) -> QualityDimension:
        observations = []
        warnings = []
        score = 1.0

        zero_latency = [
            p.get("provider", "?") for p in provider_stats
            if (p.get("avg_latency_ms") or 0) == 0 and (p.get("total_events") or 0) > 5
        ]
        if zero_latency:
            warnings.append(
                f"Provider(s) {zero_latency} show zero average latency — "
                "latency_ms may not be measured correctly."
            )
            score -= 0.40 * (len(zero_latency) / max(len(provider_stats), 1))

        if not warnings:
            observations.append("Latency appears to be captured consistently.")

        return QualityDimension(
            name="Latency Quality",
            score=max(0.0, score),
            observations=observations,
            warnings=warnings,
        )

    def _score_workflow_naming(
        self, workflow_stats: list[dict[str, Any]]
    ) -> QualityDimension:
        observations = []
        warnings = []
        score = 1.0

        if not workflow_stats:
            return QualityDimension(
                name="Workflow Naming",
                score=0.5,
                observations=["No workflow stats available — naming quality cannot be assessed."],
            )

        generic = [
            w.get("workflow", "") for w in workflow_stats
            if w.get("workflow", "").lower() in _GENERIC_WORKFLOW_NAMES
        ]
        if generic:
            frac = len(generic) / len(workflow_stats)
            score -= frac * 0.50
            warnings.append(
                f"{len(generic)} of {len(workflow_stats)} workflow(s) use generic names "
                f"({', '.join(generic[:3])}). "
                "Use descriptive names like 'api/summarize' or 'celery/tasks/process'."
            )

        flat_names = [
            w.get("workflow", "") for w in workflow_stats
            if len(_WORKFLOW_SEPARATOR_RE.split(w.get("workflow", ""))) < _MIN_WORKFLOW_SEGMENTS
            and w.get("workflow", "").lower() not in _GENERIC_WORKFLOW_NAMES
        ]
        if flat_names:
            score -= 0.20
            observations.append(
                f"{len(flat_names)} workflow name(s) appear flat (no namespace separator). "
                "Consider using 'context/workflow' format."
            )

        raw_names = [
            w.get("workflow", "") for w in workflow_stats
            if w.get("workflow", "").lower() in _RAW_PROVIDER_NAMES
        ]
        if raw_names:
            score -= 0.15
            warnings.append(
                f"Workflow name(s) appear to be HTTP library names: {raw_names}. "
                "These should be logical operation names."
            )

        if not warnings and not observations:
            observations.append("Workflow names appear meaningful and well-structured.")

        return QualityDimension(
            name="Workflow Naming",
            score=max(0.0, score),
            observations=observations,
            warnings=warnings,
        )

    def _score_error_coverage(
        self, total_failures: int, events_with_error_type: int
    ) -> QualityDimension:
        if total_failures == 0:
            return QualityDimension(
                name="Error Coverage",
                score=1.0,
                observations=["No failures recorded — error type coverage is not applicable."],
            )

        coverage = events_with_error_type / total_failures if total_failures > 0 else 0.0
        uncategorized = total_failures - events_with_error_type

        if coverage >= 0.90:
            return QualityDimension(
                name="Error Coverage",
                score=1.0,
                observations=[
                    f"{coverage:.0%} of failures have error_type set — good error coverage."
                ],
            )

        score = coverage
        warnings = []
        if uncategorized > 0:
            warnings.append(
                f"{uncategorized} failed event(s) have no error_type — "
                "classify errors as: rate_limit, timeout, context_length, authentication, etc."
            )

        return QualityDimension(
            name="Error Coverage",
            score=max(0.0, score),
            observations=[f"{total_failures} total failures; {coverage:.0%} have error_type."],
            warnings=warnings,
        )

    def _score_metadata_utilization(
        self, events_with_metadata: int, total_events: int
    ) -> QualityDimension:
        if total_events == 0:
            return QualityDimension(name="Metadata Utilization", score=0.5)

        ratio = events_with_metadata / total_events
        observations = []

        if ratio < 0.10:
            observations.append(
                f"Only {ratio:.0%} of events have metadata — "
                "consider adding operational context (env, task_name, endpoint)."
            )
            score = 0.3
        elif ratio < 0.50:
            observations.append(
                f"{ratio:.0%} of events have metadata — "
                "moderate metadata utilization."
            )
            score = 0.7
        else:
            observations.append(f"{ratio:.0%} of events include metadata — good coverage.")
            score = 1.0

        return QualityDimension(
            name="Metadata Utilization",
            score=score,
            observations=observations,
        )

    # ------------------------------------------------------------------
    # Warnings and suggestions
    # ------------------------------------------------------------------

    def _build_warnings(self, dimensions: list[QualityDimension]) -> list[str]:
        warnings: list[str] = []
        for d in dimensions:
            warnings.extend(d.warnings)
        return warnings

    def _build_suggestions(
        self, dimensions: list[QualityDimension], score: float
    ) -> list[str]:
        suggestions: list[str] = []
        lowest = sorted(dimensions, key=lambda d: d.score)[:3]
        for d in lowest:
            if d.score < 0.70:
                suggestions.append(
                    f"Improve **{d.name}** (current: {d.score:.2f}) — "
                    + (d.observations[0] if d.observations else "see dimension details")
                )
        if not suggestions:
            suggestions.append(
                "Ingestion quality appears good. Continue current instrumentation practices."
            )
        return suggestions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_band(score: float) -> str:
    if score < 0.40:
        return "poor"
    if score < 0.70:
        return "fair"
    if score < 0.90:
        return "good"
    return "excellent"


def _empty_report() -> IngestionQualityReport:
    from datetime import UTC, datetime
    return IngestionQualityReport(
        quality_score=0.0,
        quality_band="poor",
        total_events_assessed=0,
        dimensions=[],
        integration_warnings=["No LLM events have been ingested yet."],
        improvement_suggestions=[
            "Instrument your LLM call sites using the SDK or adapters in integrations/adapters/."
        ],
        generated_at=datetime.now(UTC).isoformat(),
    )
