"""
Runtime operational intelligence API routes.

All endpoints are read-only and advisory.
No infrastructure modifications. No autonomous actions.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cognition.recurrence import RecurrenceEngine
from cognition.runtime_health import RuntimeHealthIntelligence
from cognition.runtime_topology import RuntimeTopologyFusion
from cognition.severity import SeverityEngine
from reports.digest import generate_critical_digest, generate_daily_digest, generate_morning_digest
from scanners.runtime_scanner import RuntimeScanner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runtime", tags=["runtime"])


def _snapshot_engine(request: Request):
    return request.app.state.snapshot_engine


@router.get("/health")
def get_runtime_health() -> dict[str, Any]:
    """Live runtime health assessment — reads current system state.

    Runs the runtime scanner and applies deterministic health thresholds.
    Returns per-resource indicators, overall status, and instability signals.
    """
    scanner = RuntimeScanner()
    runtime_state = scanner.run("localhost")
    if "error" in runtime_state:
        raise HTTPException(status_code=500, detail=f"Runtime scan failed: {runtime_state['error']}")

    health = RuntimeHealthIntelligence().assess(runtime_state)
    return {
        "runtime_state": runtime_state,
        "health_report": health.to_dict(),
    }


@router.get("/severity")
def get_severity(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Full operational severity assessment.

    Combines live runtime health with recommendation and temporal signals
    from snapshot history to produce a weighted severity score.
    """
    scanner = RuntimeScanner()
    runtime_state = scanner.run("localhost")
    health = RuntimeHealthIntelligence().assess(runtime_state)

    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    # Pull data from latest snapshot for recommendations and cost observations
    recommendations: list[dict[str, Any]] = []
    cost_observations: list[dict[str, Any]] = []
    if snapshots:
        latest_data = snapshots[-1].get("data", {})
        recommendations = latest_data.get("recommendations", [])
        cost_observations = latest_data.get("cost_observations", [])

    # Recurrence
    recurring = RecurrenceEngine().detect(snapshots)

    # Temporal volatility from latest snapshot if available
    temporal_volatility: float | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_volatility = temporal.volatility_score

    assessment = SeverityEngine().assess(
        runtime_health_score=health.health_score,
        recommendations=recommendations,
        temporal_volatility=temporal_volatility,
        recurrence_count=len(recurring),
        cost_observations=cost_observations,
    )

    return {
        "severity": assessment.to_dict(),
        "runtime_health": health.to_dict(),
        "recurrence_count": len(recurring),
        "snapshot_count": len(snapshots),
    }


