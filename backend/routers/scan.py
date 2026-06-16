import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.operations import run_full_scan

router = APIRouter(prefix="/scan", tags=["scanning"])
logger = logging.getLogger(__name__)


class ScanRequest(BaseModel):
    target: str = "."


@router.post("", summary="Trigger a full operational scan")
def trigger_scan(request: Request, body: ScanRequest) -> dict[str, Any]:
    s = request.app.state
    result = run_full_scan(
        target=body.target,
        registry=s.registry,
        snapshot_engine=s.snapshot_engine,
        drift_detector=s.drift_detector,
        report_generator=s.report_generator,
    )
    return {
        "snapshot_id": result["snapshot_id"],
        "target": result["target"],
        "duration_s": result["duration_s"],
        "llm_providers_detected": [d["provider"] for d in result["llm_detections"]],
        "drift_changes": result["drift"]["change_count"] if result["drift"] else 0,
        "drift_summary": result["drift"]["summary"] if result["drift"] else None,
        "drift_human_readable": (result["drift"]["human_readable"] if result["drift"] else []),
    }


@router.get("/status", summary="List registered scanners and scheduled jobs")
def scan_status(request: Request) -> dict[str, Any]:
    s = request.app.state
    return {
        "registered_scanners": s.registry.registered,
        "scheduled_jobs": s.scheduler.get_jobs_info(),
    }
