"""
Temporal intelligence — analyze how the system changes over time.

Consumes a sequence of operational snapshots and extracts:
- what changed across the full window (not just N vs N-1)
- which components are volatile (changed repeatedly)
- overall volatility and stability scores
- churn indicators and trend observations

All inference is deterministic and evidence-backed.
Advisory output only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChangeEvent:
    """A single detected change between two consecutive snapshots."""
    change_type: str
    value: str
    snapshot_id: int
    detected_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_type": self.change_type,
            "value": self.value,
            "snapshot_id": self.snapshot_id,
            "detected_at": self.detected_at,
        }


@dataclass
class ComponentChurn:
    """A component that changed more than once across the analysis window."""
    component: str
    change_count: int
    change_types: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "change_count": self.change_count,
            "change_types": self.change_types,
        }


@dataclass
class TemporalAnalysis:
    """Result of analyzing multiple snapshots for operational evolution."""
    window_days: int
    snapshot_count: int
    first_snapshot_at: str
    last_snapshot_at: str
    total_changes: int
    change_events: list[ChangeEvent]
    change_frequency: dict[str, int]
    churning_components: list[ComponentChurn]
    volatility_score: float  # 0.0 (fully stable) → 1.0 (maximally volatile)
    stability_score: float   # 1.0 - volatility_score
    churn_indicators: list[str]
    trend_observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "snapshot_count": self.snapshot_count,
            "first_snapshot_at": self.first_snapshot_at,
            "last_snapshot_at": self.last_snapshot_at,
            "total_changes": self.total_changes,
            "change_events": [e.to_dict() for e in self.change_events],
            "change_frequency": self.change_frequency,
            "churning_components": [c.to_dict() for c in self.churning_components],
            "volatility_score": round(self.volatility_score, 3),
            "stability_score": round(self.stability_score, 3),
            "churn_indicators": self.churn_indicators,
            "trend_observations": self.trend_observations,
        }


class TemporalAnalysisEngine:
    """Analyzes operational evolution across multiple snapshots.

    Compares all consecutive snapshot pairs to detect repeated drift,
    volatile components, and trend patterns.
    """

    # Expected max changes per scan pair in a normal, stable system.
    # Used to normalize the volatility score.
    _EXPECTED_MAX_CHANGES_PER_PAIR = 5

    def analyze(self, snapshots: list[dict[str, Any]], window_days: int = 7) -> TemporalAnalysis:
        """
        snapshots: list of snapshot dicts, sorted oldest → newest.
        Each snapshot has keys: id, created_at, data (the full scan payload).
        """
        if not snapshots:
            return self._empty_analysis(window_days)

        first_at = snapshots[0].get("created_at", "unknown")
        last_at = snapshots[-1].get("created_at", "unknown")

        all_events: list[ChangeEvent] = []

        for i in range(1, len(snapshots)):
            older = snapshots[i - 1]
            newer = snapshots[i]
            events = _compare_snapshots(older, newer)
            all_events.extend(events)

        change_frequency: dict[str, int] = {}
        for ev in all_events:
            change_frequency[ev.change_type] = change_frequency.get(ev.change_type, 0) + 1

        churning_components = _find_churning_components(all_events)

        volatility_score = _compute_volatility(
            total_changes=len(all_events),
            snapshot_pairs=max(len(snapshots) - 1, 1),
            expected_max=self._EXPECTED_MAX_CHANGES_PER_PAIR,
        )

        churn_indicators = _build_churn_indicators(
            all_events, churning_components, len(snapshots)
        )
        trend_observations = _build_trend_observations(snapshots, all_events)

        logger.info(
            "Temporal analysis complete",
            extra={
                "window_days": window_days,
                "snapshot_count": len(snapshots),
                "total_changes": len(all_events),
                "volatility_score": round(volatility_score, 3),
            },
        )

        return TemporalAnalysis(
            window_days=window_days,
            snapshot_count=len(snapshots),
            first_snapshot_at=first_at,
            last_snapshot_at=last_at,
            total_changes=len(all_events),
            change_events=all_events,
            change_frequency=change_frequency,
            churning_components=churning_components,
            volatility_score=volatility_score,
            stability_score=round(1.0 - volatility_score, 3),
            churn_indicators=churn_indicators,
            trend_observations=trend_observations,
        )

    def _empty_analysis(self, window_days: int) -> TemporalAnalysis:
        return TemporalAnalysis(
            window_days=window_days,
            snapshot_count=0,
            first_snapshot_at="",
            last_snapshot_at="",
            total_changes=0,
            change_events=[],
            change_frequency={},
            churning_components=[],
            volatility_score=0.0,
            stability_score=1.0,
            churn_indicators=["Insufficient snapshot history for temporal analysis"],
            trend_observations=[],
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_key_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields needed for temporal comparison from a snapshot dict."""
    data = snapshot.get("data", {})
    repo = data.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
    workflows = data.get("workflows", [])

    return {
        "llm_providers": {d["provider"] for d in data.get("llm_detections", [])},
        "llm_sdks": set(repo.get("llm_sdks", [])),
        "frameworks": set(repo.get("frameworks", [])),
        "docker_present": bool(repo.get("docker", {}).get("present", False)),
        "ci_cd": set(repo.get("ci_cd", [])),
        "primary_language": repo.get("primary_language", ""),
        "workflow_types": {
            w.get("workflow_type", w.get("name", ""))
            for w in workflows
            if isinstance(w, dict)
        },
    }


