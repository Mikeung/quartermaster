import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cognition.runtime_health import RuntimeHealthIntelligence
from llm_intelligence.cost_intelligence import LLMCostIntelligence
from llm_intelligence.detector import LLMDetector
from memory.drift_detector import DriftDetector
from memory.snapshot_engine import SnapshotEngine
from reports.generator import ReportGenerator
from reports.recommendation_engine import RecommendationEngine
from scanners.registry import ScannerRegistry
from topology.builder import TopologyBuilder
from topology.workflow_inference import WorkflowInferenceEngine

if TYPE_CHECKING:
    from memory.finding_store import FindingStore

logger = logging.getLogger(__name__)


def run_full_scan(
    target: str,
    registry: ScannerRegistry,
    snapshot_engine: SnapshotEngine,
    drift_detector: DriftDetector,
    report_generator: ReportGenerator,
    finding_store: "FindingStore | None" = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    logger.info("Full scan starting", extra={"target": target})

    scan_output = registry.run_all(target)
    llm_result = LLMDetector().scan_directory(target)

    payload: dict[str, Any] = {
        "target": target,
        "scanned_at": datetime.now(UTC).isoformat(),
        "scanner_results": scan_output,
        "llm_detections": llm_result,
    }

    # Topology intelligence
    topology = TopologyBuilder().build_from_scan(payload)
    workflows = WorkflowInferenceEngine().infer(payload, topology, target)
    cost_observations = LLMCostIntelligence().observe(topology, workflows, payload)
    recommendations = RecommendationEngine().generate(
        topology, workflows, cost_observations, payload,
        finding_store=finding_store,
        target_id=target,
    )

    payload["topology"] = topology.to_dict()
    payload["workflows"] = [w.to_dict() for w in workflows]
    payload["cost_observations"] = [c.to_dict() for c in cost_observations]
    payload["recommendations"] = [r.to_dict() for r in recommendations]

    # Runtime health intelligence from scanner results
    runtime_state = (
        scan_output.get("results", {}).get("runtime_scanner", {})
    )
    runtime_health = RuntimeHealthIntelligence().assess(runtime_state)
    payload["runtime_health"] = runtime_health.to_dict()

    # Target-scoped snapshot lookup.
    # Cross-target comparison is structurally invalid: comparing /srv/hdt-web
    # to /srv/telegram-humint produces guaranteed noise (different languages,
    # file counts, frameworks). Only snapshots for the same target_id are valid
    # comparison candidates. get_latest_for_target() enforces this at the DB level.
    previous = snapshot_engine.get_latest_for_target(target, "full_scan")

    if previous is None:
        logger.info(
            "Drift skip: no prior snapshot for target=%s — baseline will be established",
            target,
        )
    else:
        prev_target = previous.get("data", {}).get("target", "<unknown>")
        if prev_target != target:
            # Defense-in-depth: store returned a mismatched target.
            # Should not occur after migration, but refuse comparison if it does.
            logger.warning(
                "Drift skip: target mismatch in retrieved snapshot — "
                "expected=%s got=%s snapshot_id=%s — cross-target comparison refused",
                target,
                prev_target,
                previous.get("id"),
            )
            previous = None
        else:
            logger.info(
                "Drift comparison: target=%s previous_snapshot_id=%s captured_at=%s",
                target,
                previous.get("id"),
                previous.get("created_at", "unknown"),
            )

    snapshot_id = snapshot_engine.create_snapshot(payload, "full_scan", target_id=target)

    drift: dict[str, Any] | None = None
    drift_report: str | None = None

    if previous:
        prev_id = previous.get("id", 0)
        drift = drift_detector.compare(previous.get("data", {}), payload)
        if drift["change_count"] > 0:
            drift_report = report_generator.drift_report(drift, prev_id, snapshot_id)
        logger.info(
            "Drift detection complete",
            extra={"change_count": drift["change_count"], "target": target},
        )

    snapshot_report = report_generator.snapshot_report({"data": payload}, snapshot_id)
    topology_report = report_generator.topology_report(
        topology.to_dict(), workflows, cost_observations, recommendations, snapshot_id
    )

    duration = round(time.monotonic() - t0, 3)
    payload["duration_s"] = duration

    result: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "target": target,
        "scan_output": scan_output,
        "llm_detections": llm_result,
        "topology": topology.to_dict(),
        "workflows": [w.to_dict() for w in workflows],
        "cost_observations": [c.to_dict() for c in cost_observations],
        "recommendations": [r.to_dict() for r in recommendations],
        "drift": drift,
        "snapshot_report": snapshot_report,
        "topology_report": topology_report,
        "drift_report": drift_report,
        "runtime_health": runtime_health.to_dict(),
        "duration_s": duration,
    }

    logger.info(
        "Full scan complete",
        extra={
            "snapshot_id": snapshot_id,
            "target": target,
            "duration_s": duration,
            "drift_changes": drift["change_count"] if drift else 0,
            "llm_providers": [d["provider"] for d in llm_result],
            "topology_nodes": topology.to_dict()["node_count"],
            "topology_edges": topology.to_dict()["edge_count"],
            "inferred_workflows": len(workflows),
            "recommendations": len(recommendations),
            "runtime_status": runtime_health.overall_status,
        },
    )
    return result
