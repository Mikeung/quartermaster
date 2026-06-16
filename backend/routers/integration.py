"""
Integration Router — integration profiles, event adapter metadata, and
ingestion compatibility reporting.

Endpoints:
  GET  /integration/profiles               — list all integration profiles
  GET  /integration/profiles/{stack}       — get profile for a specific stack
  GET  /integration/check/event            — validate a sample event payload
  GET  /integration/check/batch            — validate a batch of sample events
  GET  /integration/report/readiness       — integration readiness report
  GET  /integration/report/event-quality   — event quality summary
  GET  /integration/report/sdk-guidance    — SDK usage guidance

Design rules:
- Validation only — no automatic patching
- Advisory language throughout
- Privacy gate applied to all sample event validation
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from integrations.profiles import get_profile, list_profiles, profile_names
from llm_intelligence.privacy import PrivacyGuard
from reports.integration import (
    _check_event_sample,
    generate_event_quality_summary,
    generate_integration_readiness_report,
    generate_sdk_usage_guidance,
)
from schemas.llm_event_schema import LLMEventValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integration", tags=["integration"])

_privacy_guard = PrivacyGuard()
_event_validator = LLMEventValidator()


# ---------------------------------------------------------------------------
# Integration profiles
# ---------------------------------------------------------------------------

@router.get("/profiles")
def list_integration_profiles() -> dict[str, Any]:
    """List all available integration profiles."""
    profiles = list_profiles()
    return {
        "profiles": [p.to_dict() for p in profiles],
        "available_stacks": profile_names(),
        "count": len(profiles),
    }


@router.get("/profiles/{stack}")
def get_integration_profile(stack: str) -> dict[str, Any]:
    """Get integration profile for a specific stack."""
    profile = get_profile(stack)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"No integration profile for stack '{stack}'. "
                   f"Available: {', '.join(profile_names())}",
        )
    return profile.to_dict()


# ---------------------------------------------------------------------------
# Event validation
# ---------------------------------------------------------------------------

@router.post("/check/event")
def validate_event_sample(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a single event sample against the ingestion schema.

    Runs the full validation chain: privacy guard → schema validator → field checks.
    Does NOT store the event. Purely advisory.
    """
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Privacy guard
    privacy_result = _privacy_guard.check(payload)
    if not privacy_result.allowed:
        return {
            "valid": False,
            "privacy_rejected": True,
            "rejection_reason": privacy_result.rejection_reason,
            "issues": [f"Privacy guard: {privacy_result.rejection_reason}"],
            "warnings": [],
            "advisory": "Remove forbidden fields before sending.",
        }
    if privacy_result.warnings:
        warnings.extend(privacy_result.warnings)

    # 2. Schema validation
    schema_result = _event_validator.validate(payload)
    if not schema_result.valid:
        issues.extend(schema_result.violations)

    # 3. Deep field checks
    field_issues = _check_event_sample(payload)
    issues.extend(field_issues)

    return {
        "valid": len(issues) == 0,
        "privacy_rejected": False,
        "issues": issues,
        "warnings": warnings,
        "advisory": (
            "This event appears ready for ingestion."
            if len(issues) == 0
            else "Fix the listed issues before sending."
        ),
    }


