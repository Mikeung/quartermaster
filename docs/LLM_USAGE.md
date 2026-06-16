# LLM Usage Visibility

## Overview

Phase 9 adds lightweight runtime LLM operational visibility to the platform.

This is **not** an LLMOps platform, tracing system, or telemetry warehouse.

It answers one question:

> How are LLM workloads actually behaving operationally?

---

## What it does

- Accepts lightweight LLM operational events via `POST /llm/events`
- Tracks token consumption, latency, cost estimates, and error rates
- Aggregates by provider and workflow
- Detects latency trends and token concentration
- Generates operational reports
- Enforces privacy — never stores prompt or response content

---

## Optional ingestion

Ingestion is **entirely optional**. The system functions without any LLM events.

When events are present, analysis switches from structural heuristics to
evidence-backed observations with higher confidence.

When no events are present, cost intelligence falls back to heuristic
observations derived from topology and workflow structure.

---

## Event schema

Send events to `POST /llm/events`:

```json
{
  "timestamp": "2026-05-17T10:00:00Z",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "workflow": "document-processing",
  "prompt_tokens": 1200,
  "completion_tokens": 400,
  "total_tokens": 1600,
  "latency_ms": 2400.5,
  "success": true,
  "request_kind": "completion",
  "estimated_cost": 0.0048,
  "metadata": {
    "environment": "production",
    "stage": "extraction"
  }
}
```

### Required fields

| Field | Type | Description |
|---|---|---|
| timestamp | ISO 8601 string | Event time |
| provider | string | Provider name (anthropic, openai, ollama, …) |
| model | string | Model identifier |
| workflow | string | Caller-defined workflow label |
| prompt_tokens | integer | Prompt token count |
| completion_tokens | integer | Completion token count |
| total_tokens | integer | Total token count |
| latency_ms | float | Request latency in milliseconds |
| success | boolean | Whether the call succeeded |

### Optional fields

| Field | Type | Description |
|---|---|---|
| request_kind | string | completion / chat / embedding / … |
| estimated_cost | float | USD estimate (best-effort) |
| error_type | string | rate_limit / timeout / context_length / … |
| metadata | dict[str,str] | Bounded operational tags (max 10 keys) |

### Schema version

Current schema version: `1.0`

---

## Privacy guarantees

**The privacy guard is non-negotiable.**

Events that contain any of the following fields are rejected before storage:

```
prompt, response, content, message, messages, text,
system_prompt, user_message, assistant_message, completion,
choices, input, output, body, payload, conversation,
context, instruction, query, answer, raw, request,
transcript, dialogue, chat, history, thread
```

Metadata values that appear to contain natural language prose are also rejected.

Metadata keys that suggest content leakage (`prompt`, `response`, `message`, etc.)
are rejected.

Oversized payloads (> 8 KB) are rejected.

**This system stores operational metadata only — never prompt or response content.**

---

## Retention behavior

Default retention policy:
- **Age limit:** 30 days
- **Count limit:** 50,000 events
- **Safety floor:** 1,000 events always kept

Retention is **never automatic**. It requires explicit operator action:

```bash
# Preview what would be deleted (safe — dry run)
GET /llm/retention/plan

# Execute retention (requires dry_run=false)
POST /llm/retention/execute?dry_run=false
```

---

## Expected storage growth

| Ingestion rate | Storage per day |
|---|---|
| 100 events/day | ~50 KB/day |
| 1,000 events/day | ~500 KB/day |
| 10,000 events/day | ~5 MB/day |

At default retention (30 days, 50k max):
- Light usage (<1k events/day): ~15 MB max
- Moderate usage (~5k events/day): ~75 MB max

Storage estimate: `GET /llm/storage`

---

## Recommended ingestion rates

This system is designed for VPS use. Recommended ingestion:

- **Light:** < 1,000 events/day (observability layer, background jobs)
- **Moderate:** 1,000–10,000 events/day (production API with multiple workflows)
- **Heavy:** > 10,000/day — reduce by sampling (e.g., log 1 in 10 events)

**Do not use this as a high-volume telemetry system.**
For high-volume tracing, use OpenTelemetry + a dedicated collector.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| POST | /llm/events | Ingest event |
| GET | /llm/summary | Full usage analysis |
| GET | /llm/providers | Provider aggregates |
| GET | /llm/workflows | Workflow aggregates |
| GET | /llm/trends | Latency + daily totals |
| GET | /llm/costs | Cost concentration |
| GET | /llm/storage | Storage estimate |
| GET | /llm/retention/plan | Preview retention (dry run) |
| POST | /llm/retention/execute | Execute retention |
| GET | /llm/report/provider | Provider report (markdown) |
| GET | /llm/report/workflows | Workflow economics (markdown) |
| GET | /llm/report/latency | Latency trends (markdown) |
| GET | /llm/report/tokens | Token concentration (markdown) |
| GET | /llm/report/errors | Error trends (markdown) |

All GET endpoints support `?window_hours=N` (default: 168 = 7 days, max: 8760 = 1 year).

---

## Operational limitations

1. **Partial visibility only.** Events reflect what your code explicitly sends — not complete
   LLM activity. Gaps in ingestion mean gaps in analysis.

2. **Cost estimates are approximations.** `estimated_cost` is whatever your code passes in.
   The system does not access provider billing APIs. Always verify costs against provider dashboards.

3. **Correlation, not causation.** Observations like "workflow X consumed 62% of tokens"
   are statistical observations, not causal diagnoses.

4. **No request tracing.** Individual requests are not traced. Only aggregate patterns
   are analyzed.

5. **No automatic optimization.** The system recommends, never acts.

---

## Intentionally not included

- OpenTelemetry integration
- Distributed ingestion (Kafka, queues)
- Request/response tracing
- Prompt content storage
- Automatic model routing
- Provider billing API integration
- Real-time streaming dashboards

---

## Privacy rejection example

If you accidentally send a prompt field:

```json
POST /llm/events
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "workflow": "qa",
  "prompt": "Summarize the following document: ...",
  "prompt_tokens": 1500,
  "completion_tokens": 200,
  "total_tokens": 1700,
  "latency_ms": 3200,
  "success": true,
  "timestamp": "2026-05-17T10:00:00Z"
}
```

Response (HTTP 422):

```json
{
  "error": "Privacy guard rejected this event.",
  "rejections": [
    "Forbidden field 'prompt' — this field may contain prompt or response content and must not be stored."
  ],
  "advisory": "Never store prompt text, response text, or conversation content. Only operational metadata (tokens, latency, provider, workflow) may be stored."
}
```
