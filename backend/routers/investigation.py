"""
Investigation API routes — guided operational investigation.

All endpoints are read-only and advisory.
No infrastructure modifications. No autonomous actions.
No chatbot. No generative AI. Deterministic only.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from cognition.comparison import ComparisonEngine
from cognition.investigation import VALID_KINDS, InvestigationEngine
from cognition.patterns import PatternLibrary
from cognition.recurrence import ContinuityEngine, RecurrenceEngine
from reports.evidence_trace import EvidenceTracer
from reports.explanations import ExplanationGenerator
from reports.investigation_report import (
    generate_comparison_report,
    generate_continuity_report,
    generate_investigation_report,
    generate_persistent_concerns_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigation", tags=["investigation"])


def _snapshot_engine(request: Request):
    return request.app.state.snapshot_engine


@router.get("/investigate")
def investigate(
    kind: str = Query(default="recent_changes", description=f"One of: {', '.join(sorted(VALID_KINDS))}"),
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    title: str = Query(default="", description="Recommendation title (for recommendation_evidence kind)"),
    workflow_type: str = Query(default="", description="Workflow type (for workflow_instability kind)"),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Run a structured operational investigation.

    Supported kinds:
    - severity_increase: what contributed to severity changes?
    - recommendation_evidence: what evidence supports a recommendation?
    - workflow_instability: why does a workflow appear unstable?
    - component_involvement: which components keep recurring?
    - recent_changes: what changed recently?
    - concern_contribution: what contributed most to the top concern?
    """
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    context: dict[str, Any] = {}
    if title:
        context["title"] = title
    if workflow_type:
        context["workflow_type"] = workflow_type

    result = InvestigationEngine().investigate(kind=kind, snapshots=snapshots, context=context)
    return result.to_dict()


