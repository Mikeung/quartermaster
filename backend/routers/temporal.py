import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from cognition.attention import AttentionGuidance
from cognition.prioritization import PrioritizationEngine
from cognition.temporal_analysis import TemporalAnalysisEngine
from llm_intelligence.cost_intelligence import LLMCostIntelligence
from reports.recommendation_engine import RecommendationEngine
from reports.timeline import (
    generate_attention_report_md,
    generate_priority_report,
    generate_timeline,
    generate_volatility_report,
)
from topology.builder import TopologyBuilder
from topology.workflow_inference import WorkflowInferenceEngine

router = APIRouter(prefix="/temporal", tags=["temporal"])
logger = logging.getLogger(__name__)


def _get_snapshots(request: Request, days: int, max_count: int) -> list[dict[str, Any]]:
    """Load temporal window snapshots, raise 404 if none exist."""
    snapshots = request.app.state.snapshot_engine.get_temporal_window(
        days=days, max_count=max_count
    )
    if not snapshots:
        raise HTTPException(
            status_code=404,
            detail=f"No snapshots found in the last {days} days. Run POST /scan first.",
        )
    return snapshots


@router.get("/analysis", summary="Temporal analysis of recent scan history")
def temporal_analysis(
    request: Request,
    days: int = Query(default=7, ge=1, le=90, description="Analysis window in days"),
    max_snapshots: int = Query(default=50, ge=2, le=200),
) -> dict[str, Any]:
    """Analyze operational evolution across recent snapshots.

    Returns volatility scores, churn indicators, and trend observations.
    """
    snapshots = _get_snapshots(request, days, max_snapshots)
    analysis = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
    return analysis.to_dict()


@router.get(
    "/timeline",
    response_class=PlainTextResponse,
    summary="Operational evolution timeline as markdown",
)
def operational_timeline(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    max_snapshots: int = Query(default=100, ge=2, le=500),
) -> str:
    """Chronological timeline of infrastructure changes across all snapshots."""
    snapshots = _get_snapshots(request, days, max_snapshots)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
    return generate_timeline(snapshots, temporal)


@router.get("/priority", summary="Priority-ranked operational insights")
def operational_priority(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
) -> dict[str, Any]:
    """Priority-ranked list of operational concerns.

    Combines recommendations, cost observations, and temporal volatility
    into a single ranked list with urgency labels and scoring reasoning.
    """
    snapshots = _get_snapshots(request, days, max_snapshots)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)

    latest_snap = snapshots[-1]
    payload = latest_snap.get("data", {})

    recommendations = payload.get("recommendations", [])
    cost_observations = payload.get("cost_observations", [])
    workflows = payload.get("workflows", [])

    if not recommendations:
        topology = TopologyBuilder().build_from_scan(payload)
        target = payload.get("target", ".")
        inferred_workflows = WorkflowInferenceEngine().infer(payload, topology, target)
        cost_obs_objs = LLMCostIntelligence().observe(topology, inferred_workflows, payload)
        rec_objs = RecommendationEngine().generate(topology, inferred_workflows, cost_obs_objs, payload)
        recommendations = [r.to_dict() for r in rec_objs]
        cost_observations = [c.to_dict() for c in cost_obs_objs]
        workflows = [w.to_dict() for w in inferred_workflows]

    items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=workflows,
        temporal=temporal,
    )
    return {
        "priority_items": [i.to_dict() for i in items],
        "count": len(items),
        "temporal_volatility": temporal.volatility_score,
        "window_days": days,
    }


@router.get("/attention", summary="Attention guidance — what to care about first")
def attention_guidance(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
) -> dict[str, Any]:
    """Compressed operational attention report.

    Answers: what should the operator care about first?
    Surfaces top concerns, suppresses low-signal noise.
    """
    snapshots = _get_snapshots(request, days, max_snapshots)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)

    latest_snap = snapshots[-1]
    payload = latest_snap.get("data", {})
    recommendations = payload.get("recommendations", [])
    cost_observations = payload.get("cost_observations", [])
    workflows = payload.get("workflows", [])

    if not recommendations:
        topology = TopologyBuilder().build_from_scan(payload)
        target = payload.get("target", ".")
        inferred_workflows = WorkflowInferenceEngine().infer(payload, topology, target)
        cost_obs_objs = LLMCostIntelligence().observe(topology, inferred_workflows, payload)
        rec_objs = RecommendationEngine().generate(topology, inferred_workflows, cost_obs_objs, payload)
        recommendations = [r.to_dict() for r in rec_objs]
        cost_observations = [c.to_dict() for c in cost_obs_objs]

    items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=workflows,
        temporal=temporal,
    )
    report = AttentionGuidance().generate(items, temporal, cost_observations)
    return report.to_dict()


@router.get(
    "/attention/report",
    response_class=PlainTextResponse,
    summary="Attention guidance as markdown report",
)
def attention_report_md(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
) -> str:
    """Attention guidance as human-readable markdown."""
    snapshots = _get_snapshots(request, days, 50)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)

    latest_snap = snapshots[-1]
    payload = latest_snap.get("data", {})
    recommendations = payload.get("recommendations", [])
    cost_observations = payload.get("cost_observations", [])
    workflows = payload.get("workflows", [])

    items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=workflows,
        temporal=temporal,
    )
    report = AttentionGuidance().generate(items, temporal, cost_observations)
    return generate_attention_report_md(report.to_dict())


@router.get(
    "/volatility",
    response_class=PlainTextResponse,
    summary="Volatility and stability report as markdown",
)
def volatility_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    max_snapshots: int = Query(default=50, ge=2, le=200),
) -> str:
    """Volatility and stability report for recent scan history."""
    snapshots = _get_snapshots(request, days, max_snapshots)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)
    return generate_volatility_report(temporal)


@router.get(
    "/priority/report",
    response_class=PlainTextResponse,
    summary="Priority report as markdown",
)
def priority_report_md(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
) -> str:
    """Priority-ranked operational insights as human-readable markdown."""
    snapshots = _get_snapshots(request, days, 50)
    temporal = TemporalAnalysisEngine().analyze(snapshots, window_days=days)

    latest_snap = snapshots[-1]
    payload = latest_snap.get("data", {})
    recommendations = payload.get("recommendations", [])
    cost_observations = payload.get("cost_observations", [])
    workflows = payload.get("workflows", [])

    items = PrioritizationEngine().rank(
        recommendations=recommendations,
        cost_observations=cost_observations,
        workflows=workflows,
        temporal=temporal,
    )
    return generate_priority_report([i.to_dict() for i in items], temporal)
