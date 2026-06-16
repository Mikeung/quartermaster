"""
LLM Usage Router — lightweight operational visibility into LLM workload behavior.

Endpoints:
  POST /llm/events          — ingest a single LLM event (optional)
  GET  /llm/summary         — full usage analysis summary
  GET  /llm/providers        — provider aggregates
  GET  /llm/workflows        — workflow aggregates
  GET  /llm/trends           — latency trends + daily totals
  GET  /llm/costs            — cost concentration report (markdown)
  GET  /llm/retention/plan   — preview LLM event retention (dry run)
  POST /llm/retention/execute — execute LLM event retention
  GET  /llm/storage          — event store storage estimate
  GET  /llm/report/provider  — provider usage report (markdown)
  GET  /llm/report/workflows — workflow economics report (markdown)
  GET  /llm/report/latency   — latency trend report (markdown)
  GET  /llm/report/tokens    — token concentration report (markdown)
  GET  /llm/report/errors    — error trend report (markdown)

Privacy guarantee:
  Payloads are run through PrivacyGuard before storage.
  Events containing prompt, response, or content fields are rejected.

This is lightweight operational visibility — not high-volume telemetry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from llm_intelligence.privacy import PrivacyGuard
from llm_intelligence.usage_analysis import UsageAnalysisEngine
from memory.llm_store import LLMEventStore
from memory.retention import LLMEventRetentionEngine, LLMEventRetentionPolicy
from reports.llm_usage import (
    generate_error_trend_report,
    generate_latency_trend_report,
    generate_provider_usage_report,
    generate_token_concentration_report,
    generate_workflow_economics_report,
)
from schemas.llm_event_schema import LLMEventValidator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm", tags=["llm-usage"])

_guard = PrivacyGuard()
_validator = LLMEventValidator()
_analysis_engine = UsageAnalysisEngine()
_retention_engine = LLMEventRetentionEngine()

_DEFAULT_WINDOW_HOURS = 168  # 7 days


def _llm_store(request: Request) -> LLMEventStore:
    store = getattr(request.app.state, "llm_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="LLM event store is not initialized. "
                   "Ensure LLMEventStore is registered in the application lifespan.",
        )
    return store


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

@router.post("/events", status_code=201)
def ingest_event(
    payload: dict,
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """
    Ingest a single LLM operational event.

    The event must NOT contain prompt, response, or content fields.
    Privacy guard runs first — oversized or content-bearing payloads are rejected.
    """
    # Privacy check
    privacy_result = _guard.check(payload)
    if not privacy_result.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Privacy guard rejected this event.",
                "rejections": privacy_result.rejections,
                "advisory": (
                    "Never store prompt text, response text, or conversation content. "
                    "Only operational metadata (tokens, latency, provider, workflow) may be stored."
                ),
            },
        )

    assert privacy_result.sanitized_payload is not None
    sanitized = privacy_result.sanitized_payload

    # Schema validation
    validation = _validator.validate(sanitized)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Event schema validation failed.",
                "violations": validation.violations,
            },
        )

    assert validation.normalized_event is not None
    event_id = store.append(validation.normalized_event)

    logger.info(
        "LLM event ingested",
        extra={
            "id": event_id,
            "provider": validation.normalized_event.provider,
            "workflow": validation.normalized_event.workflow,
        },
    )

    return {
        "status": "accepted",
        "event_id": event_id,
        "provider": validation.normalized_event.provider,
        "workflow": validation.normalized_event.workflow,
        "warnings": privacy_result.warnings,
    }


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_summary(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Full usage analysis summary for the specified time window."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)
    latency_rows = store.aggregate_latency_trend(window_hours=window_hours)
    error_rows = store.aggregate_error_trend(window_hours)

    summary = _analysis_engine.analyze(
        provider_rows=provider_rows,
        workflow_rows=workflow_rows,
        latency_trend_rows=latency_rows,
        error_trend_rows=error_rows,
        window_hours=window_hours,
    )
    return summary.to_dict()


@router.get("/providers")
def get_providers(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Provider-level token, latency, and error aggregates."""
    rows = store.aggregate_by_provider(window_hours)
    known_providers = store.list_providers()
    return {
        "window_hours": window_hours,
        "provider_count": len(rows),
        "known_providers": known_providers,
        "aggregates": rows,
    }


