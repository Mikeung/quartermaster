import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/snapshots", tags=["memory"])
logger = logging.getLogger(__name__)


@router.get("", summary="List recent operational snapshots")
def list_snapshots(
    request: Request, limit: int = 20, snapshot_type: str | None = None
) -> dict[str, Any]:
    engine = request.app.state.snapshot_engine
    snapshots = engine.list_recent(snapshot_type=snapshot_type, limit=min(limit, 100))
    summary = [
        {
            "id": s["id"],
            "snapshot_type": s["snapshot_type"],
            "created_at": s["created_at"],
            "notes": s["notes"],
        }
        for s in snapshots
    ]
    return {"total": len(summary), "snapshots": summary}


@router.get("/latest", summary="Get the most recent full_scan snapshot")
def latest_snapshot(request: Request) -> dict[str, Any]:
    snap = request.app.state.snapshot_engine.get_latest("full_scan")
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshots found. Run a scan first.")
    return snap


@router.get("/{snapshot_id}", summary="Get a specific snapshot by ID")
def get_snapshot(request: Request, snapshot_id: int) -> dict[str, Any]:
    snap = request.app.state.snapshot_engine.get_by_id(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return snap
