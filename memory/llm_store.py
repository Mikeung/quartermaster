"""
LLM Event Store — bounded, append-only SQLite storage for LLM operational events.

Design rules:
- SQLite only. No external dependencies.
- Append-only: no event updates, no event corrections.
- Bounded retention: old events are pruned by age or count.
- Queries are always capped by limit parameter.
- No prompt or response content is ever stored here.

This store is a companion to OperationalStore (snapshots). It uses the same
SQLite database file but manages its own table (llm_events).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemas.llm_event_schema import LLMEvent

logger = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_MAX_EVENTS = 50_000
_DEFAULT_QUERY_LIMIT = 500


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class LLMEventStore:
    """
    Append-only store for LLM operational events.

    One SQLite table: llm_events.
    All queries are bounded. No unbounded reads.
    Retention pruning is explicit — never automatic.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        logger.info("LLM event store connected", extra={"path": str(self.db_path)})

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("LLM event store disconnected")

    def _migrate(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS llm_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp        TEXT    NOT NULL,
                provider         TEXT    NOT NULL,
                model            TEXT    NOT NULL,
                workflow         TEXT    NOT NULL,
                prompt_tokens    INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens     INTEGER NOT NULL DEFAULT 0,
                latency_ms       REAL    NOT NULL DEFAULT 0.0,
                success          INTEGER NOT NULL DEFAULT 1,
                request_kind     TEXT    NOT NULL DEFAULT 'completion',
                estimated_cost   REAL,
                error_type       TEXT,
                metadata         TEXT    NOT NULL DEFAULT '{}',
                schema_version   TEXT    NOT NULL DEFAULT '1.0',
                ingested_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_llm_events_provider
                ON llm_events(provider, timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_llm_events_workflow
                ON llm_events(workflow, timestamp DESC);

            CREATE INDEX IF NOT EXISTS idx_llm_events_timestamp
                ON llm_events(timestamp DESC);
        """)
        self._conn.commit()
        # Add project_id column if not present (backward compat)
        try:
            self._conn.execute("ALTER TABLE llm_events ADD COLUMN project_id TEXT")
            self._conn.commit()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_events_project "
                "ON llm_events(project_id, timestamp DESC)"
            )
            self._conn.commit()
        except Exception:
            pass  # Column already exists
        logger.info("LLM event store schema migrated")

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def append(self, event: LLMEvent, project_id: str | None = None) -> int:
        """Insert a single LLM event. Returns the new row ID."""
        assert self._conn is not None
        cursor = self._conn.execute(
            """INSERT INTO llm_events (
                timestamp, provider, model, workflow,
                prompt_tokens, completion_tokens, total_tokens,
                latency_ms, success, request_kind,
                estimated_cost, error_type, metadata, schema_version, project_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.timestamp,
                event.provider,
                event.model,
                event.workflow,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                event.latency_ms,
                1 if event.success else 0,
                event.request_kind,
                event.estimated_cost,
                event.error_type,
                json.dumps(event.metadata),
                event.schema_version,
                project_id,
            ),
        )
        self._conn.commit()
        row_id = cursor.lastrowid or 0
        logger.debug(
            "LLM event appended",
            extra={"id": row_id, "provider": event.provider, "workflow": event.workflow, "project_id": project_id},
        )
        return row_id

    # -----------------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------------

    def query(
        self,
        *,
        provider: str | None = None,
        workflow: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        success_only: bool | None = None,
        limit: int = _DEFAULT_QUERY_LIMIT,
    ) -> list[dict[str, Any]]:
        """Bounded query with optional filters. Always returns at most `limit` rows."""
        assert self._conn is not None
        limit = min(limit, _DEFAULT_QUERY_LIMIT)

        clauses = []
        params: list[Any] = []

        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if workflow:
            clauses.append("workflow = ?")
            params.append(workflow)
        if start_time:
            clauses.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            clauses.append("timestamp <= ?")
            params.append(end_time)
        if success_only is True:
            clauses.append("success = 1")
        elif success_only is False:
            clauses.append("success = 0")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM llm_events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [_deserialize_row(dict(r)) for r in rows]

    def count_events(
        self,
        provider: str | None = None,
        workflow: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Count events with optional provider, workflow, and project_id filters."""
        assert self._conn is not None
        conditions = []
        params: list[str] = []
        if provider:
            conditions.append("provider = ?")
            params.append(provider)
        if workflow:
            conditions.append("workflow = ?")
            params.append(workflow)
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM llm_events {where}", params
        ).fetchone()
        return int(row[0]) if row else 0

    # -----------------------------------------------------------------------
    # Aggregation helpers
    # -----------------------------------------------------------------------

    def aggregate_by_provider(
        self, window_hours: int = 168
    ) -> list[dict[str, Any]]:
        """Token/latency/cost aggregates grouped by provider for the last N hours."""
        assert self._conn is not None
        sql = """
            SELECT
                provider,
                COUNT(*)                          AS event_count,
                SUM(total_tokens)                 AS total_tokens,
                SUM(prompt_tokens)                AS prompt_tokens,
                SUM(completion_tokens)            AS completion_tokens,
                AVG(latency_ms)                   AS avg_latency_ms,
                MAX(latency_ms)                   AS max_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_estimated_cost
            FROM llm_events
            WHERE timestamp >= datetime('now', ? || ' hours')
            GROUP BY provider
            ORDER BY total_tokens DESC
        """
        rows = self._conn.execute(sql, (f"-{window_hours}",)).fetchall()
        return [dict(r) for r in rows]

    def aggregate_by_workflow(
        self, window_hours: int = 168
    ) -> list[dict[str, Any]]:
        """Token/latency/cost aggregates grouped by workflow for the last N hours."""
        assert self._conn is not None
        sql = """
            SELECT
                workflow,
                COUNT(*)                          AS event_count,
                SUM(total_tokens)                 AS total_tokens,
                SUM(prompt_tokens)                AS prompt_tokens,
                SUM(completion_tokens)            AS completion_tokens,
                AVG(latency_ms)                   AS avg_latency_ms,
                MAX(latency_ms)                   AS max_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_estimated_cost
            FROM llm_events
            WHERE timestamp >= datetime('now', ? || ' hours')
            GROUP BY workflow
            ORDER BY total_tokens DESC
        """
        rows = self._conn.execute(sql, (f"-{window_hours}",)).fetchall()
        return [dict(r) for r in rows]

    def aggregate_latency_trend(
        self,
        provider: str | None = None,
        window_hours: int = 168,
        bucket_hours: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Average latency bucketed into time windows.
        Useful for spotting provider degradation trends.
        """
        assert self._conn is not None
        provider_clause = "AND provider = ?" if provider else ""
        params: list[Any] = [f"-{window_hours}"]
        if provider:
            params.append(provider)
        params.append(bucket_hours)

        sql = f"""
            SELECT
                strftime('%Y-%m-%dT', timestamp) ||
                    CAST(CAST(strftime('%H', timestamp) AS INTEGER) / ? * ? AS TEXT) || ':00:00'
                    AS bucket,
                COUNT(*)        AS event_count,
                AVG(latency_ms) AS avg_latency_ms,
                MAX(latency_ms) AS max_latency_ms
            FROM llm_events
            WHERE timestamp >= datetime('now', ? || ' hours')
              {provider_clause}
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        # Rebuild with correct param order for bucket
        params_final: list[Any] = [bucket_hours, bucket_hours, f"-{window_hours}"]
        if provider:
            params_final.append(provider)
        rows = self._conn.execute(sql, params_final).fetchall()
        return [dict(r) for r in rows]

    def aggregate_error_trend(
        self, window_hours: int = 168
    ) -> list[dict[str, Any]]:
        """Error-rate aggregates grouped by provider and error_type."""
        assert self._conn is not None
        sql = """
            SELECT
                provider,
                error_type,
                COUNT(*) AS error_count
            FROM llm_events
            WHERE success = 0
              AND timestamp >= datetime('now', ? || ' hours')
            GROUP BY provider, error_type
            ORDER BY error_count DESC
        """
        rows = self._conn.execute(sql, (f"-{window_hours}",)).fetchall()
        return [dict(r) for r in rows]

    def aggregate_daily_totals(
        self, window_days: int = 7
    ) -> list[dict[str, Any]]:
        """Daily token and cost totals for trend analysis."""
        assert self._conn is not None
        sql = """
            SELECT
                strftime('%Y-%m-%d', timestamp) AS day,
                COUNT(*)                         AS event_count,
                SUM(total_tokens)                AS total_tokens,
                SUM(COALESCE(estimated_cost, 0)) AS total_estimated_cost,
                AVG(latency_ms)                  AS avg_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count
            FROM llm_events
            WHERE timestamp >= datetime('now', ? || ' days')
            GROUP BY day
            ORDER BY day ASC
        """
        rows = self._conn.execute(sql, (f"-{window_days}",)).fetchall()
        return [dict(r) for r in rows]

    def get_recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.query(limit=min(limit, 100))

    # -----------------------------------------------------------------------
    # Economic observability helpers (Phase A)
    # -----------------------------------------------------------------------

    def window_spend_bounds(self, window_hours: int = 24) -> dict[str, Any]:
        """Total spend, event count, and active time span over the last N hours.

        active_span_hours is (max_timestamp - min_timestamp); it powers burn-rate
        and runaway detection (a long uninterrupted span is the runaway signal).
        """
        assert self._conn is not None
        row = self._conn.execute(
            """SELECT
                COUNT(*)                          AS event_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_cost,
                SUM(total_tokens)                 AS total_tokens,
                MIN(timestamp)                    AS first_ts,
                MAX(timestamp)                    AS last_ts
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' hours')""",
            (f"-{window_hours}",),
        ).fetchone()
        d = dict(row) if row else {}
        d["active_span_hours"] = _span_hours(d.get("first_ts"), d.get("last_ts"))
        d["total_cost"] = float(d.get("total_cost") or 0.0)
        d["event_count"] = int(d.get("event_count") or 0)
        return d

    def aggregate_workflow_spend(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Per-workflow spend + activity span over the window, costliest first.

        Each row includes first_ts/last_ts/active_span_hours and the dominant
        project_id, so runaway attribution ("which agent caused it") is exact.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                workflow,
                COUNT(*)                          AS event_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_cost,
                SUM(total_tokens)                 AS total_tokens,
                MIN(timestamp)                    AS first_ts,
                MAX(timestamp)                    AS last_ts,
                MAX(project_id)                   AS project_id
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' hours')
               GROUP BY workflow
               ORDER BY total_cost DESC""",
            (f"-{window_hours}",),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["total_cost"] = float(d.get("total_cost") or 0.0)
            d["active_span_hours"] = _span_hours(d.get("first_ts"), d.get("last_ts"))
            out.append(d)
        return out

    def aggregate_cost_by_model(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Per-model spend (with provider + span) over the window, costliest first."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                model,
                MAX(provider)                     AS provider,
                COUNT(*)                          AS event_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_cost,
                SUM(total_tokens)                 AS total_tokens,
                MIN(timestamp)                    AS first_ts,
                MAX(timestamp)                    AS last_ts
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' hours')
               GROUP BY model
               ORDER BY total_cost DESC""",
            (f"-{window_hours}",),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["total_cost"] = float(d.get("total_cost") or 0.0)
            d["active_span_hours"] = _span_hours(d.get("first_ts"), d.get("last_ts"))
            out.append(d)
        return out

    def aggregate_daily_by_model(self, window_days: int = 7) -> list[dict[str, Any]]:
        """Per-day, per-model spend — answers 'WHICH model, WHEN, how much'."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                strftime('%Y-%m-%d', timestamp) AS day,
                model,
                COUNT(*)                         AS event_count,
                SUM(COALESCE(estimated_cost, 0)) AS total_cost
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' days')
               GROUP BY day, model
               ORDER BY day ASC, total_cost DESC""",
            (f"-{window_days}",),
        ).fetchall()
        return [{**dict(r), "total_cost": float(r["total_cost"] or 0.0)} for r in rows]

    def aggregate_daily_by_agent(self, window_days: int = 7) -> list[dict[str, Any]]:
        """Per-day, per-agent (project_id) spend — answers 'WHICH agent, WHEN, how much'."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                strftime('%Y-%m-%d', timestamp) AS day,
                project_id                       AS agent,
                COUNT(*)                         AS event_count,
                SUM(COALESCE(estimated_cost, 0)) AS total_cost
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' days')
               GROUP BY day, project_id
               ORDER BY day ASC, total_cost DESC""",
            (f"-{window_days}",),
        ).fetchall()
        return [{**dict(r), "total_cost": float(r["total_cost"] or 0.0)} for r in rows]

    def aggregate_project_spend(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Per-project spend + span over the window, costliest first."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                project_id,
                COUNT(*)                          AS event_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_cost,
                SUM(total_tokens)                 AS total_tokens,
                MIN(timestamp)                    AS first_ts,
                MAX(timestamp)                    AS last_ts
               FROM llm_events
               WHERE timestamp >= datetime('now', ? || ' hours')
               GROUP BY project_id
               ORDER BY total_cost DESC""",
            (f"-{window_hours}",),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["total_cost"] = float(d.get("total_cost") or 0.0)
            d["active_span_hours"] = _span_hours(d.get("first_ts"), d.get("last_ts"))
            out.append(d)
        return out

    # -----------------------------------------------------------------------
    # Project-scoped queries
    # -----------------------------------------------------------------------

    def aggregate_by_provider_project(
        self, project_id: str, window_hours: int = 168
    ) -> list[dict[str, Any]]:
        """Provider aggregates scoped to a single project."""
        assert self._conn is not None
        sql = """
            SELECT
                provider,
                COUNT(*)                          AS event_count,
                SUM(total_tokens)                 AS total_tokens,
                SUM(prompt_tokens)                AS prompt_tokens,
                SUM(completion_tokens)            AS completion_tokens,
                AVG(latency_ms)                   AS avg_latency_ms,
                MAX(latency_ms)                   AS max_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_estimated_cost
            FROM llm_events
            WHERE project_id = ?
              AND timestamp >= datetime('now', ? || ' hours')
            GROUP BY provider
            ORDER BY total_tokens DESC
        """
        rows = self._conn.execute(sql, (project_id, f"-{window_hours}")).fetchall()
        return [dict(r) for r in rows]

    def aggregate_by_workflow_project(
        self, project_id: str, window_hours: int = 168
    ) -> list[dict[str, Any]]:
        """Workflow aggregates scoped to a single project."""
        assert self._conn is not None
        sql = """
            SELECT
                workflow,
                COUNT(*)                          AS event_count,
                SUM(total_tokens)                 AS total_tokens,
                SUM(prompt_tokens)                AS prompt_tokens,
                SUM(completion_tokens)            AS completion_tokens,
                AVG(latency_ms)                   AS avg_latency_ms,
                MAX(latency_ms)                   AS max_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count,
                SUM(COALESCE(estimated_cost, 0))  AS total_estimated_cost
            FROM llm_events
            WHERE project_id = ?
              AND timestamp >= datetime('now', ? || ' hours')
            GROUP BY workflow
            ORDER BY total_tokens DESC
        """
        rows = self._conn.execute(sql, (project_id, f"-{window_hours}")).fetchall()
        return [dict(r) for r in rows]

    def count_events_by_project(self) -> list[dict[str, Any]]:
        """Return event counts grouped by project_id."""
        assert self._conn is not None
        rows = self._conn.execute(
            """SELECT
                project_id,
                COUNT(*) AS event_count,
                SUM(total_tokens) AS total_tokens,
                SUM(COALESCE(estimated_cost, 0)) AS total_estimated_cost,
                MAX(timestamp) AS latest_at
               FROM llm_events
               WHERE project_id IS NOT NULL
               GROUP BY project_id
               ORDER BY event_count DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_event_timestamp_by_project(self, project_id: str) -> str | None:
        """Return most recent event timestamp for a project."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT MAX(timestamp) FROM llm_events WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        val = row[0] if row else None
        return str(val) if val else None

    # -----------------------------------------------------------------------
    # Retention
    # -----------------------------------------------------------------------

    def delete_events_older_than(self, retention_days: int) -> int:
        """
        Delete events older than retention_days. Returns deleted count.

        Never called automatically — only via explicit operator action
        through LLMEventRetentionEngine with dry_run=False.
        """
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM llm_events WHERE timestamp < datetime('now', ? || ' days')",
            (f"-{retention_days}",),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        logger.info("LLM events pruned", extra={"deleted": deleted, "retention_days": retention_days})
        return deleted

    def delete_events_exceeding_count(self, max_count: int, min_keep: int = 1000) -> int:
        """
        Delete oldest events beyond max_count. min_keep is a safety floor.
        Returns deleted count.
        """
        assert self._conn is not None
        effective_max = max(max_count, min_keep)
        total = self.count_events()
        if total <= effective_max:
            return 0
        to_delete = total - effective_max
        cursor = self._conn.execute(
            """DELETE FROM llm_events WHERE id IN (
                SELECT id FROM llm_events ORDER BY timestamp ASC LIMIT ?
            )""",
            (to_delete,),
        )
        self._conn.commit()
        deleted = cursor.rowcount
        logger.info(
            "LLM events count-trimmed",
            extra={"deleted": deleted, "max_count": effective_max},
        )
        return deleted

    def get_oldest_event_timestamp(self) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT MIN(timestamp) FROM llm_events"
        ).fetchone()
        val = row[0] if row else None
        return str(val) if val else None

    def get_newest_event_timestamp(self) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT MAX(timestamp) FROM llm_events"
        ).fetchone()
        val = row[0] if row else None
        return str(val) if val else None

    def get_storage_estimate(self) -> dict[str, Any]:
        """Rough storage estimate for operational awareness."""
        total = self.count_events()
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        avg_bytes_per_event = round(size_bytes / max(total, 1))
        return {
            "total_events": total,
            "db_size_bytes": size_bytes,
            "avg_bytes_per_event": avg_bytes_per_event,
            "oldest_event": self.get_oldest_event_timestamp(),
            "newest_event": self.get_newest_event_timestamp(),
        }

    def list_providers(self) -> list[str]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT DISTINCT provider FROM llm_events ORDER BY provider"
        ).fetchall()
        return [r[0] for r in rows]

    def list_workflows(self) -> list[str]:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT DISTINCT workflow FROM llm_events ORDER BY workflow"
        ).fetchall()
        return [r[0] for r in rows]

    # -----------------------------------------------------------------------
    # Quality scoring helpers
    # -----------------------------------------------------------------------

    def get_provider_stats(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """
        Return per-provider aggregates in the format expected by IngestionQualityScorer.

        Returns: list of {provider, total_events, avg_prompt_tokens,
                          avg_completion_tokens, avg_latency_ms, error_count}
        """
        assert self._conn is not None
        where = "WHERE project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        sql = f"""
            SELECT
                provider,
                COUNT(*)                                 AS total_events,
                AVG(prompt_tokens)                       AS avg_prompt_tokens,
                AVG(completion_tokens)                   AS avg_completion_tokens,
                AVG(latency_ms)                          AS avg_latency_ms,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count
            FROM llm_events
            {where}
            GROUP BY provider
            ORDER BY total_events DESC
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_workflow_stats(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """
        Return per-workflow aggregates in the format expected by IngestionQualityScorer.

        Returns: list of {workflow, total_events, avg_prompt_tokens,
                          avg_completion_tokens, error_count}
        """
        assert self._conn is not None
        where = "WHERE project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        sql = f"""
            SELECT
                workflow,
                COUNT(*)                                 AS total_events,
                AVG(prompt_tokens)                       AS avg_prompt_tokens,
                AVG(completion_tokens)                   AS avg_completion_tokens,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS error_count
            FROM llm_events
            {where}
            GROUP BY workflow
            ORDER BY total_events DESC
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_events_with_metadata(self, project_id: str | None = None) -> int:
        """Count events that have non-empty metadata (beyond '{}')."""
        assert self._conn is not None
        where = "AND project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM llm_events WHERE metadata != '{{}}' AND metadata != '' {where}",
            params,
        ).fetchone()
        return int(row[0]) if row else 0

    def count_events_with_error_type(self, project_id: str | None = None) -> int:
        """Count failure events that have a non-null error_type field."""
        assert self._conn is not None
        where = "AND project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM llm_events WHERE success = 0 AND error_type IS NOT NULL {where}",
            params,
        ).fetchone()
        return int(row[0]) if row else 0

    def count_failed_events(self, project_id: str | None = None) -> int:
        """Count events where success = 0."""
        assert self._conn is not None
        where = "AND project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM llm_events WHERE success = 0 {where}", params
        ).fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deserialize_row(row: dict[str, Any]) -> dict[str, Any]:
    if "metadata" in row and isinstance(row["metadata"], str):
        try:
            row["metadata"] = json.loads(row["metadata"])
        except (json.JSONDecodeError, ValueError):
            row["metadata"] = {}
    if "success" in row:
        row["success"] = bool(row["success"])
    return row


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _span_hours(first_ts: str | None, last_ts: str | None) -> float:
    """Hours between two ISO timestamps, or 0.0 if unparseable/missing."""
    if not first_ts or not last_ts:
        return 0.0
    try:
        a = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
        return round(abs((b - a).total_seconds()) / 3600.0, 2)
    except (ValueError, TypeError):
        return 0.0