@router.get("/investigate/report")
def investigate_report(
    kind: str = Query(default="recent_changes"),
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    title: str = Query(default=""),
    workflow_type: str = Query(default=""),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Run an investigation and return a markdown report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    context: dict[str, Any] = {}
    if title:
        context["title"] = title
    if workflow_type:
        context["workflow_type"] = workflow_type

    result = InvestigationEngine().investigate(kind=kind, snapshots=snapshots, context=context)

    # Also run pattern match and explanation for richer report
    latest = snapshots[-1] if snapshots else {}
    data = latest.get("data", {}) if latest else {}
    patterns = PatternLibrary().matched_only(data)

    from cognition.severity import SeverityEngine
    rt = data.get("runtime_health", {})
    severity = SeverityEngine().assess(
        runtime_health_score=rt.get("health_score") if rt else None,
        recommendations=data.get("recommendations", []),
        cost_observations=data.get("cost_observations", []),
    )

    explanation = ExplanationGenerator().explain_severity(severity.to_dict())

    md = generate_investigation_report(
        result=result.to_dict(),
        patterns=[p.to_dict() for p in patterns],
        explanation=explanation.to_dict(),
    )
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/compare")
def compare_snapshots(
    snapshot_a: int = Query(..., description="ID of baseline snapshot"),
    snapshot_b: int = Query(..., description="ID of comparison snapshot"),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Compare two snapshots across all operational dimensions.

    Returns topology, workflow, runtime, recommendation, cost, and severity deltas.
    """
    snap_a = snapshot_engine.get_by_id(snapshot_a)
    snap_b = snapshot_engine.get_by_id(snapshot_b)

    if not snap_a:
        raise HTTPException(status_code=404, detail=f"Snapshot #{snapshot_a} not found")
    if not snap_b:
        raise HTTPException(status_code=404, detail=f"Snapshot #{snapshot_b} not found")

    comparison = ComparisonEngine().compare(snap_a, snap_b)
    explanation = ExplanationGenerator().explain_comparison(comparison.to_dict())

    return {
        "comparison": comparison.to_dict(),
        "explanation": explanation.to_dict(),
    }


@router.get("/compare/report")
def compare_report(
    snapshot_a: int = Query(..., description="ID of baseline snapshot"),
    snapshot_b: int = Query(..., description="ID of comparison snapshot"),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown comparison report for two snapshots."""
    snap_a = snapshot_engine.get_by_id(snapshot_a)
    snap_b = snapshot_engine.get_by_id(snapshot_b)

    if not snap_a:
        raise HTTPException(status_code=404, detail=f"Snapshot #{snapshot_a} not found")
    if not snap_b:
        raise HTTPException(status_code=404, detail=f"Snapshot #{snapshot_b} not found")

    comparison = ComparisonEngine().compare(snap_a, snap_b)
    md = generate_comparison_report(comparison.to_dict())
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/continuity")
def get_continuity(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Track recommendation lifespans across snapshot history.

    Identifies persistent, recurring, resolved, and new recommendations.
    """
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    lifespans = ContinuityEngine().track(snapshots)

    return {
        "lifespans": [l.to_dict() for l in lifespans],
        "snapshot_count": len(snapshots),
        "days_analyzed": days,
        "summary": {
            "persistent": sum(1 for l in lifespans if l.status == "persistent"),
            "recurring": sum(1 for l in lifespans if l.status == "recurring"),
            "resolved": sum(1 for l in lifespans if l.status == "resolved"),
            "new": sum(1 for l in lifespans if l.status == "new"),
        },
    }


@router.get("/continuity/report")
def get_continuity_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown recommendation continuity report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    lifespans = ContinuityEngine().track(snapshots)
    md = generate_continuity_report([l.to_dict() for l in lifespans])
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/patterns")
def get_patterns(
    days: int = Query(default=7, ge=1, le=90),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Match operational pattern signatures against the latest snapshot.

    Returns all patterns (matched and unmatched) with evidence.
    """
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        return {"patterns": [], "matched_count": 0, "message": "No snapshot available"}

    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=50)
    temporal_volatility: float | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_volatility = temporal.volatility_score

    data = latest.get("data", {})
    runtime_health = data.get("runtime_health")

    patterns = PatternLibrary().match_all(
        scan_payload=data,
        runtime_health=runtime_health,
        temporal_volatility=temporal_volatility,
    )
    matched = [p for p in patterns if p.matched]

    return {
        "patterns": [p.to_dict() for p in patterns],
        "matched_count": len(matched),
        "total_patterns": len(patterns),
        "snapshot_id": latest.get("id"),
    }


@router.get("/explain/severity")
def explain_severity(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Generate a bounded explanation for the current severity assessment."""
    from cognition.recurrence import RecurrenceEngine
    from cognition.severity import SeverityEngine

    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    latest = snapshots[-1] if snapshots else snapshot_engine.get_latest("full_scan")

    if not latest:
        return {"explanation": None, "message": "No snapshot available"}

    data = latest.get("data", {})
    rt = data.get("runtime_health", {})
    recommendations = data.get("recommendations", [])
    cost_observations = data.get("cost_observations", [])
    recurring = RecurrenceEngine().detect(snapshots) if len(snapshots) >= 2 else []

    temporal_dict: dict[str, Any] | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_dict = {
            "volatility_score": temporal.volatility_score,
            "total_changes": temporal.total_changes,
            "churn_indicators": temporal.churn_indicators,
        }

    severity = SeverityEngine().assess(
        runtime_health_score=rt.get("health_score") if rt else None,
        recommendations=recommendations,
        temporal_volatility=temporal_dict.get("volatility_score") if temporal_dict else None,
        recurrence_count=len(recurring),
        cost_observations=cost_observations,
    )

    explanation = ExplanationGenerator().explain_severity(
        severity=severity.to_dict(),
        temporal=temporal_dict,
        recurrence=[i.to_dict() for i in recurring],
    )

    return {
        "severity": severity.to_dict(),
        "explanation": explanation.to_dict(),
    }


@router.get("/explain/recommendation")
def explain_recommendation(
    title: str = Query(default="", description="Recommendation title (partial match)"),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Generate a bounded explanation for a specific recommendation."""
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        raise HTTPException(status_code=404, detail="No snapshot available")

    data = latest.get("data", {})
    recs = data.get("recommendations", [])

    matched_rec = None
    title_lower = title.lower()
    for rec in recs:
        if title_lower and title_lower in rec.get("title", "").lower():
            matched_rec = rec
            break
    if not matched_rec and recs:
        matched_rec = recs[0]
    if not matched_rec:
        raise HTTPException(status_code=404, detail="No recommendations found in latest snapshot")

    explanation = ExplanationGenerator().explain_recommendation(
        rec=matched_rec,
        context_snapshot=latest,
    )
    return {
        "recommendation": matched_rec,
        "explanation": explanation.to_dict(),
    }


@router.get("/evidence/recommendation")
def trace_recommendation_evidence(
    title: str = Query(default="", description="Recommendation title (partial match)"),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Trace a recommendation back to its source observations and evidence chain."""
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        raise HTTPException(status_code=404, detail="No snapshot available")

    data = latest.get("data", {})
    recs = data.get("recommendations", [])

    matched_rec = None
    title_lower = title.lower()
    for rec in recs:
        if title_lower and title_lower in rec.get("title", "").lower():
            matched_rec = rec
            break
    if not matched_rec and recs:
        matched_rec = recs[0]
    if not matched_rec:
        raise HTTPException(status_code=404, detail="No recommendations in latest snapshot")

    tree = EvidenceTracer().trace_recommendation(matched_rec, latest)
    return tree.to_dict()


@router.get("/evidence/severity")
def trace_severity_evidence(
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Trace a severity assessment back to its contributing factor evidence."""
    from cognition.severity import SeverityEngine

    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    latest = snapshots[-1] if snapshots else snapshot_engine.get_latest("full_scan")
    if not latest:
        raise HTTPException(status_code=404, detail="No snapshot available")

    data = latest.get("data", {})
    rt = data.get("runtime_health", {})

    temporal_dict: dict[str, Any] | None = None
    if len(snapshots) >= 2:
        from cognition.temporal_analysis import TemporalAnalysisEngine
        temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal_dict = {
            "volatility_score": temporal.volatility_score,
            "total_changes": temporal.total_changes,
            "churn_indicators": temporal.churn_indicators,
        }

    severity = SeverityEngine().assess(
        runtime_health_score=rt.get("health_score") if rt else None,
        recommendations=data.get("recommendations", []),
        cost_observations=data.get("cost_observations", []),
    )

    tree = EvidenceTracer().trace_severity(severity.to_dict(), latest, temporal_dict)
    return tree.to_dict()


@router.get("/report/persistent")
def get_persistent_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown report of persistent operational concerns."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    lifespans = ContinuityEngine().track(snapshots)
    recurring = RecurrenceEngine().detect(snapshots) if len(snapshots) >= 2 else []

    md = generate_persistent_concerns_report(
        lifespans=[l.to_dict() for l in lifespans],
        recurring_issues=[i.to_dict() for i in recurring],
    )
    return PlainTextResponse(md, media_type="text/markdown")
