"""
LLM Operational Usage Analysis — deterministic aggregation-oriented analysis.

Generates:
- Provider usage summaries
- Workflow token concentration
- Latency trend summaries
- Error-rate summaries
- Workflow cost concentration
- Provider fragmentation indicators
- High-cost workflow indicators

Design rules:
- Deterministic: same input → same output
- Bounded: all inputs are pre-aggregated, not raw event streams
- Explainable: every observation includes evidence
- No predictive optimization
- Correlation is allowed. Certainty is not.
- Bounded language: "appears", "suggests", "historically"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_HIGH_ERROR_RATE_THRESHOLD = 0.10        # 10%+ error rate is noteworthy
_LATENCY_INCREASE_THRESHOLD_PCT = 0.25   # 25% latency increase flags a trend
_TOKEN_CONCENTRATION_THRESHOLD = 0.60    # single workflow consuming 60%+ of tokens
_COST_CONCENTRATION_THRESHOLD = 0.60     # single workflow consuming 60%+ of cost
_PROVIDER_FRAGMENTATION_THRESHOLD = 4    # 4+ active providers is notable
_HIGH_COST_WORKFLOW_TOKEN_THRESHOLD = 50_000  # workflow with 50k+ tokens is high-cost candidate


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@dataclass
class ProviderSummary:
    provider: str
    event_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    avg_latency_ms: float
    max_latency_ms: float
    error_count: int
    error_rate: float
    total_estimated_cost: float
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "event_count": self.event_count,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "max_latency_ms": round(self.max_latency_ms, 1),
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "total_estimated_cost": round(self.total_estimated_cost, 6),
            "observations": self.observations,
        }


@dataclass
class WorkflowSummary:
    workflow: str
    event_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    avg_latency_ms: float
    error_count: int
    error_rate: float
    total_estimated_cost: float
    token_share: float        # fraction of total tokens in window
    cost_share: float         # fraction of total cost in window
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "event_count": self.event_count,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "total_estimated_cost": round(self.total_estimated_cost, 6),
            "token_share": round(self.token_share, 4),
            "cost_share": round(self.cost_share, 4),
            "observations": self.observations,
        }


@dataclass
class LatencyTrendSummary:
    provider: str | None
    window_hours: int
    trend_direction: str     # "stable" | "increasing" | "decreasing" | "insufficient_data"
    avg_latency_ms: float
    max_latency_ms: float
    bucket_count: int
    observations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "window_hours": self.window_hours,
            "trend_direction": self.trend_direction,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "max_latency_ms": round(self.max_latency_ms, 1),
            "bucket_count": self.bucket_count,
            "observations": self.observations,
        }


@dataclass
class UsageAnalysisSummary:
    """Top-level output from UsageAnalysisEngine."""

    window_hours: int
    total_events: int
    total_tokens: int
    total_estimated_cost: float
    provider_summaries: list[ProviderSummary]
    workflow_summaries: list[WorkflowSummary]
    latency_trends: list[LatencyTrendSummary]
    high_cost_workflows: list[str]
    fragmented_providers: list[str]
    error_trend: list[dict[str, Any]]
    system_observations: list[str]
    confidence_note: str = (
        "Analysis is based on ingested event data only. "
        "Confidence reflects event coverage, not billing accuracy."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_hours": self.window_hours,
            "total_events": self.total_events,
            "total_tokens": self.total_tokens,
            "total_estimated_cost": round(self.total_estimated_cost, 6),
            "provider_summaries": [p.to_dict() for p in self.provider_summaries],
            "workflow_summaries": [w.to_dict() for w in self.workflow_summaries],
            "latency_trends": [l.to_dict() for l in self.latency_trends],
            "high_cost_workflows": self.high_cost_workflows,
            "fragmented_providers": self.fragmented_providers,
            "error_trend": self.error_trend,
            "system_observations": self.system_observations,
            "confidence_note": self.confidence_note,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class UsageAnalysisEngine:
    """
    Generates deterministic operational summaries from pre-aggregated event data.

    Accepts aggregate rows from LLMEventStore (not raw events).
    All analysis is statistical observation, not causal inference.
    """

    def analyze(
        self,
        *,
        provider_rows: list[dict[str, Any]],
        workflow_rows: list[dict[str, Any]],
        latency_trend_rows: list[dict[str, Any]],
        error_trend_rows: list[dict[str, Any]],
        window_hours: int = 168,
    ) -> UsageAnalysisSummary:
        total_tokens = sum(r.get("total_tokens", 0) or 0 for r in provider_rows)
        total_cost = sum(r.get("total_estimated_cost", 0) or 0 for r in provider_rows)
        total_events = sum(r.get("event_count", 0) or 0 for r in provider_rows)
        total_wf_tokens = sum(r.get("total_tokens", 0) or 0 for r in workflow_rows)
        total_wf_cost = sum(r.get("total_estimated_cost", 0) or 0 for r in workflow_rows)

        provider_summaries = self._build_provider_summaries(provider_rows)
        workflow_summaries = self._build_workflow_summaries(
            workflow_rows, total_wf_tokens, total_wf_cost
        )
        latency_trends = self._build_latency_trends(latency_trend_rows, window_hours)
        high_cost = self._find_high_cost_workflows(workflow_summaries)
        fragmented = self._check_provider_fragmentation(provider_summaries)
        system_obs = self._build_system_observations(
            provider_summaries, workflow_summaries, latency_trends, high_cost, fragmented
        )

        logger.info(
            "Usage analysis complete",
            extra={
                "total_events": total_events,
                "total_tokens": total_tokens,
                "providers": len(provider_summaries),
                "workflows": len(workflow_summaries),
            },
        )

        return UsageAnalysisSummary(
            window_hours=window_hours,
            total_events=total_events,
            total_tokens=total_tokens,
            total_estimated_cost=total_cost,
            provider_summaries=provider_summaries,
            workflow_summaries=workflow_summaries,
            latency_trends=latency_trends,
            high_cost_workflows=high_cost,
            fragmented_providers=fragmented,
            error_trend=error_trend_rows,
            system_observations=system_obs,
        )

    # -----------------------------------------------------------------------
    # Provider summaries
    # -----------------------------------------------------------------------

    def _build_provider_summaries(
        self, rows: list[dict[str, Any]]
    ) -> list[ProviderSummary]:
        summaries = []
        for r in rows:
            event_count = int(r.get("event_count", 0) or 0)
            error_count = int(r.get("error_count", 0) or 0)
            error_rate = error_count / max(event_count, 1)
            observations = []

            if error_rate >= _HIGH_ERROR_RATE_THRESHOLD:
                observations.append(
                    f"Error rate of {error_rate:.1%} historically associated with "
                    "provider reliability issues or quota exhaustion."
                )

            avg_latency = float(r.get("avg_latency_ms", 0) or 0)
            if avg_latency > 5_000:
                observations.append(
                    f"Average latency {avg_latency:.0f}ms appears elevated — "
                    "may correlate with model size, load, or network conditions."
                )

            summaries.append(ProviderSummary(
                provider=str(r.get("provider", "unknown")),
                event_count=event_count,
                total_tokens=int(r.get("total_tokens", 0) or 0),
                prompt_tokens=int(r.get("prompt_tokens", 0) or 0),
                completion_tokens=int(r.get("completion_tokens", 0) or 0),
                avg_latency_ms=avg_latency,
                max_latency_ms=float(r.get("max_latency_ms", 0) or 0),
                error_count=error_count,
                error_rate=error_rate,
                total_estimated_cost=float(r.get("total_estimated_cost", 0) or 0),
                observations=observations,
            ))
        return summaries

    # -----------------------------------------------------------------------
    # Workflow summaries
    # -----------------------------------------------------------------------

    def _build_workflow_summaries(
        self,
        rows: list[dict[str, Any]],
        total_tokens: int,
        total_cost: float,
    ) -> list[WorkflowSummary]:
        summaries = []
        for r in rows:
            event_count = int(r.get("event_count", 0) or 0)
            error_count = int(r.get("error_count", 0) or 0)
            error_rate = error_count / max(event_count, 1)
            wf_tokens = int(r.get("total_tokens", 0) or 0)
            wf_cost = float(r.get("total_estimated_cost", 0) or 0)
            token_share = wf_tokens / max(total_tokens, 1)
            cost_share = wf_cost / max(total_cost, 1e-9)

            observations = []
            if token_share >= _TOKEN_CONCENTRATION_THRESHOLD:
                observations.append(
                    f"This workflow accounts for {token_share:.1%} of total tokens — "
                    "high token concentration historically correlates with cost spikes."
                )
            if error_rate >= _HIGH_ERROR_RATE_THRESHOLD:
                observations.append(
                    f"Error rate {error_rate:.1%} — appears elevated for this workflow. "
                    "Retry patterns may compound token waste."
                )
            avg_lat = float(r.get("avg_latency_ms", 0) or 0)
            if avg_lat > 10_000:
                observations.append(
                    f"Average latency {avg_lat:.0f}ms suggests this workflow may involve "
                    "multi-step chaining or large context windows."
                )

            summaries.append(WorkflowSummary(
                workflow=str(r.get("workflow", "unknown")),
                event_count=event_count,
                total_tokens=wf_tokens,
                prompt_tokens=int(r.get("prompt_tokens", 0) or 0),
                completion_tokens=int(r.get("completion_tokens", 0) or 0),
                avg_latency_ms=avg_lat,
                error_count=error_count,
                error_rate=error_rate,
                total_estimated_cost=wf_cost,
                token_share=token_share,
                cost_share=cost_share,
                observations=observations,
            ))
        return summaries

    # -----------------------------------------------------------------------
    # Latency trends
    # -----------------------------------------------------------------------

    def _build_latency_trends(
        self,
        trend_rows: list[dict[str, Any]],
        window_hours: int,
    ) -> list[LatencyTrendSummary]:
        if not trend_rows:
            return [LatencyTrendSummary(
                provider=None,
                window_hours=window_hours,
                trend_direction="insufficient_data",
                avg_latency_ms=0.0,
                max_latency_ms=0.0,
                bucket_count=0,
                observations=["No latency trend data available for this window."],
            )]

        latencies = [float(r.get("avg_latency_ms", 0) or 0) for r in trend_rows]
        overall_avg = sum(latencies) / max(len(latencies), 1)
        overall_max = max(latencies) if latencies else 0.0

        trend_direction = _compute_trend_direction(latencies)
        observations = []

        if trend_direction == "increasing":
            observations.append(
                "Latency appears to be increasing over this window — "
                "may correlate with provider load, model changes, or growing context sizes."
            )
        elif trend_direction == "decreasing":
            observations.append("Latency appears to be decreasing over this window.")
        else:
            observations.append("Latency appears stable over this window.")

        if overall_max > 30_000:
            observations.append(
                f"Peak latency reached {overall_max:.0f}ms — "
                "spikes of this magnitude may indicate provider timeouts or cold starts."
            )

        return [LatencyTrendSummary(
            provider=None,
            window_hours=window_hours,
            trend_direction=trend_direction,
            avg_latency_ms=overall_avg,
            max_latency_ms=overall_max,
            bucket_count=len(trend_rows),
            observations=observations,
        )]

    # -----------------------------------------------------------------------
    # Pattern detectors
    # -----------------------------------------------------------------------

    def _find_high_cost_workflows(
        self, summaries: list[WorkflowSummary]
    ) -> list[str]:
        return [
            s.workflow
            for s in summaries
            if s.total_tokens >= _HIGH_COST_WORKFLOW_TOKEN_THRESHOLD
            or s.token_share >= _TOKEN_CONCENTRATION_THRESHOLD
        ]

    def _check_provider_fragmentation(
        self, summaries: list[ProviderSummary]
    ) -> list[str]:
        active = [s.provider for s in summaries if s.event_count > 0]
        if len(active) >= _PROVIDER_FRAGMENTATION_THRESHOLD:
            return active
        return []

    # -----------------------------------------------------------------------
    # System-level observations
    # -----------------------------------------------------------------------

    def _build_system_observations(
        self,
        providers: list[ProviderSummary],
        workflows: list[WorkflowSummary],
        latency_trends: list[LatencyTrendSummary],
        high_cost_workflows: list[str],
        fragmented_providers: list[str],
    ) -> list[str]:
        obs = []

        if high_cost_workflows:
            obs.append(
                f"High-token workflows detected: {', '.join(high_cost_workflows)}. "
                "These workflows appear to concentrate token consumption."
            )

        if fragmented_providers:
            obs.append(
                f"{len(fragmented_providers)} active providers observed "
                f"({', '.join(fragmented_providers)}). "
                "Provider fragmentation may complicate cost attribution and observability."
            )

        error_providers = [p for p in providers if p.error_rate >= _HIGH_ERROR_RATE_THRESHOLD]
        if error_providers:
            names = ", ".join(p.provider for p in error_providers)
            obs.append(
                f"Elevated error rates observed for: {names}. "
                "Retry patterns may be amplifying token waste."
            )

        high_token_share_wf = [
            w for w in workflows if w.token_share >= _TOKEN_CONCENTRATION_THRESHOLD
        ]
        if high_token_share_wf:
            wf_names = ", ".join(w.workflow for w in high_token_share_wf)
            obs.append(
                f"Token concentration detected — {wf_names} account for a disproportionate "
                "share of token volume. Review whether this reflects expected workload distribution."
            )

        increasing_latency = [t for t in latency_trends if t.trend_direction == "increasing"]
        if increasing_latency:
            obs.append(
                "Latency trend appears to be increasing. "
                "This may correlate with provider load changes or context growth."
            )

        if not obs:
            obs.append("No significant operational concerns detected in current event window.")

        return obs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_trend_direction(values: list[float]) -> str:
    """
    Simple linear trend direction from a time-ordered value list.
    Uses first-half vs second-half comparison to avoid point artifacts.
    """
    if len(values) < 3:
        return "insufficient_data"

    mid = len(values) // 2
    first_half_avg = sum(values[:mid]) / max(mid, 1)
    second_half_avg = sum(values[mid:]) / max(len(values) - mid, 1)

    if first_half_avg == 0:
        return "stable"

    change_pct = (second_half_avg - first_half_avg) / first_half_avg

    if change_pct > _LATENCY_INCREASE_THRESHOLD_PCT:
        return "increasing"
    if change_pct < -_LATENCY_INCREASE_THRESHOLD_PCT:
        return "decreasing"
    return "stable"
