# API Overview

All endpoints are read-only from an infrastructure perspective. The system observes and reports. It never modifies external systems.

Base URL: `http://localhost:8000` (default)

---

## Service

### `GET /`
Service identity response.

```json
{
  "service": "quartermaster",
  "version": "0.1.0",
  "status": "running"
}
```

### `GET /health`
Uptime and version check.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_s": 3721.4
}
```

---

## Scanning

### `POST /scan`
Trigger a full operational scan. Scans the target directory and all running infrastructure. Persists a snapshot to SQLite. Returns a scan summary.

**Request body:**
```json
{ "target": "." }
```

**Response:**
```json
{
  "snapshot_id": 7,
  "target": "/root/my-project",
  "duration_s": 1.23,
  "llm_providers_detected": ["anthropic", "openai"],
  "drift_changes": 2,
  "drift_summary": "LLM provider added: openai",
  "drift_human_readable": [
    "LLM provider added: openai",
    "Framework added: fastapi"
  ]
}
```

### `GET /scan/status`
Scanner registry and scheduler status. Shows which scanners are registered and when background jobs are scheduled.

```json
{
  "registered_scanners": ["repo_scanner", "service_scanner", "process_scanner"],
  "scheduled_jobs": [
    { "id": "auto_scan", "next_run": "2026-05-16T04:00:00Z", "interval_hours": 6 }
  ]
}
```

---

## Snapshots

### `GET /snapshots`
List all stored operational snapshots, most recent first.

```json
{
  "snapshots": [
    { "id": 7, "snapshot_type": "full_scan", "created_at": "2026-05-16T12:00:00Z", "notes": "" },
    { "id": 6, "snapshot_type": "full_scan", "created_at": "2026-05-16T06:00:00Z", "notes": "" }
  ],
  "count": 7
}
```

### `GET /snapshots/{id}`
Fetch a specific snapshot by ID. Returns the full scan payload.

---

## Reports

### `GET /reports/latest`
Markdown-formatted operational report from the most recent scan. Covers scan summary, detected technologies, LLM providers, drift, and recommendations.

```json
{
  "report": "# Operational Report\n\n## Scan Summary\n...",
  "format": "markdown",
  "snapshot_id": 7
}
```

---

## Topology

All topology endpoints derive from the most recent full scan snapshot. If the snapshot already contains precomputed topology data, it is returned directly. Otherwise, topology is recomputed on-the-fly.

### `GET /topology/latest`
Full topology graph — nodes, edges, relationships, and evidence.

```json
{
  "node_count": 6,
  "edge_count": 8,
  "nodes": [
    { "id": "repo:my-project", "node_type": "repository", "label": "my-project", "metadata": {...} },
    { "id": "llm_provider:anthropic", "node_type": "llm_provider", "label": "anthropic", "metadata": {} }
  ],
  "edges": [
    {
      "source": "repo:my-project",
      "target": "llm_provider:anthropic",
      "relationship": "USES_LLM_PROVIDER",
      "confidence": 0.92,
      "evidence": [
        { "source": "package_manifest", "detail": "anthropic found in dependencies" }
      ]
    }
  ]
}
```

### `GET /topology/workflows`
Inferred AI workflow patterns with confidence scores and evidence.

```json
{
  "workflows": [
    {
      "name": "API_LLM_WRAPPER",
      "description": "HTTP API service that exposes LLM capabilities through REST endpoints.",
      "confidence": 0.80,
      "evidence": [
        "Web framework: fastapi",
        "LLM providers: anthropic"
      ],
      "llm_providers": ["anthropic"],
      "estimated_cost_tier": "medium",
      "workflow_type": "api_service"
    }
  ],
  "count": 1
}
```

### `GET /topology/recommendations`
Advisory recommendations sorted by confidence descending.

```json
{
  "recommendations": [
    {
      "title": "LLM API service — add request-level latency and token tracking",
      "observation": "Web API with LLM backend detected. Without per-request telemetry, latency regressions and cost spikes are invisible.",
      "evidence": [
        "Web frameworks: fastapi",
        "LLM providers: anthropic"
      ],
      "confidence": 0.70,
      "impact": "medium",
      "category": "observability",
      "suggested_investigation": "Add middleware to log: request ID, LLM provider, model, token count, latency, and status."
    }
  ],
  "count": 1
}
```

### `GET /topology/report`
Topology-focused markdown report. Covers components, inferred workflows, cost observations, and recommendations.

```json
{
  "report": "# Topology Report\n\n## Components\n...",
  "format": "markdown"
}
```

---

## Operational Philosophy

- All endpoints are read-only from the infrastructure perspective
- No endpoint triggers changes in target systems
- Topology and recommendations are always derived from evidence
- Confidence scores are explicit and traceable
- Every inference cites the observations that produced it

---

## Development Mode

Set `DEBUG=true` in `.env` to enable:
- Swagger UI at `/docs`
- ReDoc at `/redoc`
- Verbose structured logging
