"""
Projects Router — project namespace management and per-project operational visibility.

Endpoints:
  GET  /projects                    — list all projects
  POST /projects                    — create project
  GET  /projects/{id}               — get project
  PATCH /projects/{id}              — update project fields
  POST /projects/{id}/archive       — archive project (soft)
  GET  /projects/{id}/summary       — project summary (snapshots + LLM events)
  GET  /projects/{id}/storage       — per-project storage profile
  GET  /projects/{id}/health        — ingestion health for this project
  GET  /projects/survivability      — long-running survivability report
  GET  /projects/survivability/report — markdown survivability report
  GET  /projects/pressure           — cross-project ingestion pressure summary
  GET  /projects/storage/overview   — cross-project storage distribution

Design rules:
- No RBAC, no auth
- All operations are lightweight
- Advisory + observational for analysis endpoints
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from llm_intelligence.ingestion_limits import IngestionLimitsChecker
from memory.llm_store import LLMEventStore
from memory.project_store import ProjectStore
from memory.storage_hygiene import ProjectStorageHygiene
from memory.store import OperationalStore
from schemas.project_schema import ProjectValidator
from tools.runtime_survivability import RuntimeSurvivabilityChecker, days_since

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])

_project_validator = ProjectValidator()
_ingestion_checker = IngestionLimitsChecker()
_storage_hygiene = ProjectStorageHygiene()
_survivability_checker = RuntimeSurvivabilityChecker()


def _store(request: Request) -> OperationalStore:
    return request.app.state.store


def _llm_store(request: Request) -> LLMEventStore:
    store = getattr(request.app.state, "llm_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="LLM event store not initialized")
    return store


def _project_store(request: Request) -> ProjectStore:
    store = getattr(request.app.state, "project_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Project store not initialized")
    return store


def _scheduler(request: Request):
    return getattr(request.app.state, "scheduler", None)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("")
def list_projects(
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """List all projects. Excludes archived projects by default."""
    projects = ps.list_projects(include_archived=include_archived, limit=limit)
    return {
        "projects": [p.to_dict() for p in projects],
        "count": len(projects),
        "include_archived": include_archived,
    }


@router.post("", status_code=201)
def create_project(
    payload: dict,
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """Register a new project namespace."""
    result = _project_validator.validate(payload)
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail={"error": "Project validation failed", "violations": result.violations},
        )
    assert result.normalized is not None
    project = result.normalized
    created = ps.create_project(project)
    if not created:
        raise HTTPException(
            status_code=409,
            detail=f"Project '{project.project_id}' already exists.",
        )
    logger.info("Project created via API", extra={"project_id": project.project_id})
    return {"status": "created", "project": project.to_dict()}


@router.get("/survivability")
def get_survivability(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
    ps: ProjectStore = Depends(_project_store),
    scheduler=Depends(_scheduler),
) -> dict:
    """Long-running survivability assessment."""
    report = _build_survivability_report(store, llm_store, ps, scheduler)
    return report.to_dict()


@router.get("/survivability/report", response_class=PlainTextResponse)
def get_survivability_report(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
    ps: ProjectStore = Depends(_project_store),
    scheduler=Depends(_scheduler),
) -> str:
    """Long-running survivability report (markdown)."""
    report = _build_survivability_report(store, llm_store, ps, scheduler)
    return report.markdown()


@router.get("/pressure")
def get_pressure(
    window_hours: int = Query(default=1, ge=1, le=24),
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """Cross-project ingestion pressure summary."""
    active_ids = ps.list_active_project_ids()
    statuses = []
    for pid in active_ids:
        # Count events in the past window_hours for this project
        # Use a simple count via query
        rows = llm_store.aggregate_by_workflow_project(pid, window_hours=window_hours)
        events_in_window = sum(r.get("event_count", 0) or 0 for r in rows)
        workflow_counts = {r["workflow"]: r.get("event_count", 0) for r in rows}
        status = _ingestion_checker.check_project(
            pid,
            events_last_hour=events_in_window,
            workflow_counts=workflow_counts,
        )
        statuses.append(status)

    summary = _ingestion_checker.build_pressure_summary(statuses)
    return summary.to_dict()


@router.get("/storage/overview")
def get_storage_overview(
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Cross-project storage distribution."""
    snapshot_stats = store.get_project_snapshot_stats()
    event_stats = llm_store.count_events_by_project()
    summary = _storage_hygiene.build_project_summary(snapshot_stats, event_stats)
    return summary.to_dict()


# ---------------------------------------------------------------------------
# Per-project endpoints
# ---------------------------------------------------------------------------