@router.post("/check/batch")
def validate_event_batch(request: Request, payload: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Validate a batch of event samples.

    Returns per-event results and a summary. Does NOT store any events.
    """
    if len(payload) > 100:
        raise HTTPException(
            status_code=422,
            detail="Batch validation limited to 100 samples at a time.",
        )

    results: list[dict[str, Any]] = []
    for i, sample in enumerate(payload):
        issues = _check_event_sample(sample)
        privacy_result = _privacy_guard.check(sample)
        event_issues = list(issues)
        if not privacy_result.allowed:
            event_issues.insert(0, f"Privacy guard: {privacy_result.rejection_reason}")
        results.append({
            "index": i,
            "workflow": sample.get("workflow", f"sample-{i}"),
            "valid": len(event_issues) == 0 and privacy_result.allowed,
            "issues": event_issues,
        })

    clean = sum(1 for r in results if r["valid"])
    return {
        "total": len(payload),
        "clean": clean,
        "flagged": len(payload) - clean,
        "results": results,
        "advisory": (
            "All samples appear ready for ingestion."
            if clean == len(payload)
            else f"{len(payload) - clean} sample(s) have issues to fix before ingestion."
        ),
    }


# ---------------------------------------------------------------------------
# Integration reports
# ---------------------------------------------------------------------------

@router.get("/report/readiness")
def integration_readiness_report(request: Request) -> dict[str, Any]:
    """JSON integration readiness report synthesizing projects, pressure, and survivability."""
    llm_store = request.app.state.llm_store
    project_store = request.app.state.project_store

    try:
        projects = project_store.list_projects(include_archived=True)
        project_dicts = [p.to_dict() for p in projects]
    except Exception:
        project_dicts = []

    try:
        storage = llm_store.get_storage_stats()
    except Exception:
        storage = {}

    report_md = generate_integration_readiness_report(
        project_profiles=project_dicts,
        ingestion_pressure_summary=None,
        survivability_report=None,
        llm_storage=storage,
    )

    return {
        "project_count": len(project_dicts),
        "llm_storage": storage,
        "report_markdown": report_md,
    }


@router.get("/report/readiness/markdown", response_class=PlainTextResponse)
def integration_readiness_report_markdown(request: Request) -> str:
    """Markdown integration readiness report."""
    project_store = request.app.state.project_store
    llm_store = request.app.state.llm_store

    try:
        projects = project_store.list_projects(include_archived=True)
        project_dicts = [p.to_dict() for p in projects]
    except Exception:
        project_dicts = []

    try:
        storage = llm_store.get_storage_stats()
    except Exception:
        storage = {}

    return generate_integration_readiness_report(
        project_profiles=project_dicts,
        ingestion_pressure_summary=None,
        survivability_report=None,
        llm_storage=storage,
    )


@router.get("/report/event-quality")
def event_quality_report(
    request: Request,
    project_id: str | None = Query(None),
) -> dict[str, Any]:
    """Event quality summary for the ingested data."""
    llm_store = request.app.state.llm_store

    try:
        provider_stats = llm_store.aggregate_by_provider(limit=50)
        workflow_stats = llm_store.aggregate_by_workflow(limit=50)
    except Exception:
        provider_stats = []
        workflow_stats = []

    report_md = generate_event_quality_summary(
        provider_stats=provider_stats,
        workflow_stats=workflow_stats,
        project_id=project_id,
    )
    return {"report": report_md}


@router.get("/report/event-quality/markdown", response_class=PlainTextResponse)
def event_quality_report_markdown(
    request: Request,
    project_id: str | None = Query(None),
) -> str:
    """Markdown event quality summary."""
    llm_store = request.app.state.llm_store
    try:
        provider_stats = llm_store.aggregate_by_provider(limit=50)
        workflow_stats = llm_store.aggregate_by_workflow(limit=50)
    except Exception:
        provider_stats = []
        workflow_stats = []

    return generate_event_quality_summary(
        provider_stats=provider_stats,
        workflow_stats=workflow_stats,
        project_id=project_id,
    )


@router.get("/report/sdk-guidance")
def sdk_guidance_report(
    request: Request,
    project_id: str = Query(..., description="Project ID to generate guidance for"),
    stack: str | None = Query(None, description="Stack name (fastapi, langchain, etc.)"),
) -> dict[str, Any]:
    """SDK usage guidance for a project and optional stack."""
    base_url = str(request.base_url).rstrip("/")
    report_md = generate_sdk_usage_guidance(
        project_id=project_id,
        base_url=base_url,
        stack=stack,
    )
    return {"project_id": project_id, "stack": stack, "report": report_md}


@router.get("/report/sdk-guidance/markdown", response_class=PlainTextResponse)
def sdk_guidance_report_markdown(
    request: Request,
    project_id: str = Query(...),
    stack: str | None = Query(None),
) -> str:
    """Markdown SDK usage guidance."""
    base_url = str(request.base_url).rstrip("/")
    return generate_sdk_usage_guidance(
        project_id=project_id,
        base_url=base_url,
        stack=stack,
    )
