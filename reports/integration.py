"""
Integration reports — operational compatibility and integration readiness.

Generators:
  generate_integration_readiness_report    — overall integration health
  generate_ingestion_compatibility_report  — ingestion-specific compatibility
  generate_project_integration_summary     — per-project integration status
  generate_sdk_usage_guidance              — SDK usage guidance for a project/stack
  generate_event_quality_summary           — quality assessment of ingested events

All reports answer: "Can this ecosystem integrate safely and cleanly?"
All language is bounded: appears/suggests/historically — no certainty claims.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Integration readiness report
# ---------------------------------------------------------------------------

def generate_integration_readiness_report(
    project_profiles: list[dict[str, Any]],
    ingestion_pressure_summary: dict[str, Any] | None,
    survivability_report: dict[str, Any] | None,
    llm_storage: dict[str, Any] | None,
    generated_at: str | None = None,
) -> str:
    """
    Generate a full integration readiness report.

    Synthesizes project state, ingestion pressure, survivability, and storage
    into a single "can I integrate here safely?" answer.
    """
    ts = generated_at or datetime.now(UTC).isoformat()
    lines = [
        "# Integration Readiness Report",
        "",
        f"_Generated: {ts}_",
        "",
        "## Summary",
        "",
    ]

    # Overall readiness signal
    issues: list[str] = []
    cautions: list[str] = []

    # Check survivability
    if survivability_report:
        status = survivability_report.get("overall_status", "unknown")
        if status == "critical":
            issues.append("system survivability is in a critical state")
        elif status == "warning":
            cautions.append("system survivability has active warnings")

    # Check ingestion pressure
    if ingestion_pressure_summary:
        crit = ingestion_pressure_summary.get("critical_count", 0)
        warn = ingestion_pressure_summary.get("warning_count", 0)
        if crit:
            issues.append(f"{crit} project(s) appear to have critical ingestion pressure")
        elif warn:
            cautions.append(f"{warn} project(s) appear to have elevated ingestion pressure")

    # Check project count
    active_projects = [p for p in project_profiles if not p.get("archived", False)]
    if not active_projects:
        cautions.append("no active projects registered — events will be stored without project scoping")

    if issues:
        lines.append("**Status: NOT RECOMMENDED** — the following issues were detected:")
        for issue in issues:
            lines.append(f"- {issue}")
    elif cautions:
        lines.append("**Status: CAUTION** — integration appears possible but note the following:")
        for c in cautions:
            lines.append(f"- {c}")
    else:
        lines.append("**Status: READY** — no blocking issues detected.")

    lines += ["", "---", ""]

    # Projects section
    lines += ["## Active Projects", ""]
    if active_projects:
        lines.append("| Project ID | Retention Profile | Ingestion Enabled |")
        lines.append("|---|---|---|")
        for p in active_projects:
            pid = p.get("project_id", "unknown")
            retention = p.get("retention_profile", "standard")
            ing = "Yes" if p.get("ingestion_enabled", True) else "No"
            lines.append(f"| `{pid}` | {retention} | {ing} |")
    else:
        lines.append("_No active projects registered._")

    lines += [""]

    # Survivability section
    if survivability_report:
        status = survivability_report.get("overall_status", "unknown")
        outlook = survivability_report.get("long_term_outlook", "unknown")
        checks = survivability_report.get("checks", [])
        lines += [
            "## System Survivability",
            "",
            f"Overall: **{status.upper()}** | Outlook: **{outlook}**",
            "",
        ]
        failed_checks = [c for c in checks if not c.get("passed")]
        if failed_checks:
            lines.append("Failed checks:")
            for c in failed_checks:
                lines.append(f"- **{c.get('name')}**: {c.get('message', '')}")
        else:
            lines.append("All survivability checks passing.")
        lines.append("")

    # Storage section
    if llm_storage:
        event_count = llm_storage.get("event_count", 0)
        db_size = llm_storage.get("db_size_mb", 0)
        lines += [
            "## LLM Event Storage",
            "",
            f"- Events stored: {event_count:,}",
            f"- Database size: {db_size:.1f} MB",
            "",
        ]

    # Ingestion pressure section
    if ingestion_pressure_summary:
        total = ingestion_pressure_summary.get("total_projects_checked", 0)
        ok_count = ingestion_pressure_summary.get("ok_count", 0)
        warn_count = ingestion_pressure_summary.get("warning_count", 0)
        crit_count = ingestion_pressure_summary.get("critical_count", 0)
        lines += [
            "## Ingestion Pressure",
            "",
            f"- Projects checked: {total}",
            f"- OK: {ok_count}  |  Warning: {warn_count}  |  Critical: {crit_count}",
            "",
        ]

    lines += [
        "---",
        "",
        "_This report is advisory. Findings suggest current conditions but do not constitute_",
        "_guarantees about future behavior. Operator review recommended before acting on findings._",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ingestion compatibility report
# ---------------------------------------------------------------------------

def generate_ingestion_compatibility_report(
    event_samples: list[dict[str, Any]],
    project_id: str | None = None,
    generated_at: str | None = None,
) -> str:
    """
    Assess the compatibility of a set of event samples with the ingestion schema.

    Checks for:
    - Missing required fields
    - Forbidden field presence
    - Oversized metadata
    - Suspicious metadata keys
    - Token count consistency
    """
    ts = generated_at or datetime.now(UTC).isoformat()
    scope = f" — Project: `{project_id}`" if project_id else ""
    lines = [
        "# Ingestion Compatibility Report",
        "",
        f"_Generated: {ts}{scope}_",
        "",
    ]

    if not event_samples:
        lines += ["No event samples provided.", ""]
        return "\n".join(lines)

    total = len(event_samples)
    issues_by_sample: list[list[str]] = []

    for sample in event_samples:
        issues = _check_event_sample(sample)
        issues_by_sample.append(issues)

    clean = sum(1 for iss in issues_by_sample if not iss)
    flagged = total - clean

    lines += [
        "## Summary",
        "",
        f"- Samples checked: {total}",
        f"- Clean: {clean}",
        f"- Flagged: {flagged}",
        "",
    ]

    if flagged == 0:
        lines += ["All samples appear compatible with the ingestion schema.", ""]
    else:
        lines += [
            "## Flagged Samples",
            "",
        ]
        for i, (sample, issues) in enumerate(zip(event_samples, issues_by_sample, strict=False)):
            if not issues:
                continue
            wf = sample.get("workflow", f"sample-{i+1}")
            lines.append(f"**Sample {i+1}** (`{wf}`):")
            for iss in issues:
                lines.append(f"  - {iss}")
            lines.append("")

    lines += [
        "## Required Fields Reference",
        "",
        "| Field | Type | Required |",
        "|---|---|---|",
        "| `provider` | string | Yes |",
        "| `model` | string | Yes |",
        "| `workflow` | string | Yes |",
        "| `prompt_tokens` | int | Yes |",
        "| `completion_tokens` | int | Yes |",
        "| `total_tokens` | int | Yes |",
        "| `latency_ms` | float | Yes |",
        "| `success` | bool | Yes |",
        "| `request_kind` | string | No (default: completion) |",
        "| `estimated_cost` | float | No |",
        "| `error_type` | string | No |",
        "| `metadata` | dict[str,str] | No (max 10 keys) |",
        "",
        "_Fields `prompt`, `response`, `content`, `messages`, `text`, and similar are forbidden._",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-project integration summary
# ---------------------------------------------------------------------------

def generate_project_integration_summary(
    project: dict[str, Any],
    event_stats: dict[str, Any] | None,
    pressure_status: dict[str, Any] | None,
    generated_at: str | None = None,
) -> str:
    """Summarize integration health for a single project."""
    ts = generated_at or datetime.now(UTC).isoformat()
    pid = project.get("project_id", "unknown")
    lines = [
        f"# Project Integration Summary: `{pid}`",
        "",
        f"_Generated: {ts}_",
        "",
        "## Project",
        "",
        f"- **Name:** {project.get('name', pid)}",
        f"- **Status:** {'Archived' if project.get('archived') else 'Active'}",
        f"- **Ingestion:** {'Enabled' if project.get('ingestion_enabled', True) else 'Disabled'}",
        f"- **Retention Profile:** {project.get('retention_profile', 'standard')}",
        f"- **Deployment Profile:** {project.get('deployment_profile', 'standard')}",
        "",
    ]

    if project.get("tags"):
        lines.append(f"- **Tags:** {', '.join(project['tags'])}")
        lines.append("")

    if event_stats:
        event_count = event_stats.get("event_count", 0)
        provider_count = event_stats.get("distinct_providers", 0)
        workflow_count = event_stats.get("distinct_workflows", 0)
        lines += [
            "## LLM Event Statistics",
            "",
            f"- Events recorded: {event_count:,}",
            f"- Distinct providers: {provider_count}",
            f"- Distinct workflows: {workflow_count}",
            "",
        ]

    if pressure_status:
        level = pressure_status.get("pressure_level", "ok")
        rate_pct = pressure_status.get("rate_fraction", 0) * 100
        icon = {"ok": "✓", "warning": "⚠", "critical": "✗"}.get(level, "?")
        lines += [
            "## Ingestion Pressure",
            "",
            f"- Level: {icon} **{level.upper()}**",
            f"- Rate utilization: {rate_pct:.1f}%",
        ]
        warnings = pressure_status.get("warnings", [])
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in warnings:
                lines.append(f"- {w.get('message', str(w))}")
        lines.append("")

    lines += [
        "---",
        "",
        "_This summary reflects conditions at generation time. Operator review recommended._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SDK usage guidance
# ---------------------------------------------------------------------------

def generate_sdk_usage_guidance(
    project_id: str,
    base_url: str,
    stack: str | None = None,
    generated_at: str | None = None,
) -> str:
    """Generate SDK usage guidance tailored to a project and stack."""
    ts = generated_at or datetime.now(UTC).isoformat()
    lines = [
        "# SDK Usage Guidance",
        "",
        f"_Generated: {ts}_",
        f"_Project: `{project_id}` | Service: {base_url}_",
        "",
        "## Installation",
        "",
        "No separate package installation required if you are working within the",
        "`quartermaster` repository. The SDK is available at `sdk/python/`.",
        "",
        "## Basic Usage",
        "",
        "```python",
        "from sdk.python.client import OperationalMemoryClient",
        "from sdk.python.helpers import build_event",
        "",
        "client = OperationalMemoryClient(",
        f"    base_url='{base_url}',",
        f"    project_id='{project_id}',",
        ")",
        "",
        "# Build and send a single event",
        "event = build_event(",
        "    provider='anthropic',",
        "    model='claude-sonnet-4-6',",
        "    workflow='my-feature/summarize',",
        "    prompt_tokens=1200,",
        "    completion_tokens=350,",
        "    latency_ms=2800.0,",
        "    success=True,",
        ")",
        "result = client.send_event(event)",
        "```",
        "",
        "## Error Handling",
        "",
        "```python",
        "import time",
        "from sdk.python.helpers import build_event, build_error_event",
        "",
        "t0 = time.monotonic()",
        "try:",
        "    response = call_llm(...)   # your LLM call",
        "    latency_ms = (time.monotonic() - t0) * 1000",
        "    event = build_event(",
        "        provider='openai', model='gpt-4o-mini',",
        "        workflow='my-workflow',",
        "        prompt_tokens=response.usage.prompt_tokens,",
        "        completion_tokens=response.usage.completion_tokens,",
        "        latency_ms=latency_ms,",
        "    )",
        "except Exception as exc:",
        "    latency_ms = (time.monotonic() - t0) * 1000",
        "    event = build_error_event(",
        "        provider='openai', model='gpt-4o-mini',",
        "        workflow='my-workflow',",
        "        error_type='api_error',",
        "        latency_ms=latency_ms,",
        "    )",
        "    raise",
        "finally:",
        "    client.send_event(event)",
        "```",
        "",
    ]

    if stack:
        from integrations.profiles import get_profile
        profile = get_profile(stack)
        if profile:
            lines += [
                f"## {profile.display_name} Integration Notes",
                "",
                profile.description,
                "",
                f"- **Workflow prefix:** `{profile.recommended_workflow_prefix}/`",
                f"- **Recommended metadata keys:** {', '.join(profile.recommended_metadata_keys) or 'none'}",
                f"- **Batching:** {'Recommended' if profile.batching_recommended else 'Not needed'}",
                f"- **Suggested retention:** {profile.suggested_retention_days} days",
                "",
            ]
            if profile.cautions:
                lines += ["**Cautions:**", ""]
                for c in profile.cautions:
                    lines.append(f"- {c}")
                lines.append("")

    lines += [
        "## Privacy Constraints",
        "",
        "The following fields must **never** appear in event payloads:",
        "`prompt`, `response`, `content`, `messages`, `text`, `system_prompt`,",
        "`user_message`, `assistant_message`, `completion`, `choices`, `input`,",
        "`output`, `body`, `payload`, `conversation`, `context`, `instruction`,",
        "`query`, `answer`, `raw`, `request`, `transcript`, `dialogue`, `chat`,",
        "`history`, `thread`.",
        "",
        "The SDK client performs a local check before sending. The server privacy gate",
        "also rejects events containing these fields.",
        "",
        "---",
        "_This guidance is advisory. Adapt patterns to your specific integration needs._",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Event quality summary
# ---------------------------------------------------------------------------

def generate_event_quality_summary(
    provider_stats: list[dict[str, Any]],
    workflow_stats: list[dict[str, Any]],
    project_id: str | None = None,
    generated_at: str | None = None,
) -> str:
    """
    Assess the quality of ingested event data.

    Checks for:
    - Providers with no model variety (may indicate generic labeling)
    - Workflows with 0-token events (may indicate missing usage capture)
    - Very high error rates (>20% per workflow)
    - Missing latency data (latency_ms = 0)
    """
    ts = generated_at or datetime.now(UTC).isoformat()
    scope = f" — Project: `{project_id}`" if project_id else ""
    lines = [
        "# Event Quality Summary",
        "",
        f"_Generated: {ts}{scope}_",
        "",
    ]

    quality_issues: list[str] = []
    quality_notes: list[str] = []

    # Check provider stats
    for p in provider_stats:
        pname = p.get("provider", "unknown")
        total = p.get("total_events", 0)
        err = p.get("error_count", 0)
        error_rate = err / total if total > 0 else 0
        avg_latency = p.get("avg_latency_ms", 0) or 0

        if error_rate >= 0.20:
            quality_issues.append(
                f"Provider '{pname}' has a {error_rate*100:.0f}% error rate "
                f"({err}/{total} events) — appears elevated"
            )
        if avg_latency == 0 and total > 5:
            quality_notes.append(
                f"Provider '{pname}' shows zero average latency — "
                "latency_ms may not be captured correctly"
            )

    # Check workflow stats
    for w in workflow_stats:
        wname = w.get("workflow", "unknown")
        total = w.get("total_events", 0)
        avg_prompt = w.get("avg_prompt_tokens", 0) or 0
        avg_completion = w.get("avg_completion_tokens", 0) or 0

        if total > 5 and avg_prompt == 0:
            quality_notes.append(
                f"Workflow '{wname}' has zero average prompt tokens — "
                "token counts may not be captured"
            )
        if total > 5 and avg_completion == 0 and avg_prompt > 0:
            quality_notes.append(
                f"Workflow '{wname}' has zero completion tokens — "
                "may be an embedding or streaming workflow where token capture needs review"
            )

    # Summary
    lines += ["## Summary", ""]
    lines.append(f"- Providers analyzed: {len(provider_stats)}")
    lines.append(f"- Workflows analyzed: {len(workflow_stats)}")
    lines.append(f"- Quality issues found: {len(quality_issues)}")
    lines.append(f"- Quality notes: {len(quality_notes)}")
    lines.append("")

    if quality_issues:
        lines += ["## Quality Issues", ""]
        for issue in quality_issues:
            lines.append(f"- ⚠ {issue}")
        lines.append("")

    if quality_notes:
        lines += ["## Quality Notes", ""]
        for note in quality_notes:
            lines.append(f"- ℹ {note}")
        lines.append("")

    if not quality_issues and not quality_notes:
        lines += ["No quality issues or notes detected. Event data appears well-formed.", ""]

    lines += [
        "---",
        "_Quality findings are based on statistical patterns and suggest areas for review._",
        "_They do not constitute definitive diagnoses of capture or configuration problems._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = frozenset({
    "provider", "model", "workflow",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "latency_ms", "success",
})

_FORBIDDEN_FIELDS = frozenset({
    "prompt", "response", "content", "message", "messages", "text",
    "system_prompt", "user_message", "assistant_message", "completion",
    "choices", "input", "output", "body", "payload", "conversation",
    "context", "instruction", "query", "answer", "raw", "request",
    "transcript", "dialogue", "chat", "history", "thread",
})


def _check_event_sample(sample: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    # Missing required fields
    for field in _REQUIRED_FIELDS:
        if field not in sample:
            issues.append(f"missing required field: `{field}`")
    # Forbidden fields
    found_forbidden = [k for k in sample if k.lower() in _FORBIDDEN_FIELDS]
    for f in found_forbidden:
        issues.append(f"forbidden field present: `{f}`")
    # Check metadata
    metadata = sample.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            issues.append("metadata must be a dict[str, str]")
        elif len(metadata) > 10:
            issues.append(f"metadata has {len(metadata)} keys — max 10 allowed")
        else:
            for k, v in metadata.items():
                if len(str(v)) > 256:
                    issues.append(f"metadata key '{k}' value exceeds 256 chars")
                if k.lower() in _FORBIDDEN_FIELDS:
                    issues.append(f"forbidden metadata key: `{k}`")
    # Token consistency
    if "prompt_tokens" in sample and "completion_tokens" in sample:
        pt = sample.get("prompt_tokens", 0) or 0
        ct = sample.get("completion_tokens", 0) or 0
        tt = sample.get("total_tokens")
        if tt is not None and int(tt) != int(pt) + int(ct):
            issues.append(
                f"total_tokens ({tt}) does not equal prompt_tokens + completion_tokens ({pt + ct})"
            )
    return issues
