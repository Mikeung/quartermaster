"""
Attention guidance layer — reduce operator cognitive overload.

Takes all intelligence outputs and answers: "What should the operator
care about FIRST?"

Filters, compresses, and surfaces:
- top operational concerns (overall)
- cost concerns
- stability/volatility concerns
- drift concerns
- runtime concerns

Suppresses low-signal items so operators are not overwhelmed.

All output is advisory. Deterministic. Evidence-backed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cognition.prioritization import PriorityItem
from cognition.runtime_health import RuntimeHealthReport
from cognition.temporal_analysis import TemporalAnalysis

logger = logging.getLogger(__name__)

_MIN_SCORE_FOR_ATTENTION = 0.35
_MAX_TOP_CONCERNS = 5
_MAX_PER_CATEGORY = 3


@dataclass
class AttentionItem:
    """A single surfaced concern for operator attention."""
    title: str
    summary: str
    evidence: list[str]
    urgency: str  # "critical", "high", "medium", "low"
    category: str
    priority_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "evidence": self.evidence,
            "urgency": self.urgency,
            "category": self.category,
            "priority_score": round(self.priority_score, 3),
        }


@dataclass
class AttentionReport:
    """Compressed operational attention guidance.

    Surfaces the most important concerns across categories.
    Suppresses low-value items to reduce noise.
    """
    top_concerns: list[AttentionItem]
    cost_concerns: list[AttentionItem]
    stability_concerns: list[AttentionItem]
    drift_concerns: list[AttentionItem]
    runtime_concerns: list[AttentionItem]
    suppressed_count: int
    attention_summary: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_concerns": [i.to_dict() for i in self.top_concerns],
            "cost_concerns": [i.to_dict() for i in self.cost_concerns],
            "stability_concerns": [i.to_dict() for i in self.stability_concerns],
            "drift_concerns": [i.to_dict() for i in self.drift_concerns],
            "runtime_concerns": [i.to_dict() for i in self.runtime_concerns],
            "suppressed_count": self.suppressed_count,
            "attention_summary": self.attention_summary,
            "generated_at": self.generated_at,
        }


class AttentionGuidance:
    """Generates a compressed attention report from all intelligence outputs.

    Applies score thresholds and category caps to prevent information overload.
    """

    def generate(
        self,
        priority_items: list[PriorityItem],
        temporal: TemporalAnalysis | None = None,
        cost_observations: list[dict[str, Any]] | None = None,
        runtime_health: RuntimeHealthReport | None = None,
    ) -> AttentionReport:
        all_items = [_to_attention(p) for p in priority_items]

        above_threshold = [i for i in all_items if i.priority_score >= _MIN_SCORE_FOR_ATTENTION]
        suppressed_count = len(all_items) - len(above_threshold)

        top_concerns = above_threshold[:_MAX_TOP_CONCERNS]

        cost_concerns = [
            i for i in above_threshold if i.category == "cost"
        ][:_MAX_PER_CATEGORY]

        stability_concerns = [
            i for i in above_threshold if i.category == "stability"
        ][:_MAX_PER_CATEGORY]

        # Drift concerns from temporal analysis
        drift_concerns: list[AttentionItem] = []
        if temporal:
            for indicator in temporal.churn_indicators[:_MAX_PER_CATEGORY]:
                if "stable" in indicator.lower() or "insufficient" in indicator.lower():
                    continue
                drift_concerns.append(AttentionItem(
                    title="Operational drift detected",
                    summary=indicator,
                    evidence=temporal.trend_observations[:2],
                    urgency="medium" if temporal.volatility_score < 0.6 else "high",
                    category="drift",
                    priority_score=round(0.40 + temporal.volatility_score * 0.30, 3),
                ))

        # Runtime concerns from live health assessment
        runtime_concerns: list[AttentionItem] = []
        if runtime_health and runtime_health.overall_status != "unknown":
            runtime_concerns = _runtime_concerns_from_health(runtime_health)

        attention_summary = _build_summary(
            top_concerns, cost_concerns, stability_concerns, drift_concerns,
            suppressed_count, runtime_concerns,
        )

        logger.info(
            "Attention guidance generated",
            extra={
                "top_concerns": len(top_concerns),
                "runtime_concerns": len(runtime_concerns),
                "suppressed": suppressed_count,
            },
        )

        return AttentionReport(
            top_concerns=top_concerns,
            cost_concerns=cost_concerns,
            stability_concerns=stability_concerns,
            drift_concerns=drift_concerns,
            runtime_concerns=runtime_concerns,
            suppressed_count=suppressed_count,
            attention_summary=attention_summary,
            generated_at=datetime.now(UTC).isoformat(),
        )


def _to_attention(item: PriorityItem) -> AttentionItem:
    return AttentionItem(
        title=item.title,
        summary=item.summary,
        evidence=item.evidence,
        urgency=item.urgency,
        category=item.category,
        priority_score=item.priority_score,
    )


def _runtime_concerns_from_health(health: RuntimeHealthReport) -> list[AttentionItem]:
    """Extract runtime concerns from a health report as attention items."""
    concerns: list[AttentionItem] = []

    if health.overall_status in ("stressed", "critical"):
        urgency = "critical" if health.overall_status == "critical" else "high"
        concerns.append(AttentionItem(
            title=f"Runtime {health.overall_status}: {', '.join(health.resource_pressure[:2]) or 'resource pressure detected'}",
            summary=(
                f"Runtime health score {health.health_score:.2f} — "
                f"{health.overall_status} status detected."
            ),
            evidence=health.instability_signals[:3] + health.resource_pressure[:2],
            urgency=urgency,
            category="runtime",
            priority_score=round(1.0 - health.health_score, 3),
        ))

    for detail in health.docker_restart_details[:_MAX_PER_CATEGORY]:
        concerns.append(AttentionItem(
            title="Container restart loop detected",
            summary=detail,
            evidence=[detail, "Repeated restarts indicate instability or misconfiguration"],
            urgency="high",
            category="runtime",
            priority_score=0.65,
        ))

    if health.failed_services:
        concerns.append(AttentionItem(
            title=f"Failed services: {', '.join(health.failed_services[:3])}",
            summary=f"{len(health.failed_services)} service(s) in failed state.",
            evidence=[f"Failed: {', '.join(health.failed_services[:5])}"],
            urgency="high",
            category="runtime",
            priority_score=0.70,
        ))

    return concerns[:_MAX_PER_CATEGORY]


def _build_summary(
    top: list[AttentionItem],
    cost: list[AttentionItem],
    stability: list[AttentionItem],
    drift: list[AttentionItem],
    suppressed: int,
    runtime: list[AttentionItem] | None = None,
) -> str:
    runtime = runtime or []
    if not top and not drift and not runtime:
        return "No significant operational concerns detected. System appears stable."

    parts: list[str] = []

    critical = [i for i in top if i.urgency == "critical"]
    if critical:
        parts.append(f"{len(critical)} critical concern(s) require immediate attention")

    high = [i for i in top if i.urgency == "high"]
    if high:
        parts.append(f"{len(high)} high-priority concern(s) should be reviewed soon")

    if cost:
        parts.append(f"{len(cost)} cost risk(s) identified")

    if drift:
        parts.append(f"{len(drift)} operational drift indicator(s) detected")

    if runtime:
        runtime_critical = [r for r in runtime if r.urgency == "critical"]
        if runtime_critical:
            parts.append(f"{len(runtime_critical)} critical runtime issue(s) detected")
        elif runtime:
            parts.append(f"{len(runtime)} runtime concern(s) require attention")

    if suppressed > 0:
        parts.append(f"{suppressed} low-signal item(s) suppressed")

    return ". ".join(parts) + "." if parts else "Operational status requires review."