def _compare_snapshots(
    older: dict[str, Any], newer: dict[str, Any]
) -> list[ChangeEvent]:
    """Return ChangeEvents for all differences between two consecutive snapshots."""
    events: list[ChangeEvent] = []
    snap_id = newer.get("id", 0)
    detected_at = newer.get("created_at", "")

    a = _extract_key_data(older)
    b = _extract_key_data(newer)

    for provider in b["llm_providers"] - a["llm_providers"]:
        events.append(ChangeEvent("llm_provider_added", provider, snap_id, detected_at))
    for provider in a["llm_providers"] - b["llm_providers"]:
        events.append(ChangeEvent("llm_provider_removed", provider, snap_id, detected_at))

    for sdk in b["llm_sdks"] - a["llm_sdks"]:
        events.append(ChangeEvent("llm_sdk_added", sdk, snap_id, detected_at))
    for sdk in a["llm_sdks"] - b["llm_sdks"]:
        events.append(ChangeEvent("llm_sdk_removed", sdk, snap_id, detected_at))

    for fw in b["frameworks"] - a["frameworks"]:
        events.append(ChangeEvent("framework_added", fw, snap_id, detected_at))
    for fw in a["frameworks"] - b["frameworks"]:
        events.append(ChangeEvent("framework_removed", fw, snap_id, detected_at))

    if a["docker_present"] != b["docker_present"]:
        val = "added" if b["docker_present"] else "removed"
        events.append(ChangeEvent(f"docker_{val}", "docker", snap_id, detected_at))

    for ci in b["ci_cd"] - a["ci_cd"]:
        events.append(ChangeEvent("ci_added", ci, snap_id, detected_at))
    for ci in a["ci_cd"] - b["ci_cd"]:
        events.append(ChangeEvent("ci_removed", ci, snap_id, detected_at))

    if a["primary_language"] and b["primary_language"] and a["primary_language"] != b["primary_language"]:
        events.append(ChangeEvent(
            "language_changed",
            f"{a['primary_language']} → {b['primary_language']}",
            snap_id,
            detected_at,
        ))

    for wt in b["workflow_types"] - a["workflow_types"]:
        events.append(ChangeEvent("workflow_type_added", wt, snap_id, detected_at))
    for wt in a["workflow_types"] - b["workflow_types"]:
        events.append(ChangeEvent("workflow_type_removed", wt, snap_id, detected_at))

    return events


def _find_churning_components(events: list[ChangeEvent]) -> list[ComponentChurn]:
    """Identify components that changed more than once."""
    component_events: dict[str, list[str]] = {}
    for ev in events:
        component_events.setdefault(ev.value, []).append(ev.change_type)

    churning = [
        ComponentChurn(
            component=component,
            change_count=len(change_types),
            change_types=change_types,
        )
        for component, change_types in component_events.items()
        if len(change_types) > 1
    ]
    return sorted(churning, key=lambda c: -c.change_count)


def _compute_volatility(
    total_changes: int, snapshot_pairs: int, expected_max: int
) -> float:
    if snapshot_pairs == 0 or total_changes == 0:
        return 0.0
    raw = total_changes / (snapshot_pairs * expected_max)
    return min(round(raw, 3), 1.0)


def _build_churn_indicators(
    events: list[ChangeEvent],
    churning: list[ComponentChurn],
    snapshot_count: int,
) -> list[str]:
    indicators: list[str] = []

    for c in churning:
        indicators.append(
            f"'{c.component}' changed {c.change_count} times in the analysis window "
            f"({', '.join(c.change_types)})"
        )

    llm_changes = sum(
        1 for e in events
        if e.change_type in ("llm_provider_added", "llm_provider_removed", "llm_sdk_added", "llm_sdk_removed")
    )
    if llm_changes >= 3:
        indicators.append(
            f"LLM configuration is volatile: {llm_changes} LLM-related changes detected"
        )

    fw_changes = sum(
        1 for e in events
        if e.change_type in ("framework_added", "framework_removed")
    )
    if fw_changes >= 3:
        indicators.append(f"Framework churn detected: {fw_changes} framework changes")

    total = len(events)
    pairs = max(snapshot_count - 1, 1)
    if total > pairs * 3:
        indicators.append(
            f"High change rate: {total} changes across {pairs} scan transitions "
            f"(avg {total / pairs:.1f} per scan)"
        )

    if not indicators:
        indicators.append("System is stable — no significant churn detected in analysis window")

    return indicators


def _build_trend_observations(
    snapshots: list[dict[str, Any]], events: list[ChangeEvent]
) -> list[str]:
    observations: list[str] = []
    if len(snapshots) < 2:
        return observations

    first_data = _extract_key_data(snapshots[0])
    last_data = _extract_key_data(snapshots[-1])

    # Providers that persisted throughout
    stable_providers = first_data["llm_providers"] & last_data["llm_providers"]
    if stable_providers:
        observations.append(
            f"Stable LLM providers throughout window: {', '.join(sorted(stable_providers))}"
        )

    # New providers that appeared
    new_providers = last_data["llm_providers"] - first_data["llm_providers"]
    if new_providers:
        observations.append(
            f"New LLM providers introduced: {', '.join(sorted(new_providers))}"
        )

    # Workflow complexity growth
    new_workflows = last_data["workflow_types"] - first_data["workflow_types"]
    if new_workflows:
        observations.append(
            f"New workflow patterns emerged: {', '.join(sorted(new_workflows))}"
        )

    # Stable workflows
    stable_workflows = first_data["workflow_types"] & last_data["workflow_types"]
    if stable_workflows:
        observations.append(
            f"Persistent workflow patterns: {', '.join(sorted(stable_workflows))}"
        )

    return observations
