"""
Operational priority engine — rank what matters most.

Takes recommendations, cost observations, workflows, and temporal analysis
and produces a priority-ranked list of operational insights.

Scoring is deterministic and explainable:
- base score: recommendation confidence × impact weight
- volatility bonus: if related component is churning
- cost bonus: if category is cost-related or cost tier is high
- recurrence bonus: if the component appeared multiple times in temporal window

All output is advisory. No autonomous action implied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognition.temporal_analysis import TemporalAnalysis

logger = logging.getLogger(__name__)

_IMPACT_WEIGHTS = {"high": 1.0, "medium": 0.65, "low": 0.35}
_URGENCY_THRESHOLDS = [
    (0.80, "critical"),
    (0.60, "high"),
    (0.40, "medium"),
    (0.20, "low"),
]


@dataclass
class PriorityItem:
    """A single ranked operational insight."""
    rank: int
    urgency: str  # "critical", "high", "medium", "low", "informational"
    priority_score: float  # 0.0-1.0
    title: str
    summary: str
    category: str
    evidence: list[str]
    reasoning: list[str]  # explains what drove the score

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "urgency": self.urgency,
            "priority_score": round(self.priority_score, 3),
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "evidence": self.evidence,
            "reasoning": self.reasoning,
        }


class PrioritizationEngine:
    """Produces a priority-ranked list of operational insights.

    Priority = f(confidence, impact, volatility, cost risk, recurrence).
    All factors are weighted explicitly. Scoring is deterministic.
    """

    VOLATILITY_BONUS = 0.15
    COST_BONUS = 0.10
    RECURRENCE_BONUS = 0.10
    MAX_VOLATILITY_BONUS = 0.25

    def rank(
        self,
        recommendations: list[dict[str, Any]],
        cost_observations: list[dict[str, Any]],
        workflows: list[dict[str, Any]],
        temporal: TemporalAnalysis | None = None,
    ) -> list[PriorityItem]:
        items: list[PriorityItem] = []

        for rec in recommendations:
            score, reasoning = self._score_recommendation(rec, temporal)
            items.append(PriorityItem(
                rank=0,
                urgency=_urgency(score),
                priority_score=score,
                title=rec.get("title", ""),
                summary=rec.get("observation", ""),
                category=rec.get("category", "general"),
                evidence=rec.get("evidence", []),
                reasoning=reasoning,
            ))

        for obs in cost_observations:
            if obs.get("severity") == "high":
                score, reasoning = self._score_cost_observation(obs, temporal)
                items.append(PriorityItem(
                    rank=0,
                    urgency=_urgency(score),
                    priority_score=score,
                    title=f"Cost risk: {obs.get('observation', '')[:70]}",
                    summary=obs.get("observation", ""),
                    category="cost",
                    evidence=obs.get("evidence", []),
                    reasoning=reasoning,
                ))

        if temporal and temporal.churning_components:
            for churn in temporal.churning_components[:3]:
                score = min(0.40 + churn.change_count * 0.10, 0.80)
                items.append(PriorityItem(
                    rank=0,
                    urgency=_urgency(score),
                    priority_score=score,
                    title=f"Volatility: '{churn.component}' changed {churn.change_count} times",
                    summary=(
                        f"The component '{churn.component}' changed {churn.change_count} times "
                        f"in the temporal window — indicating instability or active migration."
                    ),
                    category="stability",
                    evidence=[f"Change types: {', '.join(churn.change_types)}"],
                    reasoning=[
                        f"base score from churn count: {churn.change_count} changes",
                        "elevated to stability concern automatically",
                    ],
                ))

        items.sort(key=lambda x: -x.priority_score)

        for i, item in enumerate(items, 1):
            item.rank = i

        logger.info(
            "Prioritization complete",
            extra={"item_count": len(items)},
        )
        return items

    def _score_recommendation(
        self,
        rec: dict[str, Any],
        temporal: TemporalAnalysis | None,
    ) -> tuple[float, list[str]]:
        confidence = float(rec.get("confidence", 0.5))
        impact = rec.get("impact", "low")
        impact_weight = _IMPACT_WEIGHTS.get(impact, 0.35)
        base = confidence * impact_weight
        reasoning = [
            f"base: confidence {confidence:.2f} × impact weight {impact_weight:.2f} = {base:.3f}"
        ]

        volatility_bonus = 0.0
        if temporal and temporal.churning_components:
            evidence_text = " ".join(rec.get("evidence", [])).lower()
            for churn in temporal.churning_components:
                if churn.component.lower() in evidence_text:
                    volatility_bonus = min(
                        self.VOLATILITY_BONUS * churn.change_count,
                        self.MAX_VOLATILITY_BONUS,
                    )
                    reasoning.append(
                        f"volatility bonus +{volatility_bonus:.3f}: "
                        f"'{churn.component}' churned {churn.change_count}× in window"
                    )
                    break

        cost_bonus = 0.0
        if rec.get("category") == "cost":
            cost_bonus = self.COST_BONUS
            reasoning.append(f"cost category bonus +{cost_bonus:.3f}")

        recurrence_bonus = 0.0
        if rec.get("recurrence_count", 0) > 0:
            recurrence_bonus = self.RECURRENCE_BONUS
            reasoning.append(f"recurrence bonus +{recurrence_bonus:.3f}: pattern repeated historically")

        score = min(base + volatility_bonus + cost_bonus + recurrence_bonus, 1.0)
        return round(score, 3), reasoning

    def _score_cost_observation(
        self,
        obs: dict[str, Any],
        temporal: TemporalAnalysis | None,
    ) -> tuple[float, list[str]]:
        severity_base = {"high": 0.75, "warning": 0.55, "info": 0.30}.get(
            obs.get("severity", "info"), 0.30
        )
        reasoning = [f"severity base: {obs.get('severity', 'info')} → {severity_base:.2f}"]

        tier_bonus = 0.10 if obs.get("estimated_tier") == "high" else 0.0
        if tier_bonus:
            reasoning.append(f"high cost tier bonus +{tier_bonus:.2f}")

        score = min(severity_base + tier_bonus, 1.0)
        return round(score, 3), reasoning


def _urgency(score: float) -> str:
    for threshold, label in _URGENCY_THRESHOLDS:
        if score >= threshold:
            return label
    return "informational"
