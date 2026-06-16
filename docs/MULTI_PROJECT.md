# Multi-Project Operation

## Overview

Phase 10 adds project namespace support — the ability to track multiple AI
ecosystems on a single VPS without operational cross-contamination.

A **project** is a named namespace that scopes:
- Snapshots
- LLM events
- Storage statistics
- Ingestion health

Projects are lightweight. They are metadata containers, not data containers.

---

## What this is

A single-operator system for:
- Tracking multiple repos/services as distinct operational namespaces
- Preventing one noisy project from obscuring another in analysis
- Understanding per-project storage footprint
- Detecting ingestion pressure before storage limits are hit
- Assessing long-term operational survivability

## What this is NOT

- Multi-tenant SaaS
- RBAC / access control system
- Distributed system
- Cloud orchestration
- User account management

---

## Project model

```json
{
  "project_id": "my-llm-app",
  "name": "My LLM Application",
  "description": "Production RAG pipeline",
  "tags": ["production", "rag"],
  "retention_profile": "standard",
  "deployment_profile": "standard",
  "ingestion_enabled": true,
  "archived": false,
  "metadata": {
    "team": "platform",
    "environment": "prod"
  }
}
```

### project_id rules
- Lowercase alphanumeric + dashes only
- 3–64 characters
- Must start and end with alphanumeric char
- Examples: `my-app`, `rag-pipeline-v2`, `prod-chatbot`

### Retention profiles
- `minimal` — short retention, low storage, infrequent scanning
- `standard` (default) — 30-day retention, standard limits
- `extended` — 90-day retention, higher limits

---

## Project isolation semantics

Projects **scope** data — they do not isolate it at the database level.

All data lives in the same SQLite file. Project-scoped queries filter by
`project_id`. This is operational namespace separation, not tenant isolation.

Implications:
- One DB backup covers all projects
- Retention operates on the full store (project-specific retention not yet implemented)
- No project can "see" another project's data via the API — but they share the same DB file

---

## Backward compatibility

All existing snapshots and LLM events have `project_id = NULL`.

Unscoped queries (without project_id filter) continue to work unchanged.
Existing API endpoints are unaffected.

Project-scoped endpoints require `project_id` to be assigned at ingestion time.

---

## Assigning a project to LLM events

Include `project_id` when posting events:

```json
POST /llm/events
{
  "project_id": "my-llm-app",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "workflow": "document-extraction",
  "prompt_tokens": 1200,
  "completion_tokens": 400,
  "total_tokens": 1600,
  "latency_ms": 2400,
  "success": true,
  "timestamp": "2026-05-17T10:00:00Z"
}
```

The project must be registered before events are accepted for it.

---

## Project archival

Archiving is soft — data is never deleted.

```
POST /projects/{id}/archive
```

Archived projects:
- Are excluded from active analysis by default
- Have ingestion disabled
- Are still queryable (with `include_archived=true`)
- Continue to consume storage until retention runs

---

## Retention per project

Per-project retention is not yet implemented (deferred to Phase 11).

Current retention runs against the full store without project scoping.
Storage budgeting per project is visible via `/projects/storage/overview`
but not yet enforced separately.

---

## Ingestion limits

Default per-project limits:
- **Max rate:** 1,000 events/hour
- **Burst threshold:** 200 events in 5 minutes

Limits are advisory — exceeding them generates warnings.
The `POST /llm/events` endpoint will reject events when the rate limit is
exceeded (HTTP 429).

Limits can be checked without posting events:
```
GET /projects/{id}/health
```

---

## Survivability expectations

The survivability report (`GET /projects/survivability`) assesses whether the
system can sustain continuous operation over 6+ months.

Checks:
1. **Database growth rate** — is storage growing faster than expected?
2. **Retention backlog** — are old snapshots/events accumulating?
3. **Scheduler health** — are scheduled jobs running reliably?
4. **Stale archived projects** — are old archives consuming space needlessly?
5. **Ingestion pressure trend** — is ingestion volume growing week-over-week?

---

## Storage expectations

| Projects | Events/day each | Estimated monthly growth |
|---|---|---|
| 1 | 1,000 | ~15 MB |
| 3 | 1,000 | ~45 MB |
| 5 | 500 | ~40 MB |
| 10 | 100 | ~30 MB |

Run retention monthly (or more frequently) to keep storage bounded.

---

## API reference

| Method | Path | Description |
|---|---|---|
| GET | /projects | List projects |
| POST | /projects | Create project |
| GET | /projects/{id} | Get project |
| PATCH | /projects/{id} | Update project |
| POST | /projects/{id}/archive | Archive project |
| GET | /projects/{id}/summary | Summary (counts + activity) |
| GET | /projects/{id}/storage | Per-project storage profile |
| GET | /projects/{id}/health | Ingestion health |
| GET | /projects/survivability | Survivability assessment |
| GET | /projects/survivability/report | Survivability report (markdown) |
| GET | /projects/pressure | Cross-project ingestion pressure |
| GET | /projects/storage/overview | Cross-project storage distribution |

---

## Operational scaling boundaries

This system is designed for VPS-scale, single-operator use.

Tested / expected bounds:
- **Projects:** up to ~50 active projects
- **Snapshots:** up to 10,000 total
- **LLM events:** up to 100,000 total
- **Query latency:** < 100ms for all bounded aggregations

Beyond these bounds, consider:
- Running retention more aggressively
- Increasing snapshot and event count limits in DeploymentProfile
- Eventually migrating to PostgreSQL (SQLite migration path exists)

---

## Intentionally deferred

- Per-project retention execution (Phase 11 candidate)
- Per-project snapshot scanning (scan_target per project)
- Project-level cognition isolation (analysis scoped to single project)
- Historical ingestion rate tracking (7-day comparison for trend analysis)
- Project creation from CLI (scripts/bootstrap.sh extension)
