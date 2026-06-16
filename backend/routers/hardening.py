"""
Hardening router — Phase 12 operational refinement endpoints.

Endpoints:
- GET /hardening/scaling-boundaries   — scaling readiness assessment
- GET /hardening/maintenance          — prioritized maintenance checklist
- GET /hardening/maintenance/report   — markdown maintenance report
- POST /hardening/deduplicate         — deduplicate a recommendation list
- POST /hardening/compress-evidence   — compress an evidence chain
- GET /hardening/ingestion-quality    — ingestion quality score for a project
- POST /hardening/executive-summary   — executive summary from attention report
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from cognition.deduplication import SignalDeduplicationEngine
from cognition.evidence_compression import EvidenceCompressor
from llm_intelligence.ingestion_quality import IngestionQualityScorer
from memory.llm_store import LLMEventStore
from memory.store import OperationalStore
from reports.refinement import ReportRefinementEngine
from tools.maintenance_assistant import MaintenanceAssistant
from tools.scaling_boundaries import ScalingBoundaryChecker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/hardening", tags=["hardening"])

_deduplicator = SignalDeduplicationEngine()
_compressor = EvidenceCompressor()
_quality_scorer = IngestionQualityScorer()
_refinement = ReportRefinementEngine()
_scaling_checker = ScalingBoundaryChecker()
_maintenance_assistant = MaintenanceAssistant()


def _store(request: Request) -> OperationalStore:
    return request.app.state.store


def _llm_store(request: Request) -> LLMEventStore:
    return request.app.state.llm_store


# ---------------------------------------------------------------------------
# Scaling boundaries
# ---------------------------------------------------------------------------

@router.get("/scaling-boundaries")
def scaling_boundaries(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """
    Assess whether the current operational footprint is within the recommended
    operating envelope for a single-VPS SQLite deployment.
    """
    snapshot_count = store.count_snapshots()
    llm_event_count = llm_store.count_events()
    db_size_bytes = store.get_db_size_bytes()

    report = _scaling_checker.check(
        snapshot_count=snapshot_count,
        llm_event_count=llm_event_count,
        db_size_bytes=db_size_bytes,
        avg_query_latency_ms=None,
        avg_report_latency_ms=None,
        writes_per_hour_estimate=None,
        avg_recs_per_snapshot=None,
    )
    return report.to_dict()


@router.get("/scaling-boundaries/report", response_class=PlainTextResponse)
def scaling_boundaries_report(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Scaling boundary assessment as a human-readable Markdown report."""
    snapshot_count = store.count_snapshots()
    llm_event_count = llm_store.count_events()
    db_size_bytes = store.get_db_size_bytes()

    report = _scaling_checker.check(
        snapshot_count=snapshot_count,
        llm_event_count=llm_event_count,
        db_size_bytes=db_size_bytes,
        avg_query_latency_ms=None,
        avg_report_latency_ms=None,
        writes_per_hour_estimate=None,
        avg_recs_per_snapshot=None,
    )
    return report.markdown()


# ---------------------------------------------------------------------------
# Maintenance checklist
# ---------------------------------------------------------------------------

