import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from llm_intelligence.cost_intelligence import LLMCostIntelligence
from reports.generator import ReportGenerator
from reports.recommendation_engine import RecommendationEngine
from topology.builder import TopologyBuilder
from topology.workflow_inference import WorkflowInferenceEngine

router = APIRouter(prefix="/topology", tags=["topology"])
logger = logging.getLogger(__name__)


def _latest_payload(request: Request) -> dict[str, Any]:
    """Retrieve the most recent full_scan snapshot payload, or raise 404."""
    snapshot_engine = request.app.state.snapshot_engine
    latest = snapshot_engine.get_latest("full_scan")
    if not latest:
        raise HTTPException(status_code=404, detail="No scan snapshots found. Run POST /scan first.")
    return latest.get("data", {})


@router.get("/latest")
def get_latest_topology(request: Request) -> dict[str, Any]:
    """Return the topology graph from the most recent scan."""
    payload = _latest_payload(request)

    if "topology" in payload:
        return payload["topology"]

    # Recompute for older snapshots that predate topology persistence
    topology = TopologyBuilder().build_from_scan(payload)
    return topology.to_dict()


@router.get("/workflows")
def get_latest_workflows(request: Request) -> dict[str, Any]:
    """Return inferred workflows from the most recent scan."""
    payload = _latest_payload(request)

    if "workflows" in payload:
        return {"workflows": payload["workflows"], "count": len(payload["workflows"])}

    topology = TopologyBuilder().build_from_scan(payload)
    target = payload.get("target", ".")
    workflows = WorkflowInferenceEngine().infer(payload, topology, target)
    return {"workflows": [w.to_dict() for w in workflows], "count": len(workflows)}


@router.get("/recommendations")
def get_latest_recommendations(request: Request) -> dict[str, Any]:
    """Return advisory recommendations from the most recent scan."""
    payload = _latest_payload(request)

    if "recommendations" in payload:
        return {
            "recommendations": payload["recommendations"],
            "count": len(payload["recommendations"]),
        }

    topology = TopologyBuilder().build_from_scan(payload)
    target = payload.get("target", ".")
    workflows = WorkflowInferenceEngine().infer(payload, topology, target)
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)
    return {"recommendations": [r.to_dict() for r in recs], "count": len(recs)}


@router.get("/report")
def get_topology_report(request: Request) -> dict[str, Any]:
    """Return the topology markdown report from the most recent scan."""
    payload = _latest_payload(request)

    if "topology_report" in payload:
        return {"report": payload["topology_report"], "format": "markdown"}

    topology = TopologyBuilder().build_from_scan(payload)
    target = payload.get("target", ".")
    workflows = WorkflowInferenceEngine().infer(payload, topology, target)
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)

    snapshot_engine = request.app.state.snapshot_engine
    latest = snapshot_engine.get_latest("full_scan")
    snapshot_id = latest.get("id", 0) if latest else 0

    report_generator: ReportGenerator = request.app.state.report_generator
    report = report_generator.topology_report(
        topology.to_dict(), workflows, cost_obs, recs, snapshot_id
    )
    return {"report": report, "format": "markdown"}