@router.get("/{project_id}")
def get_project(
    project_id: str,
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """Get a project by ID."""
    project = ps.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project.to_dict()


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    updates: dict,
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """Update mutable project fields."""
    if not ps.project_exists(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    updated = ps.update_project(project_id, updates)
    if not updated:
        raise HTTPException(status_code=422, detail="Update failed — no valid fields provided")
    project = ps.get_project(project_id)
    return {"status": "updated", "project": project.to_dict() if project else {}}


@router.post("/{project_id}/archive")
def archive_project(
    project_id: str,
    ps: ProjectStore = Depends(_project_store),
) -> dict:
    """Soft-archive a project. Data is preserved. Ingestion is disabled."""
    if not ps.project_exists(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    ps.archive_project(project_id)
    logger.info("Project archived via API", extra={"project_id": project_id})
    return {
        "status": "archived",
        "project_id": project_id,
        "advisory": "Data is preserved. Ingestion is now disabled for this project.",
    }


@router.get("/{project_id}/summary")
def get_project_summary(
    project_id: str,
    ps: ProjectStore = Depends(_project_store),
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Project summary — snapshot count, LLM event count, latest activity."""
    if not ps.project_exists(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    snapshot_count = store.count_snapshots_by_project(project_id)
    event_count = llm_store.count_events(project_id=project_id) if hasattr(llm_store, "count_events") else 0
    latest_snap = store.get_latest_snapshot_by_project(project_id, "operational")
    latest_event_ts = llm_store.get_latest_event_timestamp_by_project(project_id)

    latest_snap_ts = latest_snap.get("created_at") if latest_snap else None

    return ps.project_summary(
        project_id,
        snapshot_count=snapshot_count,
        llm_event_count=event_count,
        latest_snapshot_at=latest_snap_ts,
        latest_event_at=latest_event_ts,
    )


@router.get("/{project_id}/storage")
def get_project_storage(
    project_id: str,
    ps: ProjectStore = Depends(_project_store),
    store: OperationalStore = Depends(_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Per-project storage profile."""
    if not ps.project_exists(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    # Build a project-specific profile
    all_snap_stats = store.get_project_snapshot_stats()
    all_event_stats = llm_store.count_events_by_project()

    summary = _storage_hygiene.build_project_summary(all_snap_stats, all_event_stats)
    profile = next(
        (p for p in summary.project_profiles if p.project_id == project_id), None
    )
    if not profile:
        return {
            "project_id": project_id,
            "snapshot_count": 0,
            "llm_event_count": 0,
            "total_tokens": 0,
            "message": "No data found for this project.",
        }
    return profile.to_dict()


@router.get("/{project_id}/health")
def get_project_health(
    project_id: str,
    window_hours: int = Query(default=1, ge=1, le=24),
    ps: ProjectStore = Depends(_project_store),
    llm_store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Ingestion health for a specific project."""
    if not ps.project_exists(project_id):
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    rows = llm_store.aggregate_by_workflow_project(project_id, window_hours=window_hours)
    events_in_window = sum(r.get("event_count", 0) or 0 for r in rows)
    workflow_counts = {r["workflow"]: r.get("event_count", 0) for r in rows}

    status = _ingestion_checker.check_project(
        project_id,
        events_last_hour=events_in_window,
        workflow_counts=workflow_counts,
    )
    return status.to_dict()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_survivability_report(store, llm_store, ps, scheduler):
    """Gather inputs and run the survivability checker."""
    db_size = store.get_db_size_bytes()
    snapshot_count = store.count_snapshots()
    event_count = llm_store.count_events()

    # Oldest timestamps
    oldest_snap_ts = None
    snap_list = store.list_snapshots(snapshot_type=None, limit=1000)
    if snap_list:
        oldest_ts = min((s.get("created_at", "") for s in snap_list), default=None)
        oldest_snap_ts = oldest_ts

    oldest_event_days = days_since(llm_store.get_oldest_event_timestamp())
    oldest_snap_days = days_since(oldest_snap_ts) if oldest_snap_ts else None

    # Archived projects
    archived = [p for p in ps.list_projects(include_archived=True) if p.archived]
    archived_ids = [p.project_id for p in archived]
    archived_activity: dict[str, int] = {}
    for p in archived:
        # Use created_at as proxy for last activity (no last-activity tracking yet)
        d = days_since(p.created_at)
        archived_activity[p.project_id] = d or 0

    # Current ingestion rates (last hour per project)
    active_ids = ps.list_active_project_ids()
    current_rates = {}
    for pid in active_ids:
        rows = llm_store.aggregate_by_workflow_project(pid, window_hours=1)
        current_rates[pid] = sum(r.get("event_count", 0) or 0 for r in rows)

    scheduler_health = scheduler.get_health_status() if scheduler else None

    return _survivability_checker.check(
        db_size_bytes=db_size,
        db_size_bytes_7d_ago=None,  # no historical tracking yet
        snapshot_count=snapshot_count,
        oldest_snapshot_days=oldest_snap_days,
        llm_event_count=event_count,
        oldest_event_days=oldest_event_days,
        scheduler_health=scheduler_health,
        archived_project_ids=archived_ids,
        archived_project_last_activity_days=archived_activity,
        events_last_hour_by_project=current_rates,
        events_last_hour_7d_ago=None,  # no historical tracking yet
    )
