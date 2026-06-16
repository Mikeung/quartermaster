"""
Heuristic registry — centralized threshold definitions for Phase 6 ecosystem cognition.

Documents and mirrors thresholds used across cognition modules.
Provides a single lookup point for ecosystem-level synthesis, clustering,
drift analysis, and consolidation.

IMPORTANT:
- Existing modules retain their own constants (no refactoring).
- This registry mirrors those values for cross-module visibility.
- This is NOT a rules engine. It is a static reference layer.
- Thresholds are engineering estimates — not empirically validated minimums.

Advisory only. Deterministic. Lightweight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Heuristic:
    """A named operational heuristic with its threshold, rationale, and source module."""
    name: str
    description: str
    threshold: float
    rationale: str
    source_module: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "threshold": self.threshold,
            "rationale": self.rationale,
            "source_module": self.source_module,
        }


# ---------------------------------------------------------------------------
# Heuristic definitions
# ---------------------------------------------------------------------------

_HEURISTICS: dict[str, Heuristic] = {
    # Severity scoring (cognition/severity.py)
    "severity_critical_score": Heuristic(
        name="severity_critical_score",
        description="Minimum weighted score for CRITICAL severity classification",
        threshold=0.80,
        rationale="Above 0.80 multiple high-weight factors are simultaneously elevated",
        source_module="cognition.severity",
    ),
    "severity_high_score": Heuristic(
        name="severity_high_score",
        description="Minimum weighted score for HIGH severity classification",
        threshold=0.60,
        rationale="0.60 represents co-occurrence of runtime degradation + significant recommendation load",
        source_module="cognition.severity",
    ),
    "severity_moderate_score": Heuristic(
        name="severity_moderate_score",
        description="Minimum weighted score for MODERATE severity classification",
        threshold=0.40,
        rationale="0.40 is roughly one major factor fully saturated",
        source_module="cognition.severity",
    ),
    "severity_low_score": Heuristic(
        name="severity_low_score",
        description="Minimum weighted score for LOW severity classification",
        threshold=0.20,
        rationale="0.20 captures weak signals that warrant monitoring but not action",
        source_module="cognition.severity",
    ),

    # Attention guidance (cognition/attention.py)
    "attention_suppress_threshold": Heuristic(
        name="attention_suppress_threshold",
        description="Minimum priority score for an item to appear in attention report",
        threshold=0.35,
        rationale="Below 0.35 items are low-urgency noise; above brings meaningful signal",
        source_module="cognition.attention",
    ),

    # Temporal analysis (cognition/temporal_analysis.py)
    "high_volatility_threshold": Heuristic(
        name="high_volatility_threshold",
        description="Volatility score above which infrastructure is considered highly volatile",
        threshold=0.60,
        rationale="0.60+ means changes in >60% of snapshot pairs — structurally unstable",
        source_module="cognition.temporal_analysis",
    ),
    "moderate_volatility_threshold": Heuristic(
        name="moderate_volatility_threshold",
        description="Volatility score above which infrastructure is considered moderately volatile",
        threshold=0.40,
        rationale="0.40+ signals active change without full churn",
        source_module="cognition.temporal_analysis",
    ),

    # Recurrence detection (cognition/recurrence.py)
    "recurrence_min_occurrences": Heuristic(
        name="recurrence_min_occurrences",
        description="Minimum snapshot appearances for a concern to be considered recurring",
        threshold=2.0,
        rationale="One occurrence may be transient; two or more establishes a pattern",
        source_module="cognition.recurrence",
    ),
    "persistent_occurrence_ratio": Heuristic(
        name="persistent_occurrence_ratio",
        description="Minimum occurrence ratio (occurrences / total snapshots) for PERSISTENT status",
        threshold=0.80,
        rationale="Present in 80%+ of scans is a structural concern, not a transient one",
        source_module="cognition.recurrence",
    ),
    "recurring_occurrence_ratio": Heuristic(
        name="recurring_occurrence_ratio",
        description="Minimum occurrence ratio for RECURRING (below persistent) status",
        threshold=0.40,
        rationale="Present in 40%+ of scans is frequent enough to warrant tracking",
        source_module="cognition.recurrence",
    ),

    # Ecosystem synthesis (cognition/synthesis.py)
    "theme_minimum_evidence": Heuristic(
        name="theme_minimum_evidence",
        description="Minimum number of evidence items to declare an operational theme active",
        threshold=2.0,
        rationale="A single signal may be spurious; two or more suggests a theme",
        source_module="cognition.synthesis",
    ),
    "dominant_theme_prevalence": Heuristic(
        name="dominant_theme_prevalence",
        description="Minimum prevalence score for a theme to be declared dominant",
        threshold=0.50,
        rationale="Dominant means the theme accounts for the majority of observed signals",
        source_module="cognition.synthesis",
    ),

    # Clustering (cognition/clustering.py)
    "cluster_minimum_score": Heuristic(
        name="cluster_minimum_score",
        description="Minimum evidence score for a concern cluster to be considered active",
        threshold=0.30,
        rationale="Below 0.30 the cluster has too few signals to be operationally meaningful",
        source_module="cognition.clustering",
    ),
    "cluster_high_score": Heuristic(
        name="cluster_high_score",
        description="Score above which a cluster is considered densely populated",
        threshold=0.70,
        rationale="0.70+ means multiple independent signals converge on the same cluster",
        source_module="cognition.clustering",
    ),

    # Systemic drift (cognition/systemic_drift.py)
    "drift_significant_magnitude": Heuristic(
        name="drift_significant_magnitude",
        description="Drift magnitude above which a trend is considered significant",
        threshold=0.25,
        rationale="0.25+ represents a 25% change in the measured dimension between windows",
        source_module="cognition.systemic_drift",
    ),
    "complexity_accumulation_threshold": Heuristic(
        name="complexity_accumulation_threshold",
        description="Complexity score above which the ecosystem is considered complex",
        threshold=0.60,
        rationale="Combines framework count + provider diversity + workflow depth",
        source_module="cognition.systemic_drift",
    ),

    # Consolidation (cognition/consolidation.py)
    "consolidation_min_shared_evidence": Heuristic(
        name="consolidation_min_shared_evidence",
        description="Minimum shared evidence items for two concerns to be consolidated",
        threshold=2.0,
        rationale="One shared keyword may be coincidental; two suggests genuine overlap",
        source_module="cognition.consolidation",
    ),
}


class HeuristicRegistry:
    """Static registry of operational heuristics.

    Provides a single lookup point for threshold values used across
    ecosystem-level cognition modules.

    Not a rules engine. Does not execute logic.
    Returns heuristic metadata and threshold values only.
    """

    def get(self, name: str) -> Heuristic:
        """Return a heuristic by name, or raise KeyError."""
        if name not in _HEURISTICS:
            raise KeyError(f"Unknown heuristic: '{name}'. Available: {sorted(_HEURISTICS.keys())}")
        return _HEURISTICS[name]

    def threshold(self, name: str) -> float:
        """Return the numeric threshold for a named heuristic."""
        return self.get(name).threshold

    def all(self) -> list[Heuristic]:
        """Return all registered heuristics, sorted by name."""
        return sorted(_HEURISTICS.values(), key=lambda h: h.name)

    def by_module(self, module: str) -> list[Heuristic]:
        """Return heuristics belonging to a given source module."""
        return [h for h in _HEURISTICS.values() if h.source_module == module]

    def to_dict(self) -> dict[str, Any]:
        return {
            "heuristics": [h.to_dict() for h in self.all()],
            "count": len(_HEURISTICS),
            "advisory": "Thresholds are engineering estimates — not empirically validated minimums.",
        }
