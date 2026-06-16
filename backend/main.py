from fastapi import FastAPI

from backend.config import settings
from backend.health import router as health_router
from backend.lifecycle import lifespan
from backend.routers.ecosystem import router as ecosystem_router
from backend.routers.hardening import router as hardening_router
from backend.routers.integration import router as integration_router
from backend.routers.investigation import router as investigation_router
from backend.routers.llm_usage import router as llm_usage_router
from backend.routers.operations import router as operations_router
from backend.routers.projects import router as projects_router
from backend.routers.reports import router as reports_router
from backend.routers.runtime import router as runtime_router
from backend.routers.scan import router as scan_router
from backend.routers.snapshots import router as snapshots_router
from backend.routers.stability import router as stability_router
from backend.routers.temporal import router as temporal_router
from backend.routers.topology import router as topology_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Operational intelligence and memory layer for AI agent ecosystems.",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(scan_router)
app.include_router(snapshots_router)
app.include_router(reports_router)
app.include_router(topology_router)
app.include_router(temporal_router)
app.include_router(runtime_router)
app.include_router(investigation_router)
app.include_router(ecosystem_router)
app.include_router(stability_router)
app.include_router(operations_router)
app.include_router(llm_usage_router)
app.include_router(projects_router)
app.include_router(integration_router)
app.include_router(hardening_router)


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
        "philosophy": "Observe automatically. Decide manually.",
        "endpoints": {
            "health": "GET /health",
            "scan": "POST /scan",
            "scan_status": "GET /scan/status",
            "snapshots": "GET /snapshots",
            "latest_snapshot": "GET /snapshots/latest",
            "latest_report": "GET /reports/latest",
            "topology": "GET /topology/latest",
            "workflows": "GET /topology/workflows",
            "recommendations": "GET /topology/recommendations",
            "topology_report": "GET /topology/report",
            "temporal_analysis": "GET /temporal/analysis",
            "temporal_timeline": "GET /temporal/timeline",
            "temporal_priority": "GET /temporal/priority",
            "temporal_attention": "GET /temporal/attention",
            "temporal_volatility": "GET /temporal/volatility",
            "runtime_health": "GET /runtime/health",
            "runtime_severity": "GET /runtime/severity",
            "runtime_recurrence": "GET /runtime/recurrence",
            "runtime_fused": "GET /runtime/fused",
            "runtime_digest": "GET /runtime/digest",
            "runtime_digest_morning": "GET /runtime/digest/morning",
            "runtime_digest_critical": "GET /runtime/digest/critical",
            "investigate": "GET /investigation/investigate",
            "investigate_report": "GET /investigation/investigate/report",
            "compare": "GET /investigation/compare",
            "compare_report": "GET /investigation/compare/report",
            "continuity": "GET /investigation/continuity",
            "continuity_report": "GET /investigation/continuity/report",
            "patterns": "GET /investigation/patterns",
            "explain_severity": "GET /investigation/explain/severity",
            "explain_recommendation": "GET /investigation/explain/recommendation",
            "evidence_recommendation": "GET /investigation/evidence/recommendation",
            "evidence_severity": "GET /investigation/evidence/severity",
            "persistent_report": "GET /investigation/report/persistent",
            "ecosystem_summary": "GET /ecosystem/summary",
            "ecosystem_themes": "GET /ecosystem/themes",
            "ecosystem_clusters": "GET /ecosystem/clusters",
            "ecosystem_drift": "GET /ecosystem/drift",
            "ecosystem_trends": "GET /ecosystem/trends",
            "ecosystem_review": "GET /ecosystem/review",
            "ecosystem_report_themes": "GET /ecosystem/report/themes",
            "ecosystem_report_concerns": "GET /ecosystem/report/concerns",
            "ecosystem_report_drift": "GET /ecosystem/report/drift",
            "ecosystem_report_complexity": "GET /ecosystem/report/complexity",
            "ecosystem_digest_weekly": "GET /ecosystem/digest/weekly",
            "ecosystem_digest_strategic": "GET /ecosystem/digest/strategic",
            "schema_version": "GET /stability/schema/version",
            "schema_validate_latest": "GET /stability/schema/validate/latest",
            "schema_validate_batch": "GET /stability/schema/validate/batch",
            "confidence_explain": "GET /stability/confidence/explain",
            "validate_synthesis": "GET /stability/validate/synthesis",
            "validate_synthesis_report": "GET /stability/validate/synthesis/report",
            "audit_snapshots": "GET /stability/audit/snapshots",
            "audit_snapshots_report": "GET /stability/audit/snapshots/report",
            "selfcheck": "GET /operations/selfcheck",
            "retention_preview": "GET /operations/retention",
            "retention_execute": "POST /operations/retention/execute",
            "storage": "GET /operations/storage",
            "scheduler_health": "GET /operations/scheduler",
            "readiness": "GET /operations/readiness",
            "readiness_report": "GET /operations/readiness/report",
            "active_profile": "GET /operations/profile",
            "list_profiles": "GET /operations/profiles",
            "llm_ingest": "POST /llm/events",
            "llm_summary": "GET /llm/summary",
            "llm_providers": "GET /llm/providers",
            "llm_workflows": "GET /llm/workflows",
            "llm_trends": "GET /llm/trends",
            "llm_costs": "GET /llm/costs",
            "llm_storage": "GET /llm/storage",
            "llm_retention_plan": "GET /llm/retention/plan",
            "llm_retention_execute": "POST /llm/retention/execute",
            "llm_report_provider": "GET /llm/report/provider",
            "llm_report_workflows": "GET /llm/report/workflows",
            "llm_report_latency": "GET /llm/report/latency",
            "llm_report_tokens": "GET /llm/report/tokens",
            "llm_report_errors": "GET /llm/report/errors",
            "list_projects": "GET /projects",
            "create_project": "POST /projects",
            "get_project": "GET /projects/{id}",
            "update_project": "PATCH /projects/{id}",
            "archive_project": "POST /projects/{id}/archive",
            "project_summary": "GET /projects/{id}/summary",
            "project_storage": "GET /projects/{id}/storage",
            "project_health": "GET /projects/{id}/health",
            "survivability": "GET /projects/survivability",
            "survivability_report": "GET /projects/survivability/report",
            "ingestion_pressure": "GET /projects/pressure",
            "storage_overview": "GET /projects/storage/overview",
            "integration_profiles": "GET /integration/profiles",
            "integration_profile": "GET /integration/profiles/{stack}",
            "integration_check_event": "POST /integration/check/event",
            "integration_check_batch": "POST /integration/check/batch",
            "integration_readiness": "GET /integration/report/readiness",
            "integration_event_quality": "GET /integration/report/event-quality",
            "integration_sdk_guidance": "GET /integration/report/sdk-guidance",
            "scaling_boundaries": "GET /hardening/scaling-boundaries",
            "scaling_boundaries_report": "GET /hardening/scaling-boundaries/report",
            "maintenance_checklist": "GET /hardening/maintenance",
            "maintenance_report": "GET /hardening/maintenance/report",
            "deduplicate": "POST /hardening/deduplicate",
            "compress_evidence": "POST /hardening/compress-evidence",
            "ingestion_quality": "GET /hardening/ingestion-quality",
            "ingestion_quality_report": "GET /hardening/ingestion-quality/report",
            "executive_summary": "POST /hardening/executive-summary",
        },
    }