@router.get("/recurrence")
def get_recurrence(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Detect recurring operational issues across snapshot history.

    Identifies patterns that repeat across scans: repeated recommendations,
    recurring cost warnings, component drift, and persistent service failures.
    """
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if len(snapshots) < 2:
        return {
            "recurring_issues": [],
            "snapshot_count": len(snapshots),
            "message": "Insufficient snapshot history for recurrence detection (need ≥ 2)",
        }

    issues = RecurrenceEngine().detect(snapshots)
    return {
        "recurring_issues": [i.to_dict() for i in issues],
        "snapshot_count": len(snapshots),
        "days_analyzed": days,
    }


@router.get("/fused")
def get_fused_insights(
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Runtime + topology fusion insights.

    Correlates live runtime state with topology structure and workflow patterns
    to surface compound operational concerns not visible from either source alone.
    """
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        return {"fused_insights": [], "message": "No snapshot available for fusion analysis"}

    data = latest.get("data", {})
    topology_dict = data.get("topology", {})
    workflows = data.get("workflows", [])
    cost_observations = data.get("cost_observations", [])

    scanner = RuntimeScanner()
    runtime_state = scanner.run("localhost")
    health = RuntimeHealthIntelligence().assess(runtime_state)

    insights = RuntimeTopologyFusion().fuse(
        topology_dict=topology_dict,
        workflows=workflows,
        runtime_health=health,
        cost_observations=cost_observations,
    )

    return {
        "fused_insights": [i.to_dict() for i in insights],
        "snapshot_id": latest.get("id"),
        "runtime_status": health.overall_status,
        "workflow_count": len(workflows),
    }


@router.get("/digest")
def get_daily_digest(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Daily operational digest — full picture from latest snapshot + live runtime.

    Combines snapshot intelligence, runtime health, attention guidance,
    recurring issues, severity, and fused insights into one concise report.
    """
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        return {"digest": "No snapshot available.", "format": "markdown"}

    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)

    # Live runtime health
    runtime_state = RuntimeScanner().run("localhost")
    health = RuntimeHealthIntelligence().assess(runtime_state)

    # Severity
    data = latest.get("data", {})
    recommendations = data.get("recommendations", [])
    cost_observations = data.get("cost_observations", [])
    recurring = RecurrenceEngine().detect(snapshots) if len(snapshots) >= 2 else []

    temporal_volatility: float | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_volatility = temporal.volatility_score

    severity = SeverityEngine().assess(
        runtime_health_score=health.health_score,
        recommendations=recommendations,
        temporal_volatility=temporal_volatility,
        recurrence_count=len(recurring),
        cost_observations=cost_observations,
    )

    # Attention report
    from cognition.attention import AttentionGuidance
    from cognition.prioritization import PrioritizationEngine
    workflows = data.get("workflows", [])
    temporal_obj = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal_obj = TemporalAnalysisEngine().analyze(snapshots, window_days=days)

    priority_items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=[],
        temporal=temporal_obj,
    )
    attention = AttentionGuidance().generate(
        priority_items=priority_items,
        temporal=temporal_obj,
        cost_observations=cost_observations,
        runtime_health=health,
    )

    # Fused insights
    insights = RuntimeTopologyFusion().fuse(
        topology_dict=data.get("topology", {}),
        workflows=workflows,
        runtime_health=health,
        temporal_volatility=temporal_volatility,
        cost_observations=cost_observations,
    )

    digest_md = generate_daily_digest(
        snapshot=latest,
        runtime_health=health.to_dict(),
        attention_report=attention.to_dict(),
        recurring_issues=[i.to_dict() for i in recurring],
        severity=severity.to_dict(),
        fused_insights=[i.to_dict() for i in insights],
    )

    return {"digest": digest_md, "format": "markdown", "snapshot_id": latest.get("id")}


@router.get("/digest/morning")
def get_morning_digest(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Morning operational digest — trend-focused start-of-day summary."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)

    temporal_dict: dict[str, Any] | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal_obj = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_dict = {
            "volatility_score": temporal_obj.volatility_score,
            "stability_score": temporal_obj.stability_score,
            "total_changes": temporal_obj.total_changes,
            "window_days": temporal_obj.window_days,
            "churn_indicators": temporal_obj.churn_indicators,
            "trend_observations": temporal_obj.trend_observations,
        }

    attention_dict: dict[str, Any] | None = None
    if snapshots:
        latest_data = snapshots[-1].get("data", {})
        recommendations = latest_data.get("recommendations", [])
        cost_observations = latest_data.get("cost_observations", [])
        from cognition.attention import AttentionGuidance
        from cognition.prioritization import PrioritizationEngine
        priority_items = PrioritizationEngine().rank(
            recommendations=recommendations,
            cost_observations=cost_observations,
            workflows=[],
            temporal=None,
        )
        attention = AttentionGuidance().generate(priority_items=priority_items)
        attention_dict = attention.to_dict()

    digest_md = generate_morning_digest(
        snapshots=snapshots,
        temporal=temporal_dict,
        attention_report=attention_dict,
    )
    return {"digest": digest_md, "format": "markdown"}


@router.get("/digest/critical")
def get_critical_digest(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Critical operational digest — immediate-action items only."""
    latest = snapshot_engine.get_latest("full_scan")
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)

    runtime_state = RuntimeScanner().run("localhost")
    health = RuntimeHealthIntelligence().assess(runtime_state)

    data = (latest or {}).get("data", {})
    recommendations = data.get("recommendations", [])
    cost_observations = data.get("cost_observations", [])
    workflows = data.get("workflows", [])
    recurring = RecurrenceEngine().detect(snapshots) if len(snapshots) >= 2 else []

    temporal_volatility: float | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal_obj = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_volatility = temporal_obj.volatility_score

    severity = SeverityEngine().assess(
        runtime_health_score=health.health_score,
        recommendations=recommendations,
        temporal_volatility=temporal_volatility,
        recurrence_count=len(recurring),
        cost_observations=cost_observations,
    )

    from cognition.attention import AttentionGuidance
    from cognition.prioritization import PrioritizationEngine
    priority_items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=[],
        temporal=None,
    )
    attention = AttentionGuidance().generate(
        priority_items=priority_items,
        runtime_health=health,
    )

    insights = RuntimeTopologyFusion().fuse(
        topology_dict=data.get("topology", {}),
        workflows=workflows,
        runtime_health=health,
        temporal_volatility=temporal_volatility,
        cost_observations=cost_observations,
    )

    digest_md = generate_critical_digest(
        severity=severity.to_dict(),
        attention_report=attention.to_dict(),
        fused_insights=[i.to_dict() for i in insights],
        runtime_health=health.to_dict(),
    )

    return {
        "digest": digest_md,
        "format": "markdown",
        "severity_level": severity.level.value,
    }