@router.get("/maintenance")
def maintenance_checklist(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """
    Generate a prioritized maintenance checklist by aggregating signals
    from scaling boundaries and survivability checks.
    """
    snapshot_count = store.count_snapshots()
    llm_event_count = llm_store.count_events()
    db_size_bytes = store.get_db_size_bytes()

    scaling = _scaling_checker.check(
        snapshot_count=snapshot_count,
        llm_event_count=llm_event_count,
        db_size_bytes=db_size_bytes,
        avg_query_latency_ms=None,
        avg_report_latency_ms=None,
        writes_per_hour_estimate=None,
        avg_recs_per_snapshot=None,
    )

    checklist = _maintenance_assistant.generate(
        scaling_report=scaling.to_dict(),
        db_size_bytes=db_size_bytes,
    )
    return checklist.to_dict()


@router.get("/maintenance/report", response_class=PlainTextResponse)
def maintenance_report(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Maintenance checklist as a Markdown report."""
    snapshot_count = store.count_snapshots()
    llm_event_count = llm_store.count_events()
    db_size_bytes = store.get_db_size_bytes()

    scaling = _scaling_checker.check(
        snapshot_count=snapshot_count,
        llm_event_count=llm_event_count,
        db_size_bytes=db_size_bytes,
        avg_query_latency_ms=None,
        avg_report_latency_ms=None,
        writes_per_hour_estimate=None,
        avg_recs_per_snapshot=None,
    )

    checklist = _maintenance_assistant.generate(
        scaling_report=scaling.to_dict(),
        db_size_bytes=db_size_bytes,
    )
    return checklist.markdown()


# ---------------------------------------------------------------------------
# Signal deduplication
# ---------------------------------------------------------------------------

@router.post("/deduplicate")
def deduplicate_recommendations(payload: dict) -> dict:
    """
    Deduplicate a list of recommendations.

    Payload: {"recommendations": [{"title": "...", "category": "...", "confidence": 0.8, "evidence": [...]}]}

    Returns a DeduplicationSummary with collapsed concerns and statistics.
    """
    recommendations = payload.get("recommendations", [])
    if not isinstance(recommendations, list):
        raise HTTPException(status_code=422, detail="recommendations must be a list")

    result = _deduplicator.deduplicate(recommendations)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Evidence compression
# ---------------------------------------------------------------------------

@router.post("/compress-evidence")
def compress_evidence(payload: dict) -> dict:
    """
    Compress an evidence list.

    Payload: {"evidence": ["evidence string 1", "evidence string 2", ...]}

    Returns a CompressedEvidence result with readable compressed list and statistics.
    Critical, uncertainty, and conflicting evidence items are never suppressed.
    """
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        raise HTTPException(status_code=422, detail="evidence must be a list")
    if not all(isinstance(e, str) for e in evidence):
        raise HTTPException(status_code=422, detail="all evidence items must be strings")

    result = _compressor.compress(evidence)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Ingestion quality
# ---------------------------------------------------------------------------

@router.get("/ingestion-quality")
def ingestion_quality(
    project_id: str | None = Query(default=None),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """
    Compute ingestion quality score for a project (or all projects if no project_id).

    Returns an IngestionQualityReport with dimension scores and improvement suggestions.
    """
    provider_stats = llm_store.get_provider_stats(project_id=project_id)
    workflow_stats = llm_store.get_workflow_stats(project_id=project_id)
    total = llm_store.count_events(project_id=project_id)

    if total == 0:
        return {
            "quality_score": 0.0,
            "quality_band": "poor",
            "total_events_assessed": 0,
            "dimensions": [],
            "integration_warnings": ["No events have been ingested for this project."],
            "improvement_suggestions": ["Ingest LLM events to enable quality scoring."],
        }

    events_with_metadata = llm_store.count_events_with_metadata(project_id=project_id)
    events_with_error_type = llm_store.count_events_with_error_type(project_id=project_id)
    total_failures = llm_store.count_failed_events(project_id=project_id)

    report = _quality_scorer.score(
        provider_stats=provider_stats,
        workflow_stats=workflow_stats,
        total_events=total,
        events_with_metadata=events_with_metadata,
        events_with_error_type=events_with_error_type,
        total_failures=total_failures,
    )
    return report.to_dict()


@router.get("/ingestion-quality/report", response_class=PlainTextResponse)
def ingestion_quality_report(
    project_id: str | None = Query(default=None),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Ingestion quality assessment as a Markdown report."""
    provider_stats = llm_store.get_provider_stats(project_id=project_id)
    workflow_stats = llm_store.get_workflow_stats(project_id=project_id)
    total = llm_store.count_events(project_id=project_id)

    if total == 0:
        return "# Ingestion Quality Report\n\nNo events have been ingested yet."

    events_with_metadata = llm_store.count_events_with_metadata(project_id=project_id)
    events_with_error_type = llm_store.count_events_with_error_type(project_id=project_id)
    total_failures = llm_store.count_failed_events(project_id=project_id)

    report = _quality_scorer.score(
        provider_stats=provider_stats,
        workflow_stats=workflow_stats,
        total_events=total,
        events_with_metadata=events_with_metadata,
        events_with_error_type=events_with_error_type,
        total_failures=total_failures,
    )
    return report.markdown()


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

@router.post("/executive-summary")
def executive_summary(payload: dict) -> dict:
    """
    Generate an executive summary from an attention report.

    Payload: attention report dict (output of GET /temporal/attention).
    Returns an ExecutiveSummary with headline, status, key_points, and top_action.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be an attention report dict")

    summary = _refinement.executive_summary(payload)
    return summary.to_dict()
