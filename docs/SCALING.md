# Scaling Guide — Operational Limits and VPS Sizing

This document describes the known operational boundaries of the AI Operational
Memory system when deployed on a single VPS with SQLite. It is based on
heuristic analysis and typical SQLite performance characteristics — not
benchmarked measurements on specific hardware.

**Advisory only.** All capacity planning decisions require operator judgment.

---

## Recommended Operating Envelope

| Dimension                     | Comfortable Range | Warning Threshold | Critical Threshold |
|-------------------------------|-------------------|-------------------|--------------------|
| Total snapshots               | < 5,000           | 5,000             | 20,000             |
| Total LLM events              | < 50,000          | 50,000            | 200,000            |
| Database file size            | < 200 MB          | 200 MB            | 1 GB               |
| Write rate                    | < 5,000 writes/hr | 5,000 writes/hr   | 36,000 writes/hr   |
| Recommendations per snapshot  | < 150             | 150               | 400                |
| Avg. query latency            | < 2s              | 2s                | 8s                 |
| Avg. report generation time   | < 10s             | 10s               | 30s                |

These thresholds are advisory boundaries for a **single-VPS, SQLite deployment**.
Exceeding them will not immediately break the system, but will degrade performance
over time if left unaddressed.

---

## VPS Sizing Recommendations

### Minimal (development / small workloads)

- **CPU:** 1 vCPU
- **RAM:** 1 GB
- **Disk:** 10 GB SSD
- **Expected capacity:** < 1,000 snapshots, < 10,000 events
- **Retention:** Run weekly

### Standard (single-team production)

- **CPU:** 2 vCPU
- **RAM:** 2–4 GB
- **Disk:** 40 GB SSD
- **Expected capacity:** Up to 5,000 snapshots, 50,000 events
- **Retention:** Run daily or on schedule

### Extended (high-volume operational use)

- **CPU:** 4 vCPU
- **RAM:** 8 GB
- **Disk:** 100 GB SSD
- **Expected capacity:** Up to 20,000 snapshots, 200,000 events
- **Retention:** Run twice daily
- **Note:** At this scale, consider evaluating a PostgreSQL migration path

> **SSD matters.** SQLite WAL performance is dominated by fsync latency.
> An SSD extends all capacity thresholds by 3–5× versus an HDD.

---

## SQLite-Specific Limits

### WAL Mode and Write Concurrency

The system uses SQLite in **WAL (Write-Ahead Logging) mode**. This allows
one writer and multiple concurrent readers. Characteristics:

- Write throughput is limited by fsync frequency and disk write speed
- At > ~10 writes/second sustained, WAL checkpoint lag can cause read latency spikes
- Checkpoint interval is configured automatically by SQLite
- WAL file size grows between checkpoints; monitor for WAL files > 50 MB

### VACUUM

SQLite does not automatically reclaim freed pages after deletions. After
running retention, the database file may appear large even though the
data has been deleted.

To reclaim space:
```bash
PGPASSWORD="" sqlite3 /path/to/operational_memory.db "VACUUM;"
```

Monitor fragmentation with:
```sql
PRAGMA page_count;
PRAGMA freelist_count;
-- freelist_count / page_count > 0.30 = consider VACUUM
```

### Index Coverage

The following columns should have indexes for acceptable query performance
at scale (these are created at schema initialization):

- `snapshots.created_at`
- `snapshots.project_id`
- `llm_events.created_at`
- `llm_events.project_id`
- `llm_events.provider`
- `llm_events.workflow`

---

## Cognition Pipeline Scaling

The cognition pipeline (investigation, consolidation, deduplication, synthesis)
runs in-memory on snapshot data. Its cost scales with:

1. **Recommendation count per snapshot** — deduplication and consolidation
   are O(n²) in the worst case for greedy grouping. Above 150 recs/snapshot,
   pipeline time becomes noticeable.

2. **Evidence chain length** — evidence compression activates above 20 items
   per chain. Below this threshold, no compression is applied.

3. **Report generation** — ecosystem synthesis and temporal analysis scan
   all snapshots in the requested window. Larger windows = longer generation.

### When cognition cost grows:

1. Enable the Signal Deduplication Engine to reduce input to consolidation.
2. Enable Evidence Compression to reduce display chain size.
3. Raise confidence thresholds to filter low-quality signals before pipeline.
4. Consider shorter temporal windows for on-demand reports.

---

## Retention as a Scaling Tool

Retention is the primary mechanism for staying within the operating envelope.
Key retention parameters:

```python
# POST /operations/retention/snapshots
{
  "retention_days": 30,    # delete snapshots older than 30 days
  "min_keep_count": 100,   # always keep at least 100 newest snapshots
  "dry_run": true          # preview only — set false to execute
}

# POST /operations/retention/llm-events
{
  "retention_days": 30,
  "max_event_count": 50000,
  "dry_run": true
}
```

**Recommended retention schedule:**

| Deployment size | Snapshots retention | Events retention |
|-----------------|---------------------|------------------|
| Minimal         | Every 7 days        | Every 14 days    |
| Standard        | Every 3 days        | Every 7 days     |
| Extended        | Daily               | Daily            |

---

## Migration Path: SQLite → PostgreSQL

The system is designed for single-VPS SQLite operation. If you consistently
exceed the extended envelope (e.g., > 20,000 snapshots or > 200,000 events
despite aggressive retention), PostgreSQL offers significantly higher capacity.

**Migration is not automated.** It requires:
1. Exporting data from SQLite (`sqlite3` `.dump` or custom export script)
2. Adapting `CREATE TABLE` statements for PostgreSQL syntax
3. Updating `backend/config.py` and `memory/store.py` to use `psycopg2`
4. Testing all store operations against the new DB

The decision to migrate should be driven by **measured performance degradation**,
not anticipated volume. Do not migrate prematurely.

---

## API Response Time Targets

| Endpoint category       | Acceptable  | Warning  | Critical  |
|-------------------------|-------------|----------|-----------|
| Health check            | < 100 ms    | 500 ms   | 2s        |
| Single snapshot read    | < 200 ms    | 1s       | 5s        |
| Temporal analysis       | < 2s        | 5s       | 15s       |
| Full report generation  | < 10s       | 20s      | 60s       |
| LLM event aggregation   | < 2s        | 5s       | 15s       |

---

## Monitoring for Scaling Pressure

Use these endpoints to monitor operational scaling health:

```bash
# Scaling boundary assessment
GET /hardening/scaling-boundaries

# Long-term survivability
GET /operations/survivability

# Storage pressure
GET /operations/storage

# Database self-check
GET /operations/self-check
```

Set up a weekly check using:
```bash
./scripts/healthcheck.sh
```

The healthcheck script reports on scaling boundary status as part of its
system health summary.

---

_This document reflects the operational design decisions recorded in
`DECISION_LOG.md`. For architecture rationale, see entries from 2026-05-15
through 2026-05-17._
