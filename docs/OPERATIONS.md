# Operations Guide

Day-to-day operational reference for Quartermaster.

---

## Core Principle

> Observe automatically. Decide manually.

The system scans, analyzes, and reports. Operators read reports and decide what to do. No automated infrastructure changes occur.

---

## Key Endpoints

### System Status

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Server health check |
| `GET /` | Endpoint directory |
| `GET /operations/selfcheck` | Full runtime self-check |
| `GET /operations/readiness` | Deployment readiness report |

### Scanning

| Endpoint | Purpose |
|----------|---------|
| `POST /scan` | Trigger a manual scan |
| `GET /scan/status` | Scheduled scan status |

### Snapshots

| Endpoint | Purpose |
|----------|---------|
| `GET /snapshots` | List recent snapshots |
| `GET /snapshots/latest` | Latest snapshot |
| `GET /snapshots/{id}` | Snapshot by ID |

### Reports

| Endpoint | Purpose |
|----------|---------|
| `GET /reports/latest` | Latest markdown report |
| `GET /temporal/timeline` | Change timeline |
| `GET /runtime/digest` | Daily operational digest |
| `GET /runtime/digest/morning` | Morning briefing digest |
| `GET /runtime/digest/critical` | Critical issues only |

### Operational Intelligence

| Endpoint | Purpose |
|----------|---------|
| `GET /ecosystem/summary` | Ecosystem synthesis |
| `GET /ecosystem/review` | Full ecosystem review |
| `GET /stability/audit/snapshots` | Snapshot integrity audit |
| `GET /investigation/investigate` | Structured investigation |

### Maintenance

| Endpoint | Purpose |
|----------|---------|
| `GET /operations/retention` | Retention dry-run preview |
| `POST /operations/retention/execute` | Execute retention (requires dry_run=false) |
| `GET /operations/storage` | Storage pressure estimate |
| `GET /operations/scheduler` | Scheduler health |

---

## Routine Operations

### Checking System Health

```bash
# Quick check
curl http://localhost:8000/health

# Full self-check
curl http://localhost:8000/operations/selfcheck

# Readiness report
curl http://localhost:8000/operations/readiness/report
```

### Triggering a Manual Scan

```bash
curl -X POST http://localhost:8000/scan \
  -H "Content-Type: application/json" \
  -d '{"target": "."}'
```

### Viewing the Latest Report

```bash
curl http://localhost:8000/reports/latest
```

### Running Retention (Dry Run First)

Always preview before executing:

```bash
# 1. Preview what would be deleted
curl "http://localhost:8000/operations/retention?dry_run=true"

# 2. Review the candidates in the response

# 3. Execute if satisfied
curl -X POST "http://localhost:8000/operations/retention/execute?dry_run=false"
```

### Viewing Storage Pressure

```bash
curl http://localhost:8000/operations/storage
```

---

## Monitoring Recommendations

For a solo-dev VPS context, lightweight monitoring options:

**Systemd health**: `systemctl status quartermaster`

**Log streaming**: `journalctl -u quartermaster -f`

**Cron-based health check**:
```cron
# Alert if server goes down
*/5 * * * * /opt/quartermaster/scripts/healthcheck.sh || echo "ALERT: ops server down" | mail -s "ops-alert" ops@example.com
```

**Weekly backup cron**:
```cron
0 3 * * 0 /opt/quartermaster/scripts/backup.sh
```

---

## Log Interpretation

Logs are structured JSON by default (`LOG_FORMAT=json`).

Common fields:

| Field | Meaning |
|-------|---------|
| `level` | `INFO`, `WARNING`, `ERROR` |
| `message` | Human-readable event description |
| `scanner` | Which scanner produced the event |
| `target` | Scan target path |
| `error` | Exception message on failures |
| `consecutive_errors` | Scheduler job error counter |

Watch for:
- `"Scheduled scan failed"` — scan errors, check target path and permissions
- `"Scan job degraded"` — 5+ consecutive failures on a job
- `"Retention executed"` — snapshot deletions occurred

---

## What Requires Human Judgment

The system surfaces findings — humans decide:

- Whether a recommendation is worth acting on
- When to run retention (the system previews, you decide)
- Whether a drift signal represents real change or noise
- How to respond to runtime instability findings
- Whether cost observations warrant architecture changes

---

## Escalation Situations

Escalate to architecture review if:
- Scan errors persist after target path verification
- Database size exceeds 1 GB
- Snapshot schema violations appear across multiple snapshots
- Runtime health shows sustained critical scores
