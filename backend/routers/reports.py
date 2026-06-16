import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/reports", tags=["reports"])
logger = logging.getLogger(__name__)


@router.get(
    "/latest",
    response_class=PlainTextResponse,
    summary="Get the latest snapshot report as markdown",
)
def latest_report(request: Request) -> str:
    s = request.app.state
    snap = s.snapshot_engine.get_latest("full_scan")
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshots found. Run a scan first.")
    return s.report_generator.snapshot_report(snap, snap.get("id", 0))


@router.get(
    "/snapshot/{snapshot_id}",
    response_class=PlainTextResponse,
    summary="Get a specific snapshot report as markdown",
)
def snapshot_report(request: Request, snapshot_id: int) -> str:
    s = request.app.state
    snap = s.snapshot_engine.get_by_id(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return s.report_generator.snapshot_report(snap, snapshot_id)