@router.get("/workflows")
def get_workflows(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Workflow-level token, latency, and error aggregates."""
    rows = store.aggregate_by_workflow(window_hours)
    known_workflows = store.list_workflows()
    return {
        "window_hours": window_hours,
        "workflow_count": len(rows),
        "known_workflows": known_workflows,
        "aggregates": rows,
    }


@router.get("/trends")
def get_trends(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    provider: str | None = Query(default=None),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Latency trend buckets and daily token/cost totals."""
    latency = store.aggregate_latency_trend(
        provider=provider, window_hours=window_hours
    )
    daily = store.aggregate_daily_totals(window_days=min(window_hours // 24, 90))
    return {
        "window_hours": window_hours,
        "provider_filter": provider,
        "latency_trend_buckets": latency,
        "daily_totals": daily,
    }


@router.get("/costs")
def get_costs(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Cost concentration analysis by provider and workflow."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)

    total_cost = sum(r.get("total_estimated_cost", 0) or 0 for r in provider_rows)
    total_tokens = sum(r.get("total_tokens", 0) or 0 for r in provider_rows)

    return {
        "window_hours": window_hours,
        "total_estimated_cost": round(total_cost, 6),
        "total_tokens": total_tokens,
        "cost_by_provider": [
            {
                "provider": r.get("provider"),
                "estimated_cost": round(r.get("total_estimated_cost", 0) or 0, 6),
                "tokens": r.get("total_tokens", 0),
            }
            for r in provider_rows
        ],
        "cost_by_workflow": [
            {
                "workflow": r.get("workflow"),
                "estimated_cost": round(r.get("total_estimated_cost", 0) or 0, 6),
                "tokens": r.get("total_tokens", 0),
                "cost_share": round(
                    (r.get("total_estimated_cost", 0) or 0) / max(total_cost, 1e-9), 4
                ),
            }
            for r in workflow_rows
        ],
        "advisory": "Cost estimates are derived from event data. Not authoritative billing figures.",
    }


# ---------------------------------------------------------------------------
# Storage & Retention
# ---------------------------------------------------------------------------

@router.get("/storage")
def get_storage(store: LLMEventStore = Depends(_llm_store)) -> dict:
    """LLM event store storage estimate."""
    return store.get_storage_estimate()


@router.get("/retention/plan")
def retention_plan(
    retention_days: int = Query(default=30, ge=1, le=365),
    max_event_count: int = Query(default=50_000, ge=1000),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Preview LLM event retention plan. Always dry-run (read-only)."""
    policy = LLMEventRetentionPolicy(
        retention_days=retention_days,
        max_event_count=max_event_count,
        dry_run=True,
    )
    total = store.count_events()
    oldest = store.get_oldest_event_timestamp()
    plan = _retention_engine.plan(total, oldest, policy)
    return plan.to_dict()


@router.post("/retention/execute")
def retention_execute(
    retention_days: int = Query(default=30, ge=1, le=365),
    max_event_count: int = Query(default=50_000, ge=1000),
    dry_run: bool = Query(default=True),
    store: LLMEventStore = Depends(_llm_store),
) -> dict:
    """Execute LLM event retention. Requires dry_run=false to delete."""
    policy = LLMEventRetentionPolicy(
        retention_days=retention_days,
        max_event_count=max_event_count,
        dry_run=dry_run,
    )
    total = store.count_events()
    oldest = store.get_oldest_event_timestamp()
    plan = _retention_engine.plan(total, oldest, policy)
    result = _retention_engine.execute(
        plan,
        delete_by_age_fn=store.delete_events_older_than,
        delete_by_count_fn=store.delete_events_exceeding_count,
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Markdown reports
# ---------------------------------------------------------------------------

@router.get("/report/provider", response_class=PlainTextResponse)
def report_provider(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Provider usage report (markdown)."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)
    error_rows = store.aggregate_error_trend(window_hours)
    latency_rows = store.aggregate_latency_trend(window_hours=window_hours)

    summary = _analysis_engine.analyze(
        provider_rows=provider_rows,
        workflow_rows=workflow_rows,
        latency_trend_rows=latency_rows,
        error_trend_rows=error_rows,
        window_hours=window_hours,
    )
    return generate_provider_usage_report(summary.to_dict())


@router.get("/report/workflows", response_class=PlainTextResponse)
def report_workflows(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Workflow economics report (markdown)."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)
    latency_rows = store.aggregate_latency_trend(window_hours=window_hours)
    error_rows = store.aggregate_error_trend(window_hours)

    summary = _analysis_engine.analyze(
        provider_rows=provider_rows,
        workflow_rows=workflow_rows,
        latency_trend_rows=latency_rows,
        error_trend_rows=error_rows,
        window_hours=window_hours,
    )
    return generate_workflow_economics_report(summary.to_dict())


@router.get("/report/latency", response_class=PlainTextResponse)
def report_latency(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Latency trend report (markdown)."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)
    latency_rows = store.aggregate_latency_trend(window_hours=window_hours)
    error_rows = store.aggregate_error_trend(window_hours)
    total_events = store.count_events()

    summary = _analysis_engine.analyze(
        provider_rows=provider_rows,
        workflow_rows=workflow_rows,
        latency_trend_rows=latency_rows,
        error_trend_rows=error_rows,
        window_hours=window_hours,
    )
    return generate_latency_trend_report(
        summary.to_dict().get("latency_trends", []),
        window_hours=window_hours,
        total_events=total_events,
    )


@router.get("/report/tokens", response_class=PlainTextResponse)
def report_tokens(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Token concentration report (markdown)."""
    provider_rows = store.aggregate_by_provider(window_hours)
    workflow_rows = store.aggregate_by_workflow(window_hours)
    latency_rows = store.aggregate_latency_trend(window_hours=window_hours)
    error_rows = store.aggregate_error_trend(window_hours)
    total_events = store.count_events()

    summary = _analysis_engine.analyze(
        provider_rows=provider_rows,
        workflow_rows=workflow_rows,
        latency_trend_rows=latency_rows,
        error_trend_rows=error_rows,
        window_hours=window_hours,
    )
    data = summary.to_dict()
    return generate_token_concentration_report(
        data.get("workflow_summaries", []),
        total_tokens=data.get("total_tokens", 0),
        window_hours=window_hours,
        total_events=total_events,
    )


@router.get("/report/errors", response_class=PlainTextResponse)
def report_errors(
    window_hours: int = Query(default=_DEFAULT_WINDOW_HOURS, ge=1, le=8760),
    store: LLMEventStore = Depends(_llm_store),
) -> str:
    """Error trend report (markdown)."""
    error_rows = store.aggregate_error_trend(window_hours)
    total_events = store.count_events()
    return generate_error_trend_report(
        error_rows,
        window_hours=window_hours,
        total_events=total_events,
    )
