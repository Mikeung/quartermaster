# ADR-001: SQLite as Initial Storage Layer

**Date:** 2026-05-15
**Status:** Accepted

## Context

The system needs to persist scan records and operational snapshots. Options considered:
- SQLite
- PostgreSQL
- JSON files

## Decision

Use SQLite for Phase 0-2.

## Reasons

- Zero infrastructure dependency (no separate DB process)
- Sufficient for single-process write pattern
- WAL mode enables concurrent reads
- Easy to inspect (`sqlite3 data/operational_memory.db`)
- Trivial backup (copy one file)
- Migration to Postgres is mechanical if needed

## Consequences

- Cannot support multi-process concurrent writes at scale
- No full-text search (acceptable for Phase 0-2)
- Migration required if VPS splits into multiple nodes

## Migration Trigger

Switch to PostgreSQL when any of these apply:
- Multi-process write contention observed
- Dataset exceeds 10GB
- Multi-VPS deployment required
