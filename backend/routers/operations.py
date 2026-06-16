"""
Operations router — deployment readiness, retention, storage, and scheduler endpoints.

All endpoints are read-only by default.
Retention execution requires explicit dry_run=False parameter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.config import settings
from config.profiles import STANDARD, get_profile
from memory.retention import RetentionEngine, RetentionPolicy
from memory.snapshot_engine import SnapshotEngine
from memory.storage_hygiene import StorageHygieneEngine
from memory.store import OperationalStore
from reports.maintenance import (
    generate_deployment_readiness_report,
    generate_maintenance_report,
    generate_retention_summary,
    generate_scheduler_health_report,
    generate_storage_growth_report,
)
from schemas.snapshot_schema import SnapshotValidator
from tools.selfcheck import SystemSelfChecker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/operations", tags=["operations"])


def _store(request: Request) -> OperationalStore:
    return request.app.state.store


def _snapshot_engine(request: Request) -> SnapshotEngine:
    return request.app.state.snapshot_engine


def _scheduler(request: Request):
    return request.app.state.scheduler


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

@router.get("/selfcheck")
def selfcheck(
    store: OperationalStore = Depends(_store),
    snapshot_engine: SnapshotEngine = Depends(_snapshot_engine),
    scheduler=Depends(_scheduler),
) -> dict:
    """Run a full system self-check and return the result."""
    profile = _active_profile()

    scheduler_health = scheduler.get_health_status() if scheduler else None
    latest_snapshot = snapshot_engine.get_latest()
    snapshot_count = store.count_snapshots()

    storage_engine = StorageHygieneEngine()
    storage_est = storage_engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )

    schema_validation = None
    if latest_snapshot:
        validator = SnapshotValidator()
        result = validator.validate(latest_snapshot)
        schema_validation = {
            "valid": result.valid,
            "violations": [
                {"severity": v.severity, "field": v.field, "message": v.message}
                for v in result.violations
            ],
        }

    checker = SystemSelfChecker()
    report = checker.run(
        scheduler_health=scheduler_health,
        latest_snapshot=latest_snapshot,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
        storage_estimate=storage_est.to_dict(),
        schema_validation=schema_validation,
    )
    return report.to_dict()


@router.get("/selfcheck/report")
def selfcheck_report(
    store: OperationalStore = Depends(_store),
    snapshot_engine: SnapshotEngine = Depends(_snapshot_engine),
    scheduler=Depends(_scheduler),
) -> dict:
    """Run self-check and return a full markdown maintenance report."""
    profile = _active_profile()
    scheduler_health = scheduler.get_health_status() if scheduler else None
    latest_snapshot = snapshot_engine.get_latest()
    snapshot_count = store.count_snapshots()

    storage_engine = StorageHygieneEngine()
    storage_est = storage_engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )

    checker = SystemSelfChecker()
    selfcheck_data = checker.run(
        scheduler_health=scheduler_health,
        latest_snapshot=latest_snapshot,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
        storage_estimate=storage_est.to_dict(),
    ).to_dict()

    report_md = generate_maintenance_report(
        selfcheck=selfcheck_data,
        storage=storage_est.to_dict(),
        scheduler=scheduler_health,
    )
    return {"report": report_md, "selfcheck": selfcheck_data}


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

@router.get("/retention")
def retention_preview(
    dry_run: bool = Query(True, description="Always true for GET — preview only"),
    retention_days: int | None = Query(None),
    max_snapshot_count: int | None = Query(None),
    store: OperationalStore = Depends(_store),
) -> dict:
    """Preview what retention would delete (dry run only)."""
    profile = _active_profile()
    policy = RetentionPolicy(
        retention_days=retention_days or profile.retention_days,
        max_snapshot_count=max_snapshot_count or profile.max_snapshot_count,
        min_keep_count=profile.min_keep_count,
        dry_run=True,  # GET is always dry-run
    )

    snapshots = store.list_snapshots(snapshot_type=None, limit=10000)
    engine = RetentionEngine()
    plan = engine.plan(snapshots, policy)
    return plan.to_dict()


@router.post("/retention/execute")
def retention_execute(
    dry_run: bool = Query(True, description="Set to false to actually delete snapshots"),
    retention_days: int | None = Query(None),
    max_snapshot_count: int | None = Query(None),
    store: OperationalStore = Depends(_store),
) -> dict:
    """Execute retention. Set dry_run=false to delete snapshots."""
    profile = _active_profile()
    policy = RetentionPolicy(
        retention_days=retention_days or profile.retention_days,
        max_snapshot_count=max_snapshot_count or profile.max_snapshot_count,
        min_keep_count=profile.min_keep_count,
        dry_run=dry_run,
    )

    snapshots = store.list_snapshots(snapshot_type=None, limit=10000)
    engine = RetentionEngine()
    result = engine.plan_and_execute(
        snapshots=snapshots,
        policy=policy,
        delete_fn=store.delete_snapshots_by_ids,
    )
    logger.info(
        "Retention requested via API",
        extra={"dry_run": dry_run, "message": result.message},
    )
    return result.to_dict()


@router.get("/retention/report")
def retention_report(
    store: OperationalStore = Depends(_store),
) -> dict:
    """Generate a retention summary report in markdown."""
    profile = _active_profile()
    policy = RetentionPolicy(
        retention_days=profile.retention_days,
        max_snapshot_count=profile.max_snapshot_count,
        min_keep_count=profile.min_keep_count,
        dry_run=True,
    )
    snapshots = store.list_snapshots(snapshot_type=None, limit=10000)
    engine = RetentionEngine()
    result = engine.plan_and_execute(
        snapshots=snapshots,
        policy=policy,
        delete_fn=store.delete_snapshots_by_ids,
    )
    report_md = generate_retention_summary(result.to_dict())
    return {"report": report_md, "result": result.to_dict()}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

@router.get("/storage")
def storage_estimate(
    store: OperationalStore = Depends(_store),
) -> dict:
    """Return current storage pressure estimate."""
    profile = _active_profile()
    snapshot_count = store.count_snapshots()
    engine = StorageHygieneEngine()
    est = engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )
    return est.to_dict()


@router.get("/storage/report")
def storage_report(
    store: OperationalStore = Depends(_store),
) -> dict:
    """Return a markdown storage growth report."""
    profile = _active_profile()
    snapshot_count = store.count_snapshots()
    engine = StorageHygieneEngine()
    est = engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )
    report_md = generate_storage_growth_report(current=est.to_dict())
    return {"report": report_md, "storage": est.to_dict()}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@router.get("/scheduler")
def scheduler_health(scheduler=Depends(_scheduler)) -> dict:
    """Return scheduler health status."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    return scheduler.get_health_status()


