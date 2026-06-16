"""
Ecosystem API routes — ecosystem-level operational synthesis.

All endpoints are read-only and advisory.
No infrastructure modifications. No autonomous actions.
No chatbot. No generative AI. Deterministic only.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from cognition.clustering import ConcernClusteringEngine
from cognition.consolidation import ConsolidationEngine
from cognition.patterns import PatternLibrary
from cognition.recurrence import RecurrenceEngine
from cognition.severity import SeverityEngine
from cognition.synthesis import EcosystemSynthesisEngine
from cognition.systemic_drift import SystemicDriftEngine
from cognition.temporal_analysis import TemporalAnalysisEngine
from reports.digest import (
    generate_strategic_attention_digest,
    generate_weekly_synthesis_digest,
)
from reports.ecosystem_review import (
    generate_ecosystem_complexity_report,
    generate_ecosystem_drift_report,
    generate_ecosystem_review,
    generate_operational_theme_report,
    generate_systemic_concern_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ecosystem", tags=["ecosystem"])


def _snapshot_engine(request: Request):
    return request.app.state.snapshot_engine


def _build_context(
    snapshots: list[dict[str, Any]],
    days: int,
) -> dict[str, Any]:
    """Build ecosystem context from a snapshot window."""
    latest = snapshots[-1] if snapshots else {}
    data = latest.get("data", {}) if latest else {}

    runtime_health = data.get("runtime_health")
    recommendations = data.get("recommendations", [])
    workflows = data.get("workflows", [])

    temporal = None
    if len(snapshots) >= 2:
        temporal_analysis = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
        temporal = {
            "volatility_score": temporal_analysis.volatility_score,
            "total_changes": temporal_analysis.total_changes,
            "churn_indicators": temporal_analysis.churn_indicators,
        }

    patterns = PatternLibrary().match_all(
        scan_payload=data,
        runtime_health=runtime_health,
        temporal_volatility=temporal.get("volatility_score") if temporal else None,
    )

    recurring = RecurrenceEngine().detect(snapshots) if len(snapshots) >= 2 else []

    return {
        "snapshots": snapshots,
        "latest_data": data,
        "runtime_health": runtime_health,
        "recommendations": recommendations,
        "workflows": workflows,
        "temporal": temporal,
        "patterns": [p.to_dict() for p in patterns],
        "matched_patterns": [p.to_dict() for p in patterns if p.matched],
        "recurring": [r.to_dict() for r in recurring],
    }


@router.get("/summary")
def get_ecosystem_summary(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Generate ecosystem-level operational synthesis.

    Answers: What themes dominate? Where is complexity accumulating?
    Which concerns are systemic?
    """
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)

    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    return summary.to_dict()


