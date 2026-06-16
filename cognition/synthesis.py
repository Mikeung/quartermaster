"""
Ecosystem synthesis engine — generate ecosystem-level operational understanding.

Answers:
- what themes dominate the ecosystem?
- what operational patterns recur most?
- where is complexity accumulating?
- what kinds of instability are increasing?
- which workflows dominate operational risk?
- where are LLM costs concentrating?
- which concerns appear systemic rather than isolated?

Inputs: recommendations, recurrence, runtime health, temporal, patterns, topology.
Output: EcosystemSummary containing OperationalTheme, SystemicConcern, EcosystemTrend.

IMPORTANT:
- Deterministic only
- Evidence-backed only
- No speculative reasoning
- Bounded synthesis — every claim cites its inputs

Advisory only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cognition.heuristics import HeuristicRegistry

logger = logging.getLogger(__name__)

_HEURISTICS = HeuristicRegistry()

# ---------------------------------------------------------------------------
# Theme definitions — operational groupings of related signals
# ---------------------------------------------------------------------------

_THEME_COST_ACCUMULATION = "cost_accumulation"
_THEME_ORCHESTRATION_COMPLEXITY = "orchestration_complexity"
_THEME_RUNTIME_INSTABILITY = "runtime_instability"
_THEME_PROVIDER_FRAGMENTATION = "provider_fragmentation"
_THEME_LLM_COST_RISK = "llm_cost_risk"


@dataclass
class OperationalTheme:
    """A named cluster of related operational signals that appears ecosystem-wide."""
    name: str
    label: str
    description: str
    contributing_patterns: list[str]
    contributing_categories: list[str]   # recommendation categories
    evidence: list[str]
    severity_hint: str
    prevalence: float                    # 0.0-1.0 — fraction of total signals

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "contributing_patterns": self.contributing_patterns,
            "contributing_categories": self.contributing_categories,
            "evidence": self.evidence,
            "severity_hint": self.severity_hint,
            "prevalence": round(self.prevalence, 3),
        }


@dataclass
class SystemicConcern:
    """A concern that appears cross-cutting — present across multiple themes."""
    title: str
    description: str
    contributing_themes: list[str]
    evidence: list[str]
    severity: str
    systemic: bool = True   # always True; field preserved for clarity

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "contributing_themes": self.contributing_themes,
            "evidence": self.evidence,
            "severity": self.severity,
            "systemic": self.systemic,
        }


@dataclass
class EcosystemTrend:
    """A directional observation about how one ecosystem dimension is changing."""
    dimension: str      # "complexity", "instability", "cost_risk", "provider_fragmentation"
    direction: str      # "increasing", "decreasing", "stable"
    score: float        # current score 0-1
    evidence: list[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "direction": self.direction,
            "score": round(self.score, 3),
            "evidence": self.evidence,
            "note": self.note,
        }


@dataclass
class EcosystemSummary:
    """Ecosystem-level operational synthesis.

    Represents bounded, evidence-backed understanding of what themes,
    concerns, and trends currently dominate the observed AI ecosystem.

    Advisory only. Not a prediction. Not a diagnosis.
    """
    themes: list[OperationalTheme]
    systemic_concerns: list[SystemicConcern]
    trends: list[EcosystemTrend]
    dominant_theme: str | None
    overall_health: str          # "stable", "degrading", "improving", "critical"
    evidence_count: int
    confidence: float
    generated_at: str
    snapshot_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "themes": [t.to_dict() for t in self.themes],
            "systemic_concerns": [c.to_dict() for c in self.systemic_concerns],
            "trends": [t.to_dict() for t in self.trends],
            "dominant_theme": self.dominant_theme,
            "overall_health": self.overall_health,
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 3),
            "generated_at": self.generated_at,
            "snapshot_count": self.snapshot_count,
            "advisory": "Synthesis reflects observed structure — not live runtime behavior unless runtime data was provided.",
        }


class EcosystemSynthesisEngine:
    """Generates ecosystem-level operational understanding from aggregated signals.

    Deterministic. Evidence-backed. No speculative reasoning.
    """

    def synthesize(
        self,
        snapshots: list[dict[str, Any]],
        patterns: list[dict[str, Any]] | None = None,
        recurring_issues: list[dict[str, Any]] | None = None,
        runtime_health: dict[str, Any] | None = None,
        temporal: dict[str, Any] | None = None,
    ) -> EcosystemSummary:
        """Generate an ecosystem-level summary from available intelligence.

        snapshots: list of snapshot dicts (any order)
        patterns: list of serialized OperationalPattern dicts (matched + unmatched)
        recurring_issues: list of serialized RecurringIssue dicts
        runtime_health: serialized RuntimeHealthReport dict
        temporal: serialized TemporalAnalysis dict
        """
        if not snapshots:
            return self._empty_summary()

        matched_patterns = [p for p in (patterns or []) if p.get("matched")]
        pattern_names = {p["name"] for p in matched_patterns}
        all_recs = _aggregate_recommendations(snapshots)
        rec_categories = _count_by_category(all_recs)
        total_signals = len(matched_patterns) + len(all_recs) + len(recurring_issues or [])

        themes = self._extract_themes(
            matched_patterns=matched_patterns,
            pattern_names=pattern_names,
            rec_categories=rec_categories,
            recurring_issues=recurring_issues or [],
            runtime_health=runtime_health or {},
            temporal=temporal or {},
            total_signals=max(total_signals, 1),
            snapshots=snapshots,
        )

        trends = self._extract_trends(
            temporal=temporal or {},
            runtime_health=runtime_health or {},
            matched_patterns=matched_patterns,
            rec_categories=rec_categories,
        )

        systemic_concerns = self._detect_systemic(themes)
        dominant_theme = self._dominant_theme(themes)
        overall_health = self._overall_health(themes, runtime_health or {}, temporal or {})
        confidence = self._confidence(snapshots, matched_patterns, runtime_health, temporal)

        logger.info(
            "Ecosystem synthesis complete",
            extra={
                "snapshot_count": len(snapshots),
                "themes_detected": len(themes),
                "systemic_concerns": len(systemic_concerns),
                "dominant_theme": dominant_theme,
            },
        )

        return EcosystemSummary(
            themes=themes,
            systemic_concerns=systemic_concerns,
            trends=trends,
            dominant_theme=dominant_theme,
            overall_health=overall_health,
            evidence_count=total_signals,
            confidence=confidence,
            generated_at=_now(),
            snapshot_count=len(snapshots),
        )

    def _extract_themes(
        self,
        matched_patterns: list[dict],
        pattern_names: set[str],
        rec_categories: dict[str, int],
        recurring_issues: list[dict],
        runtime_health: dict,
        temporal: dict,
        total_signals: int,
        snapshots: list[dict] | None = None,
    ) -> list[OperationalTheme]:
        themes: list[OperationalTheme] = []
        min_evidence = _HEURISTICS.threshold("theme_minimum_evidence")

        # --- LLM cost risk theme ---
        cost_risk_patterns = pattern_names & {
            "retry_amplification", "ocr_token_amplification", "cost_blind_rag"
        }
        cost_risk_cats = _categories_matching(rec_categories, {"cost", "llm", "token"})
        cost_risk_recurring = [
            r for r in recurring_issues
            if "cost" in r.get("pattern", "").lower() or r.get("kind") == "cost_warning"
        ]
        cost_evidence: list[str] = []
        if cost_risk_patterns:
            cost_evidence.append(f"Matched cost-risk patterns: {', '.join(sorted(cost_risk_patterns))}")
        if cost_risk_cats:
            cost_evidence.append(f"Cost-related recommendation categories: {', '.join(sorted(cost_risk_cats))}")
        if cost_risk_recurring:
            cost_evidence.append(f"{len(cost_risk_recurring)} recurring cost warning(s)")
        if len(cost_evidence) >= min_evidence:
            themes.append(OperationalTheme(
                name=_THEME_LLM_COST_RISK,
                label="LLM Cost Risk",
                description="Structural patterns that correlate with elevated or unpredictable LLM token costs",
                contributing_patterns=sorted(cost_risk_patterns),
                contributing_categories=sorted(cost_risk_cats),
                evidence=cost_evidence[:5],
                severity_hint=_theme_severity(cost_risk_patterns, cost_risk_recurring, rec_categories),
                prevalence=_prevalence(len(cost_evidence), total_signals),
            ))

        # --- Orchestration complexity theme ---
        orch_patterns = pattern_names & {
            "framework_stacking", "orchestration_sprawl", "excessive_multi_agent_layering"
        }
        orch_cats = _categories_matching(rec_categories, {"orchestration", "workflow", "agent"})
        orch_evidence: list[str] = []
        if orch_patterns:
            orch_evidence.append(f"Orchestration complexity patterns: {', '.join(sorted(orch_patterns))}")
        if orch_cats:
            orch_evidence.append(f"Orchestration-related recommendations in {', '.join(sorted(orch_cats))}")
        orch_workflows = _extract_dominant_workflows([], ["multi_agent_orchestration", "agent_pipeline"])
        if orch_workflows:
            orch_evidence.append("Multi-agent workflow patterns detected")
        if len(orch_evidence) >= min_evidence:
            themes.append(OperationalTheme(
                name=_THEME_ORCHESTRATION_COMPLEXITY,
                label="Orchestration Complexity",
                description="Accumulating orchestration framework depth and multi-agent layering",
                contributing_patterns=sorted(orch_patterns),
                contributing_categories=sorted(orch_cats),
                evidence=orch_evidence[:5],
                severity_hint="high" if len(orch_patterns) >= 2 else "moderate",
                prevalence=_prevalence(len(orch_evidence), total_signals),
            ))

        # --- Runtime instability theme ---
        rt_status = runtime_health.get("overall_status", "")
        rt_score = runtime_health.get("health_score", 1.0)
        rt_signals = runtime_health.get("instability_signals", [])
        rt_patterns = pattern_names & {"unstable_worker_pattern"}
        rt_recurring = [r for r in recurring_issues if r.get("kind") == "runtime_failure"]
        rt_evidence: list[str] = []
        if rt_status in ("degraded", "critical"):
            rt_evidence.append(f"Runtime health: {rt_status} (score {rt_score:.2f})")
        if rt_signals:
            rt_evidence.append(f"{len(rt_signals)} instability signal(s): {', '.join(rt_signals[:2])}")
        if rt_recurring:
            rt_evidence.append(f"{len(rt_recurring)} recurring runtime failure(s)")
        if rt_patterns:
            rt_evidence.append("Unstable worker pattern matched")
        volatility = temporal.get("volatility_score", 0.0)
        if volatility >= _HEURISTICS.threshold("moderate_volatility_threshold"):
            rt_evidence.append(f"Infrastructure volatility: {volatility:.2f}")
        if len(rt_evidence) >= min_evidence:
            themes.append(OperationalTheme(
                name=_THEME_RUNTIME_INSTABILITY,
                label="Runtime Instability",
                description="Degraded runtime health, recurring failures, or infrastructure churn",
                contributing_patterns=sorted(rt_patterns),
                contributing_categories=["stability", "reliability"],
                evidence=rt_evidence[:5],
                severity_hint="high" if rt_status == "critical" or rt_score < 0.40 else "moderate",
                prevalence=_prevalence(len(rt_evidence), total_signals),
            ))

        # --- Provider fragmentation theme ---
        prov_patterns = pattern_names & {
            "volatile_provider_switching", "single_provider_dependency"
        }
        prov_cats = _categories_matching(rec_categories, {"provider", "llm", "routing"})
        prov_evidence: list[str] = []
        if prov_patterns:
            prov_evidence.append(f"Provider risk patterns: {', '.join(sorted(prov_patterns))}")
        if prov_cats:
            prov_evidence.append(f"Provider-related recommendations in {', '.join(sorted(prov_cats))}")
        if len(prov_evidence) >= min_evidence:
            themes.append(OperationalTheme(
                name=_THEME_PROVIDER_FRAGMENTATION,
                label="Provider Fragmentation",
                description="Structural risks from LLM provider dependency or switching volatility",
                contributing_patterns=sorted(prov_patterns),
                contributing_categories=sorted(prov_cats),
                evidence=prov_evidence[:5],
                severity_hint="high" if "volatile_provider_switching" in prov_patterns else "moderate",
                prevalence=_prevalence(len(prov_evidence), total_signals),
            ))

        # --- Cost accumulation theme ---
        cost_obs_recs = _categories_matching(rec_categories, {"cost", "budget", "spending"})
        rec_recurring = [
            r for r in recurring_issues
            if r.get("kind") == "recommendation" and "cost" in r.get("pattern", "").lower()
        ]
        cost_acc_evidence: list[str] = []
        if cost_obs_recs:
            cost_acc_evidence.append(
                f"{sum(rec_categories.get(c, 0) for c in cost_obs_recs)} cost-related recommendation(s) "
                f"in {', '.join(sorted(cost_obs_recs))}"
            )
        if rec_recurring:
            cost_acc_evidence.append(
                f"{len(rec_recurring)} cost recommendation(s) recurring across multiple scans"
            )
        cost_high_obs = _count_high_cost_obs(snapshots or [])
        if cost_high_obs >= 2:
            cost_acc_evidence.append(f"{cost_high_obs} high-severity cost observation(s) aggregated across scans")
        if len(cost_acc_evidence) >= min_evidence:
            themes.append(OperationalTheme(
                name=_THEME_COST_ACCUMULATION,
                label="Cost Accumulation",
                description="Persistent cost concerns accumulating without resolution across scans",
                contributing_patterns=[],
                contributing_categories=sorted(cost_obs_recs),
                evidence=cost_acc_evidence[:5],
                severity_hint="high" if cost_high_obs >= 4 else "moderate",
                prevalence=_prevalence(len(cost_acc_evidence), total_signals),
            ))

        return sorted(themes, key=lambda t: -t.prevalence)

    def _extract_trends(
        self,
        temporal: dict,
        runtime_health: dict,
        matched_patterns: list[dict],
        rec_categories: dict[str, int],
    ) -> list[EcosystemTrend]:
        trends: list[EcosystemTrend] = []

        # Complexity trend — based on matched orchestration patterns
        orch_pattern_count = sum(
            1 for p in matched_patterns
            if p.get("name") in {"framework_stacking", "orchestration_sprawl", "excessive_multi_agent_layering"}
        )
        complexity_score = min(orch_pattern_count / 3.0, 1.0)
        trends.append(EcosystemTrend(
            dimension="orchestration_complexity",
            direction="increasing" if complexity_score >= 0.33 else "stable",
            score=complexity_score,
            evidence=[f"{orch_pattern_count} orchestration complexity pattern(s) matched"] if orch_pattern_count else [],
            note="Complexity measured by matched orchestration risk patterns",
        ))

        # Runtime stability trend — from runtime health score
        rt_score = runtime_health.get("health_score", 1.0) if runtime_health else 1.0
        rt_status = runtime_health.get("overall_status", "unknown") if runtime_health else "unknown"
        trends.append(EcosystemTrend(
            dimension="runtime_stability",
            direction="decreasing" if rt_score < 0.6 else ("stable" if rt_score >= 0.8 else "degrading"),
            score=rt_score,
            evidence=[f"Runtime health score: {rt_score:.2f} ({rt_status})"] if runtime_health else ["No runtime data available"],
            note="Runtime stability from most recent runtime health assessment",
        ))

        # Cost risk trend — from pattern matches + cost observation count
        cost_patterns = sum(
            1 for p in matched_patterns
            if p.get("name") in {"retry_amplification", "ocr_token_amplification", "cost_blind_rag"}
        )
        cost_score = min(cost_patterns / 3.0, 1.0)
        trends.append(EcosystemTrend(
            dimension="llm_cost_risk",
            direction="increasing" if cost_score >= 0.33 else "stable",
            score=cost_score,
            evidence=[f"{cost_patterns} LLM cost-risk pattern(s) matched"] if cost_patterns else [],
            note="Cost risk measured by matched cost-amplification patterns",
        ))

        # Infrastructure volatility trend
        vol = temporal.get("volatility_score", 0.0) if temporal else 0.0
        churn = temporal.get("churn_indicators", []) if temporal else []
        trends.append(EcosystemTrend(
            dimension="infrastructure_volatility",
            direction="increasing" if vol >= _HEURISTICS.threshold("high_volatility_threshold") else (
                "stable" if vol < _HEURISTICS.threshold("moderate_volatility_threshold") else "moderate"
            ),
            score=vol,
            evidence=[f"Volatility score: {vol:.2f}", *churn[:2]] if temporal else ["No temporal data available"],
            note="Volatility from temporal change frequency analysis",
        ))

        return trends

    def _detect_systemic(
        self, themes: list[OperationalTheme]
    ) -> list[SystemicConcern]:
        """Detect concerns that appear across 2+ themes — genuinely systemic."""
        if len(themes) < 2:
            return []

        concerns: list[SystemicConcern] = []
        theme_names = {t.name for t in themes}

        # LLM cost + orchestration complexity both active → compounding cost risk
        if {_THEME_LLM_COST_RISK, _THEME_ORCHESTRATION_COMPLEXITY} <= theme_names:
            concerns.append(SystemicConcern(
                title="Compounding LLM cost through orchestration depth",
                description=(
                    "LLM cost-risk patterns co-occur with orchestration complexity. "
                    "Each orchestration layer may amplify token consumption from underlying LLM calls."
                ),
                contributing_themes=[_THEME_LLM_COST_RISK, _THEME_ORCHESTRATION_COMPLEXITY],
                evidence=[
                    "Both LLM cost-risk and orchestration complexity themes are active",
                    "Multi-layer orchestration correlates with retry/amplification risk",
                ],
                severity="high",
            ))

        # Runtime instability + orchestration complexity both active → unstable orchestration
        if {_THEME_RUNTIME_INSTABILITY, _THEME_ORCHESTRATION_COMPLEXITY} <= theme_names:
            concerns.append(SystemicConcern(
                title="Unstable orchestration infrastructure",
                description=(
                    "Runtime instability co-occurs with orchestration complexity. "
                    "Complex orchestration under degraded runtime conditions correlates with "
                    "task loss, retry storms, and unpredictable throughput."
                ),
                contributing_themes=[_THEME_RUNTIME_INSTABILITY, _THEME_ORCHESTRATION_COMPLEXITY],
                evidence=[
                    "Runtime instability and orchestration complexity themes both active",
                    "Orchestration frameworks running under degraded runtime conditions",
                ],
                severity="high",
            ))

        # Provider fragmentation + LLM cost risk → fragile cost structure
        if {_THEME_PROVIDER_FRAGMENTATION, _THEME_LLM_COST_RISK} <= theme_names:
            concerns.append(SystemicConcern(
                title="Fragile LLM cost structure",
                description=(
                    "Provider fragmentation risk co-occurs with LLM cost risk. "
                    "Cost amplification patterns are more impactful when provider switching is "
                    "structurally constrained or uncontrolled."
                ),
                contributing_themes=[_THEME_PROVIDER_FRAGMENTATION, _THEME_LLM_COST_RISK],
                evidence=[
                    "Provider fragmentation and LLM cost-risk themes both active",
                    "Cost risk exposure concentrates on provider dependency structure",
                ],
                severity="moderate",
            ))

        # Cost accumulation + any runtime problem → neglected ecosystem
        if {_THEME_COST_ACCUMULATION, _THEME_RUNTIME_INSTABILITY} <= theme_names:
            concerns.append(SystemicConcern(
                title="Unresolved cost concerns under runtime pressure",
                description=(
                    "Persistent cost concerns are accumulating while runtime health is degraded. "
                    "These concerns have historically been observed together in ecosystems "
                    "with limited operational bandwidth."
                ),
                contributing_themes=[_THEME_COST_ACCUMULATION, _THEME_RUNTIME_INSTABILITY],
                evidence=[
                    "Both cost accumulation and runtime instability themes are active",
                    "Unresolved recommendations persisting under degraded runtime",
                ],
                severity="moderate",
            ))

        return concerns

    def _dominant_theme(self, themes: list[OperationalTheme]) -> str | None:
        if not themes:
            return None
        top = themes[0]
        if top.prevalence >= _HEURISTICS.threshold("dominant_theme_prevalence"):
            return top.name
        return top.name if themes else None

    def _overall_health(
        self, themes: list[OperationalTheme], runtime_health: dict, temporal: dict
    ) -> str:
        rt_score = runtime_health.get("health_score", 1.0) if runtime_health else 1.0
        high_themes = [t for t in themes if t.severity_hint == "high"]
        vol = temporal.get("volatility_score", 0.0) if temporal else 0.0

        if rt_score < 0.30 or len(high_themes) >= 3:
            return "critical"
        if rt_score < 0.60 or len(high_themes) >= 2:
            return "degrading"
        if len(high_themes) >= 1 or vol >= _HEURISTICS.threshold("high_volatility_threshold"):
            return "elevated"
        return "stable"

    def _confidence(
        self,
        snapshots: list[dict],
        matched_patterns: list[dict],
        runtime_health: dict | None,
        temporal: dict | None,
    ) -> float:
        score = 0.30  # base: have snapshots
        if len(snapshots) >= 3:
            score += 0.15
        if matched_patterns:
            score += 0.20
        if runtime_health and runtime_health.get("health_score") is not None:
            score += 0.20
        if temporal and temporal.get("volatility_score") is not None:
            score += 0.15
        return min(round(score, 3), 1.0)

    def _empty_summary(self) -> EcosystemSummary:
        return EcosystemSummary(
            themes=[],
            systemic_concerns=[],
            trends=[],
            dominant_theme=None,
            overall_health="unknown",
            evidence_count=0,
            confidence=0.0,
            generated_at=_now(),
            snapshot_count=0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aggregate_recommendations(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recs: list[dict] = []
    for snap in snapshots:
        recs.extend(snap.get("data", {}).get("recommendations", []))
    return recs


def _count_by_category(recs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in recs:
        cat = rec.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _categories_matching(counts: dict[str, int], keywords: set[str]) -> set[str]:
    return {
        cat for cat in counts
        if any(kw in cat.lower() for kw in keywords)
    }


def _count_high_cost_obs(snapshots: list[dict[str, Any]]) -> int:
    total = 0
    for snap in snapshots:
        obs_list = snap.get("data", {}).get("cost_observations", [])
        total += sum(1 for o in obs_list if o.get("severity") in ("high", "warning"))
    return total


def _prevalence(signal_count: int, total: int) -> float:
    return round(min(signal_count / max(total, 1), 1.0), 3)


def _extract_dominant_workflows(
    snapshots: list[dict[str, Any]], target_types: list[str]
) -> list[str]:
    found: set[str] = set()
    for snap in snapshots:
        for wf in snap.get("data", {}).get("workflows", []):
            if wf.get("workflow_type") in target_types:
                found.add(wf["workflow_type"])
    return list(found)


def _theme_severity(
    patterns: set[str], recurring: list[dict], rec_categories: dict[str, int]
) -> str:
    if len(patterns) >= 2 or len(recurring) >= 3:
        return "high"
    if patterns or recurring or sum(rec_categories.values()) >= 3:
        return "moderate"
    return "low"


def _now() -> str:
    return datetime.now(UTC).isoformat()
