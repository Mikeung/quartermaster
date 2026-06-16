"""
Stability API routes — schema validation, confidence, cognition validation, snapshot audit.

All endpoints are read-only and advisory.
No infrastructure modifications. No autonomous actions.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from cognition.clustering import ConcernClusteringEngine
from cognition.confidence import ConfidenceNormalizer
from cognition.synthesis import EcosystemSynthesisEngine
from cognition.systemic_drift import SystemicDriftEngine
from cognition.validation import CognitionValidator
from schemas.snapshot_schema import SCHEMA_VERSION, SnapshotValidator
from tools.snapshot_audit import SnapshotAuditor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stability", tags=["stability"])


def _snapshot_engine(request: Request):
    return request.app.state.snapshot_engine


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

@router.get("/schema/version")
def get_schema_version() -> dict[str, Any]:
    """Return the current canonical snapshot schema version."""
    return {
        "schema_version": SCHEMA_VERSION,
        "advisory": "Schema version tracks structural evolution of snapshot payloads.",
    }


@router.get("/schema/validate/latest")
def validate_latest_snapshot(
    engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Validate the latest snapshot against the canonical schema."""
    snap = engine.get_latest()
    if not snap:
        return {"valid": None, "message": "No snapshots available"}
    validator = SnapshotValidator()
    result = validator.validate(snap)
    return result.to_dict()


@router.get("/schema/validate/batch")
def validate_recent_snapshots(
    limit: int = Query(20, ge=1, le=100),
    engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Validate recent snapshots and return a batch summary."""
    snaps = engine.list_recent(limit=limit)
    validator = SnapshotValidator()
    results = validator.validate_batch(snaps)
    return {
        "summary": validator.batch_summary(results),
        "results": [r.to_dict() for r in results],
    }


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

@router.get("/confidence/explain")
def explain_confidence(
    raw: float = Query(0.8, ge=0.0, le=1.0),
    evidence_count: int = Query(3, ge=0),
    snapshot_count: int = Query(1, ge=0),
    temporal: bool = Query(False),
    recurrence: bool = Query(False),
) -> dict[str, Any]:
    """
    Explain what a confidence value means given input signals.

    Returns a normalized score with interpretation and basis notes.
    Demonstrates confidence-as-evidence-strength semantics.
    """
    normalizer = ConfidenceNormalizer()
    score = normalizer.normalize(
        raw,
        evidence_count,
        snapshot_count=snapshot_count,
        temporal_support=temporal,
        recurrence_support=recurrence,
    )
    return score.to_dict()


# ---------------------------------------------------------------------------
# Cognition validation
# ---------------------------------------------------------------------------

@router.get("/validate/synthesis")
def validate_synthesis(
    days: int = Query(30, ge=1, le=365),
    engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Run consistency validation on ecosystem synthesis from recent snapshots."""
    snaps = engine.get_temporal_window(days=days)
    if not snaps:
        return {"message": "No snapshots in window", "checks": []}

    synthesis_engine = EcosystemSynthesisEngine()
    summary = synthesis_engine.synthesize(snaps).to_dict()

    drift_engine = SystemicDriftEngine()
    drift = drift_engine.analyze(snaps).to_dict()

    clustering_engine = ConcernClusteringEngine()
    clusters = [c.to_dict() for c in clustering_engine.cluster(
        summary.get("recommendations", [])
    )]

    recs = []
    for snap in snaps:
        recs.extend(snap.get("data", {}).get("recommendations", []))

    validator = CognitionValidator()
    report = validator.run_all(
        summary=summary,
        clusters=clusters,
        drift=drift,
        recommendations=recs,
    )
    return report.to_dict()


@router.get("/validate/synthesis/report", response_class=PlainTextResponse)
def validate_synthesis_report(
    days: int = Query(30, ge=1, le=365),
    engine=Depends(_snapshot_engine),
) -> str:
    """Validation report as markdown."""
    snaps = engine.get_temporal_window(days=days)
    if not snaps:
        return "# Cognition Validation\n\nNo snapshots available."

    synthesis_engine = EcosystemSynthesisEngine()
    summary = synthesis_engine.synthesize(snaps).to_dict()

    drift_engine = SystemicDriftEngine()
    drift = drift_engine.analyze(snaps).to_dict()

    clustering_engine = ConcernClusteringEngine()
    clusters = [c.to_dict() for c in clustering_engine.cluster([])]

    recs = []
    for snap in snaps:
        recs.extend(snap.get("data", {}).get("recommendations", []))

    validator = CognitionValidator()
    report = validator.run_all(
        summary=summary,
        clusters=clusters,
        drift=drift,
        recommendations=recs,
    )
    return report.markdown()


# ---------------------------------------------------------------------------
# Snapshot audit
# ---------------------------------------------------------------------------

@router.get("/audit/snapshots")
def audit_snapshots(
    limit: int = Query(50, ge=1, le=200),
    engine=Depends(_snapshot_engine),
) -> dict[str, Any]:
    """Audit stored snapshots for integrity issues."""
    snaps = engine.list_recent(limit=limit)
    auditor = SnapshotAuditor()
    report = auditor.audit(snaps)
    return report.to_dict()


@router.get("/audit/snapshots/report", response_class=PlainTextResponse)
def audit_snapshots_report(
    limit: int = Query(50, ge=1, le=200),
    engine=Depends(_snapshot_engine),
) -> str:
    """Snapshot audit report as markdown."""
    snaps = engine.list_recent(limit=limit)
    auditor = SnapshotAuditor()
    report = auditor.audit(snaps)
    return report.markdown()