@router.get("/scheduler/report")
def scheduler_health_report(scheduler=Depends(_scheduler)) -> dict:
    """Return a markdown scheduler health report."""
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not available")
    health = scheduler.get_health_status()
    report_md = generate_scheduler_health_report(health)
    return {"report": report_md, "health": health}


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@router.get("/readiness")
def readiness(
    profile_name: str = Query("standard"),
    store: OperationalStore = Depends(_store),
    snapshot_engine: SnapshotEngine = Depends(_snapshot_engine),
    scheduler=Depends(_scheduler),
) -> dict:
    """Return a deployment readiness assessment."""
    profile = _get_named_profile(profile_name)
    scheduler_health = scheduler.get_health_status() if scheduler else None
    latest_snapshot = snapshot_engine.get_latest()
    snapshot_count = store.count_snapshots()

    storage_engine = StorageHygieneEngine()
    storage_est = storage_engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )

    checker = SystemSelfChecker()
    selfcheck_data = checker.run(
        scheduler_health=scheduler_health,
        latest_snapshot=latest_snapshot,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
        storage_estimate=storage_est.to_dict(),
    ).to_dict()

    return {
        "overall_status": selfcheck_data["overall_status"],
        "profile": profile_name,
        "selfcheck": selfcheck_data,
    }


@router.get("/readiness/report")
def readiness_report(
    profile_name: str = Query("standard"),
    store: OperationalStore = Depends(_store),
    snapshot_engine: SnapshotEngine = Depends(_snapshot_engine),
    scheduler=Depends(_scheduler),
) -> dict:
    """Return a markdown deployment readiness report."""
    profile = _get_named_profile(profile_name)
    scheduler_health = scheduler.get_health_status() if scheduler else None
    latest_snapshot = snapshot_engine.get_latest()
    snapshot_count = store.count_snapshots()

    storage_engine = StorageHygieneEngine()
    storage_est = storage_engine.estimate(
        db_path=settings.db_path,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
    )

    checker = SystemSelfChecker()
    selfcheck_data = checker.run(
        scheduler_health=scheduler_health,
        latest_snapshot=latest_snapshot,
        snapshot_count=snapshot_count,
        max_snapshot_count=profile.max_snapshot_count,
        storage_estimate=storage_est.to_dict(),
    ).to_dict()

    report_md = generate_deployment_readiness_report(
        selfcheck=selfcheck_data,
        profile_name=profile_name,
        profile_info=profile.to_dict(),
    )
    return {"report": report_md, "selfcheck": selfcheck_data}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
def active_profile(profile_name: str = Query("standard")) -> dict:
    """Return the active deployment profile configuration."""
    return _get_named_profile(profile_name).to_dict()


@router.get("/profiles")
def list_profiles_endpoint() -> dict:
    """Return all available deployment profiles."""
    from config.profiles import list_profiles
    return {
        "profiles": [p.to_dict() for p in list_profiles()],
        "default": "standard",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _active_profile():
    return STANDARD


def _get_named_profile(name: str):
    try:
        return get_profile(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