@router.get("/themes")
def get_ecosystem_themes(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Return operational themes extracted from ecosystem signals."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)

    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    return {
        "themes": [t.to_dict() for t in summary.themes],
        "dominant_theme": summary.dominant_theme,
        "theme_count": len(summary.themes),
    }


@router.get("/clusters")
def get_concern_clusters(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    active_only: bool = Query(default=False, description="Return only active clusters"),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Generate concern clusters from ecosystem signals.

    Clusters are organizational aids — not causal assertions.
    """
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    engine = ConcernClusteringEngine()

    clusters = engine.cluster(
        recommendations=ctx["recommendations"],
        patterns=ctx["patterns"],
        runtime_health=ctx["runtime_health"],
        workflows=ctx["workflows"],
    )

    result = engine.active_only(clusters) if active_only else clusters

    return {
        "clusters": [c.to_dict() for c in result],
        "total_clusters": len(clusters),
        "active_clusters": sum(1 for c in clusters if c.active),
        "note": "Clusters are organizational aids — not causal assertions.",
    }


@router.get("/drift")
def get_ecosystem_drift(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Analyze systemic drift patterns across the ecosystem snapshot history."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    drift = SystemicDriftEngine().analyze(snapshots, window_days=days)
    return drift.to_dict()


@router.get("/trends")
def get_ecosystem_trends(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Return ecosystem-level trends (complexity, instability, cost risk, volatility)."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)

    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    drift = SystemicDriftEngine().analyze(snapshots, window_days=days)

    return {
        "ecosystem_trends": [t.to_dict() for t in summary.trends],
        "drift_trends": [t.to_dict() for t in drift.drift_trends],
        "complexity_trend": drift.complexity_trend.to_dict(),
        "overall_drift_score": drift.overall_drift_score,
    }


@router.get("/review")
def get_ecosystem_review(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a full ecosystem operational review in markdown."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    engine = ConcernClusteringEngine()

    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )

    clusters = engine.cluster(
        recommendations=ctx["recommendations"],
        patterns=ctx["patterns"],
        runtime_health=ctx["runtime_health"],
        workflows=ctx["workflows"],
    )

    drift = SystemicDriftEngine().analyze(snapshots, window_days=days)

    consolidated = ConsolidationEngine().consolidate(
        recommendations=ctx["recommendations"],
        patterns=ctx["matched_patterns"],
        clusters=[c.to_dict() for c in engine.active_only(clusters)],
    )

    md = generate_ecosystem_review(
        summary=summary.to_dict(),
        clusters=[c.to_dict() for c in clusters],
        drift=drift.to_dict(),
        consolidated=[c.to_dict() for c in consolidated],
    )
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/report/themes")
def get_theme_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown operational theme report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    md = generate_operational_theme_report([t.to_dict() for t in summary.themes])
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/report/concerns")
def get_systemic_concern_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown systemic concern report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    md = generate_systemic_concern_report([c.to_dict() for c in summary.systemic_concerns])
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/report/drift")
def get_drift_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown ecosystem drift report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    drift = SystemicDriftEngine().analyze(snapshots, window_days=days)
    md = generate_ecosystem_drift_report(drift.to_dict())
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/report/complexity")
def get_complexity_report(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a markdown ecosystem complexity report."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    drift = SystemicDriftEngine().analyze(snapshots, window_days=days)
    md = generate_ecosystem_complexity_report(
        complexity=drift.complexity_trend.to_dict(),
        drift=drift.to_dict(),
    )
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/digest/weekly")
def get_weekly_digest(
    days: int = Query(default=7, ge=1, le=30),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a weekly synthesis digest."""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )
    consolidated = ConsolidationEngine().consolidate(
        recommendations=ctx["recommendations"],
        patterns=ctx["matched_patterns"],
    )
    md = generate_weekly_synthesis_digest(
        snapshots=snapshots,
        themes=[t.to_dict() for t in summary.themes],
        recurring_issues=ctx["recurring"],
        consolidated=[c.to_dict() for c in consolidated],
    )
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/digest/strategic")
def get_strategic_digest(
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=50, ge=2, le=200),
    snapshot_engine=Depends(_snapshot_engine),
) -> PlainTextResponse:
    """Generate a strategic attention digest — what deserves operator focus?"""
    snapshots = snapshot_engine.get_temporal_window(days=days, max_count=max_snapshots)
    if not snapshots:
        latest = snapshot_engine.get_latest("full_scan")
        snapshots = [latest] if latest else []

    ctx = _build_context(snapshots, days)
    latest_data = ctx["latest_data"]
    rt = latest_data.get("runtime_health", {})

    summary = EcosystemSynthesisEngine().synthesize(
        snapshots=snapshots,
        patterns=ctx["patterns"],
        recurring_issues=ctx["recurring"],
        runtime_health=ctx["runtime_health"],
        temporal=ctx["temporal"],
    )

    severity = SeverityEngine().assess(
        runtime_health_score=rt.get("health_score") if rt else None,
        recommendations=latest_data.get("recommendations", []),
        cost_observations=latest_data.get("cost_observations", []),
    )

    md = generate_strategic_attention_digest(
        summary=summary.to_dict(),
        severity=severity.to_dict(),
    )
    return PlainTextResponse(md, media_type="text/markdown")
