"""
Systemic drift analysis — detect ecosystem-wide drift patterns across rolling windows.

Detects:
- increasing orchestration complexity
- growing framework diversity
- rising runtime instability
- expanding provider fragmentation
- increasing operational coupling
- worsening cost posture

Requirements:
- compare rolling windows (early third vs. recent third of snapshot history)
- trend-based only
- deterministic thresholds
- explainable scoring

NO predictions. NO future forecasting. Trends describe observed change, not projected change.

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


@dataclass
class DriftTrend:
    """A directional observation across two rolling windows of snapshot history."""
    dimension: str         # "orchestration_complexity", "provider_diversity", etc.
    direction: str         # "increasing", "decreasing", "stable"
    early_score: float     # score in early window
    recent_score: float    # score in recent window
    magnitude: float       # abs(recent - early), 0.0-1.0
    significant: bool      # magnitude >= drift_significant_magnitude threshold
    evidence: list[str]
    snapshot_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "direction": self.direction,
            "early_score": round(self.early_score, 3),
            "recent_score": round(self.recent_score, 3),
            "magnitude": round(self.magnitude, 3),
            "significant": self.significant,
            "evidence": self.evidence,
            "snapshot_count": self.snapshot_count,
        }


@dataclass
class EcosystemInstabilityIndicator:
    """A named instability signal detected across the snapshot window."""
    name: str
    active: bool
    score: float           # 0.0-1.0
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "active": self.active,
            "score": round(self.score, 3),
            "evidence": self.evidence,
        }


@dataclass
class OperationalComplexityTrend:
    """Tracks how operational complexity has changed across the snapshot window."""
    current_score: float
    previous_score: float
    delta: float
    direction: str          # "increasing", "decreasing", "stable"
    dimensions: list[str]   # which sub-dimensions drove the change
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_score": round(self.current_score, 3),
            "previous_score": round(self.previous_score, 3),
            "delta": round(self.delta, 3),
            "direction": self.direction,
            "dimensions": self.dimensions,
            "evidence": self.evidence,
        }


@dataclass
class SystemicDriftAnalysis:
    """Complete systemic drift analysis for an ecosystem snapshot window."""
    drift_trends: list[DriftTrend]
    instability_indicators: list[EcosystemInstabilityIndicator]
    complexity_trend: OperationalComplexityTrend
    overall_drift_score: float        # 0.0-1.0, aggregate drift magnitude
    significant_drift_count: int      # number of significant drift trends
    evidence: list[str]
    window_days: int
    snapshot_count: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_trends": [t.to_dict() for t in self.drift_trends],
            "instability_indicators": [i.to_dict() for i in self.instability_indicators],
            "complexity_trend": self.complexity_trend.to_dict(),
            "overall_drift_score": round(self.overall_drift_score, 3),
            "significant_drift_count": self.significant_drift_count,
            "evidence": self.evidence,
            "window_days": self.window_days,
            "snapshot_count": self.snapshot_count,
            "generated_at": self.generated_at,
            "advisory": "Trends describe observed historical change — not predicted future behavior.",
        }


class SystemicDriftEngine:
    """Detects ecosystem-wide drift patterns by comparing rolling snapshot windows.

    Splits snapshots into early (oldest third) and recent (newest third) windows.
    Computes scores for each dimension in each window, then derives direction and magnitude.

    Deterministic. Evidence-backed. No predictions.
    """

    def analyze(
        self,
        snapshots: list[dict[str, Any]],
        window_days: int = 30,
    ) -> SystemicDriftAnalysis:
        """Analyze systemic drift across the provided snapshots.

        Requires at least 2 snapshots. With fewer, returns a minimal analysis.
        """
        if len(snapshots) < 2:
            return self._empty_analysis(window_days)

        sorted_snaps = sorted(snapshots, key=lambda s: s.get("created_at", ""))
        early, recent = self._split_windows(sorted_snaps)

        drift_trends = [
            self._orchestration_complexity_trend(early, recent),
            self._provider_diversity_trend(early, recent),
            self._runtime_stability_trend(early, recent),
            self._recommendation_volume_trend(early, recent),
            self._cost_severity_trend(early, recent),
        ]

        indicators = self._instability_indicators(sorted_snaps, drift_trends)
        complexity = self._complexity_trend(early, recent, drift_trends)

        significant = [t for t in drift_trends if t.significant]
        overall = _aggregate_drift_score(drift_trends)

        top_evidence: list[str] = []
        for t in significant[:3]:
            top_evidence.append(
                f"{t.dimension}: {t.direction} (magnitude {t.magnitude:.2f})"
            )
        if not top_evidence:
            top_evidence.append("No significant drift detected across analyzed dimensions")

        logger.info(
            "Systemic drift analysis complete",
            extra={
                "snapshot_count": len(snapshots),
                "significant_drift_count": len(significant),
                "overall_drift_score": round(overall, 3),
            },
        )

        return SystemicDriftAnalysis(
            drift_trends=drift_trends,
            instability_indicators=indicators,
            complexity_trend=complexity,
            overall_drift_score=overall,
            significant_drift_count=len(significant),
            evidence=top_evidence,
            window_days=window_days,
            snapshot_count=len(snapshots),
            generated_at=_now(),
        )

    # ------------------------------------------------------------------
    # Drift trend builders
    # ------------------------------------------------------------------

    def _orchestration_complexity_trend(
        self, early: list[dict], recent: list[dict]
    ) -> DriftTrend:
        """Track how orchestration framework depth is changing."""
        early_score = _avg_orchestration_complexity(early)
        recent_score = _avg_orchestration_complexity(recent)
        mag = abs(recent_score - early_score)
        direction = _direction(early_score, recent_score)
        evidence: list[str] = []
        if direction != "stable":
            evidence.append(
                f"Orchestration complexity {direction}: "
                f"{early_score:.2f} (early) → {recent_score:.2f} (recent)"
            )
        return DriftTrend(
            dimension="orchestration_complexity",
            direction=direction,
            early_score=early_score,
            recent_score=recent_score,
            magnitude=mag,
            significant=mag >= _HEURISTICS.threshold("drift_significant_magnitude"),
            evidence=evidence,
            snapshot_count=len(early) + len(recent),
        )

    def _provider_diversity_trend(
        self, early: list[dict], recent: list[dict]
    ) -> DriftTrend:
        """Track LLM provider count diversity changes."""
        early_score = _avg_provider_count(early)
        recent_score = _avg_provider_count(recent)
        mag = abs(recent_score - early_score)
        direction = _direction(early_score, recent_score)
        evidence: list[str] = []
        if direction != "stable":
            evidence.append(
                f"Provider diversity {direction}: "
                f"{early_score:.2f} → {recent_score:.2f} (normalized)"
            )
        return DriftTrend(
            dimension="provider_diversity",
            direction=direction,
            early_score=early_score,
            recent_score=recent_score,
            magnitude=mag,
            significant=mag >= _HEURISTICS.threshold("drift_significant_magnitude"),
            evidence=evidence,
            snapshot_count=len(early) + len(recent),
        )

    def _runtime_stability_trend(
        self, early: list[dict], recent: list[dict]
    ) -> DriftTrend:
        """Track runtime health score changes — lower score = worse stability."""
        early_score = _avg_runtime_health(early)
        recent_score = _avg_runtime_health(recent)
        mag = abs(recent_score - early_score)
        direction = _direction(early_score, recent_score)
        # For runtime, "decreasing" stability score is the concern
        trend_direction = "decreasing" if direction == "decreasing" else direction
        evidence: list[str] = []
        if direction != "stable":
            evidence.append(
                f"Runtime stability {trend_direction}: "
                f"{early_score:.2f} → {recent_score:.2f}"
            )
        return DriftTrend(
            dimension="runtime_stability",
            direction=trend_direction,
            early_score=early_score,
            recent_score=recent_score,
            magnitude=mag,
            significant=mag >= _HEURISTICS.threshold("drift_significant_magnitude"),
            evidence=evidence,
            snapshot_count=len(early) + len(recent),
        )

    def _recommendation_volume_trend(
        self, early: list[dict], recent: list[dict]
    ) -> DriftTrend:
        """Track whether the recommendation load is growing or shrinking."""
        early_score = _avg_recommendation_count(early)
        recent_score = _avg_recommendation_count(recent)
        mag = abs(recent_score - early_score)
        direction = _direction(early_score, recent_score)
        evidence: list[str] = []
        if direction != "stable":
            evidence.append(
                f"Recommendation volume {direction}: "
                f"{early_score:.1f} → {recent_score:.1f} (avg per snapshot)"
            )
        return DriftTrend(
            dimension="recommendation_volume",
            direction=direction,
            early_score=early_score,
            recent_score=recent_score,
            magnitude=mag,
            significant=mag >= _HEURISTICS.threshold("drift_significant_magnitude"),
            evidence=evidence,
            snapshot_count=len(early) + len(recent),
        )

    def _cost_severity_trend(
        self, early: list[dict], recent: list[dict]
    ) -> DriftTrend:
        """Track whether high-severity cost observations are becoming more prevalent."""
        early_score = _avg_high_cost_ratio(early)
        recent_score = _avg_high_cost_ratio(recent)
        mag = abs(recent_score - early_score)
        direction = _direction(early_score, recent_score)
        evidence: list[str] = []
        if direction != "stable":
            evidence.append(
                f"Cost severity ratio {direction}: "
                f"{early_score:.2f} → {recent_score:.2f}"
            )
        return DriftTrend(
            dimension="cost_severity",
            direction=direction,
            early_score=early_score,
            recent_score=recent_score,
            magnitude=mag,
            significant=mag >= _HEURISTICS.threshold("drift_significant_magnitude"),
            evidence=evidence,
            snapshot_count=len(early) + len(recent),
        )

    # ------------------------------------------------------------------
    # Instability indicators
    # ------------------------------------------------------------------

    def _instability_indicators(
        self,
        snapshots: list[dict],
        trends: list[DriftTrend],
    ) -> list[EcosystemInstabilityIndicator]:
        indicators: list[EcosystemInstabilityIndicator] = []

        # Runtime degradation indicator
        rt_trend = next((t for t in trends if t.dimension == "runtime_stability"), None)
        if rt_trend:
            rt_score = rt_trend.recent_score
            indicators.append(EcosystemInstabilityIndicator(
                name="runtime_degradation",
                active=rt_score < 0.60,
                score=1.0 - rt_score,
                evidence=rt_trend.evidence or [f"Runtime health score: {rt_score:.2f}"],
            ))

        # Complexity accumulation indicator
        orch_trend = next((t for t in trends if t.dimension == "orchestration_complexity"), None)
        if orch_trend:
            indicators.append(EcosystemInstabilityIndicator(
                name="complexity_accumulation",
                active=orch_trend.recent_score >= _HEURISTICS.threshold("complexity_accumulation_threshold"),
                score=orch_trend.recent_score,
                evidence=orch_trend.evidence or [f"Complexity score: {orch_trend.recent_score:.2f}"],
            ))

        # Cost drift indicator
        cost_trend = next((t for t in trends if t.dimension == "cost_severity"), None)
        if cost_trend:
            indicators.append(EcosystemInstabilityIndicator(
                name="cost_drift",
                active=cost_trend.direction == "increasing" and cost_trend.significant,
                score=cost_trend.recent_score,
                evidence=cost_trend.evidence or [f"Cost severity ratio: {cost_trend.recent_score:.2f}"],
            ))

        # Recommendation accumulation indicator
        rec_trend = next((t for t in trends if t.dimension == "recommendation_volume"), None)
        if rec_trend:
            indicators.append(EcosystemInstabilityIndicator(
                name="recommendation_accumulation",
                active=rec_trend.direction == "increasing" and rec_trend.significant,
                score=min(rec_trend.recent_score / 10.0, 1.0),
                evidence=rec_trend.evidence or [f"Avg recommendations/snapshot: {rec_trend.recent_score:.1f}"],
            ))

        return indicators

    # ------------------------------------------------------------------
    # Complexity trend
    # ------------------------------------------------------------------

    def _complexity_trend(
        self,
        early: list[dict],
        recent: list[dict],
        trends: list[DriftTrend],
    ) -> OperationalComplexityTrend:
        """Aggregate complexity across orchestration + recommendation volume + provider diversity."""
        orch = next((t for t in trends if t.dimension == "orchestration_complexity"), None)
        rec = next((t for t in trends if t.dimension == "recommendation_volume"), None)
        prov = next((t for t in trends if t.dimension == "provider_diversity"), None)

        def avg3(a: float, b: float, c: float) -> float:
            return (a + b + c) / 3.0

        current = avg3(
            orch.recent_score if orch else 0.0,
            min((rec.recent_score if rec else 0.0) / 10.0, 1.0),
            min((prov.recent_score if prov else 0.0), 1.0),
        )
        previous = avg3(
            orch.early_score if orch else 0.0,
            min((rec.early_score if rec else 0.0) / 10.0, 1.0),
            min((prov.early_score if prov else 0.0), 1.0),
        )
        delta = current - previous
        direction = "increasing" if delta > 0.05 else ("decreasing" if delta < -0.05 else "stable")

        dimensions: list[str] = []
        evidence: list[str] = []
        for t in [orch, rec, prov]:
            if t and t.significant:
                dimensions.append(t.dimension)
                evidence.extend(t.evidence[:1])

        return OperationalComplexityTrend(
            current_score=round(current, 3),
            previous_score=round(previous, 3),
            delta=round(delta, 3),
            direction=direction,
            dimensions=dimensions,
            evidence=evidence[:4],
        )

    def _split_windows(
        self, sorted_snaps: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        n = len(sorted_snaps)
        if n < 3:
            mid = n // 2
            return sorted_snaps[:mid or 1], sorted_snaps[mid:]
        third = max(1, n // 3)
        return sorted_snaps[:third], sorted_snaps[-third:]

    def _empty_analysis(self, window_days: int) -> SystemicDriftAnalysis:
        empty_complexity = OperationalComplexityTrend(
            current_score=0.0,
            previous_score=0.0,
            delta=0.0,
            direction="stable",
            dimensions=[],
            evidence=["Insufficient snapshot history for drift analysis"],
        )
        return SystemicDriftAnalysis(
            drift_trends=[],
            instability_indicators=[],
            complexity_trend=empty_complexity,
            overall_drift_score=0.0,
            significant_drift_count=0,
            evidence=["Insufficient snapshot history — at least 2 snapshots required"],
            window_days=window_days,
            snapshot_count=0,
            generated_at=_now(),
        )


# ---------------------------------------------------------------------------
# Window scoring helpers
# ---------------------------------------------------------------------------

def _avg_orchestration_complexity(snaps: list[dict[str, Any]]) -> float:
    """Score per snapshot: fraction of detected orchestration frameworks (capped at 1.0)."""
    _ORCH_FRAMEWORKS = frozenset({
        "langchain", "langgraph", "autogen", "crewai", "haystack", "llamaindex", "llama-index"
    })
    if not snaps:
        return 0.0
    scores: list[float] = []
    for snap in snaps:
        pkgs_raw = (
            snap.get("data", {})
            .get("scanner_results", {})
            .get("results", {})
            .get("repo_scanner", {})
            .get("packages", [])
        )
        pkgs = frozenset(p.lower() for p in pkgs_raw if isinstance(p, str))
        found = pkgs & _ORCH_FRAMEWORKS
        scores.append(min(len(found) / 4.0, 1.0))
    return round(sum(scores) / len(scores), 3)


def _avg_provider_count(snaps: list[dict[str, Any]]) -> float:
    """Score per snapshot: normalized provider count (1 provider = 0.25, 4+ = 1.0)."""
    if not snaps:
        return 0.0
    scores: list[float] = []
    for snap in snaps:
        detections = snap.get("data", {}).get("llm_detections", [])
        providers = {d.get("provider", "") for d in detections if d.get("provider")}
        scores.append(min(len(providers) / 4.0, 1.0))
    return round(sum(scores) / len(scores), 3)


def _avg_runtime_health(snaps: list[dict[str, Any]]) -> float:
    """Average health_score across snapshots with runtime data. Returns 1.0 if no data."""
    if not snaps:
        return 1.0
    valid = [
        snap.get("data", {}).get("runtime_health", {}).get("health_score")
        for snap in snaps
        if snap.get("data", {}).get("runtime_health", {}).get("health_score") is not None
    ]
    if not valid:
        return 1.0
    return round(sum(valid) / len(valid), 3)


def _avg_recommendation_count(snaps: list[dict[str, Any]]) -> float:
    """Average recommendation count per snapshot (raw count, not normalized)."""
    if not snaps:
        return 0.0
    counts = [len(snap.get("data", {}).get("recommendations", [])) for snap in snaps]
    return round(sum(counts) / len(counts), 2)


def _avg_high_cost_ratio(snaps: list[dict[str, Any]]) -> float:
    """Fraction of cost observations that are high-severity, averaged across snapshots."""
    if not snaps:
        return 0.0
    ratios: list[float] = []
    for snap in snaps:
        obs = snap.get("data", {}).get("cost_observations", [])
        if not obs:
            ratios.append(0.0)
        else:
            high = sum(1 for o in obs if o.get("severity") in ("high", "warning"))
            ratios.append(high / len(obs))
    return round(sum(ratios) / len(ratios), 3)


def _direction(early: float, recent: float) -> str:
    delta = recent - early
    threshold = _HEURISTICS.threshold("drift_significant_magnitude") / 2.0
    if delta > threshold:
        return "increasing"
    if delta < -threshold:
        return "decreasing"
    return "stable"


def _aggregate_drift_score(trends: list[DriftTrend]) -> float:
    if not trends:
        return 0.0
    return round(sum(t.magnitude for t in trends) / len(trends), 3)


def _now() -> str:
    return datetime.now(UTC).isoformat()
