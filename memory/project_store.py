"""
Project Store — SQLite-backed project namespace registry.

Manages project registration, metadata, archival, and per-project statistics.

Shares the same SQLite database file as OperationalStore and LLMEventStore,
using a dedicated `projects` table.

Design rules:
- SQLite-only
- No complex ORM
- project_id is the primary key and namespace boundary
- Archival is soft (archived=1) — data is never deleted here
- All queries are bounded
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemas.project_schema import Project, ProjectValidator

logger = logging.getLogger(__name__)

_validator = ProjectValidator()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ProjectStore:
    """
    Manages project namespaces in the operational memory database.

    Projects are lightweight metadata containers. They do not hold data —
    they scope it. Snapshots and LLM events are linked to projects via
    project_id.
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
        logger.info("Project store connected", extra={"path": str(self.db_path)})

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Project store disconnected")

    def _migrate(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id          TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                description         TEXT NOT NULL DEFAULT '',
                tags                TEXT NOT NULL DEFAULT '[]',
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                retention_profile   TEXT NOT NULL DEFAULT 'standard',
                deployment_profile  TEXT NOT NULL DEFAULT 'standard',
                ingestion_enabled   INTEGER NOT NULL DEFAULT 1,
                archived            INTEGER NOT NULL DEFAULT 0,
                metadata            TEXT NOT NULL DEFAULT '{}',
                schema_version      TEXT NOT NULL DEFAULT '1.0',
                updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_projects_archived
                ON projects(archived, created_at DESC);
        """)
        self._conn.commit()
        logger.info("Project store schema migrated")

    # -----------------------------------------------------------------------
    # Write operations
    # -----------------------------------------------------------------------

    def create_project(self, project: Project) -> bool:
        """
        Register a new project. Returns False if project_id already exists.
        Never overwrites an existing project.
        """
        assert self._conn is not None
        try:
            self._conn.execute(
                """INSERT INTO projects
                   (project_id, name, description, tags, created_at,
                    retention_profile, deployment_profile, ingestion_enabled,
                    archived, metadata, schema_version, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project.project_id,
                    project.name,
                    project.description,
                    json.dumps(project.tags),
                    project.created_at,
                    project.retention_profile,
                    project.deployment_profile,
                    1 if project.ingestion_enabled else 0,
                    1 if project.archived else 0,
                    json.dumps(project.metadata),
                    project.schema_version,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.commit()
            logger.info("Project created", extra={"project_id": project.project_id})
            return True
        except sqlite3.IntegrityError:
            logger.warning("Project already exists", extra={"project_id": project.project_id})
            return False

    def update_project(self, project_id: str, updates: dict[str, Any]) -> bool:
        """
        Update mutable project fields. project_id and created_at are immutable.
        Returns False if project not found.
        """
        assert self._conn is not None
        existing = self.get_project(project_id)
        if existing is None:
            return False

        _MUTABLE_FIELDS = frozenset({
            "name", "description", "tags", "retention_profile",
            "deployment_profile", "ingestion_enabled", "archived", "metadata",
        })

        set_clauses = []
        params: list[Any] = []

        for key, value in updates.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if key == "tags":
                set_clauses.append("tags = ?")
                params.append(json.dumps(_coerce_list(value)))
            elif key == "metadata":
                set_clauses.append("metadata = ?")
                params.append(json.dumps(_coerce_dict(value)))
            elif key == "ingestion_enabled":
                set_clauses.append("ingestion_enabled = ?")
                params.append(1 if value else 0)
            elif key == "archived":
                set_clauses.append("archived = ?")
                params.append(1 if value else 0)
            else:
                set_clauses.append(f"{key} = ?")
                params.append(str(value))

        if not set_clauses:
            return True  # Nothing to update, not an error

        set_clauses.append("updated_at = ?")
        params.append(datetime.now(UTC).isoformat())
        params.append(project_id)

        self._conn.execute(
            f"UPDATE projects SET {', '.join(set_clauses)} WHERE project_id = ?",
            params,
        )
        self._conn.commit()
        logger.info("Project updated", extra={"project_id": project_id, "fields": list(updates.keys())})
        return True

    def archive_project(self, project_id: str) -> bool:
        """
        Soft-archive a project. Archived projects are excluded from active
        analysis by default. Data is never deleted.
        Returns False if project not found.
        """
        return self.update_project(project_id, {"archived": True, "ingestion_enabled": False})

    def unarchive_project(self, project_id: str) -> bool:
        """Restore an archived project to active state."""
        return self.update_project(project_id, {"archived": False, "ingestion_enabled": True})

    # -----------------------------------------------------------------------
    # Read operations
    # -----------------------------------------------------------------------

    def get_project(self, project_id: str) -> Project | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_project(dict(row))

    def list_projects(
        self,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[Project]:
        assert self._conn is not None
        if include_archived:
            rows = self._conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM projects WHERE archived = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_project(dict(r)) for r in rows]

    def count_projects(self, include_archived: bool = True) -> int:
        assert self._conn is not None
        if include_archived:
            row = self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM projects WHERE archived = 0"
            ).fetchone()
        return int(row[0]) if row else 0

    def project_exists(self, project_id: str) -> bool:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return row is not None

    def list_active_project_ids(self) -> list[str]:
        """Return project_ids of active (non-archived, ingestion-enabled) projects."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT project_id FROM projects WHERE archived = 0 AND ingestion_enabled = 1"
        ).fetchall()
        return [r[0] for r in rows]

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    def project_summary(
        self,
        project_id: str,
        snapshot_count: int = 0,
        llm_event_count: int = 0,
        latest_snapshot_at: str | None = None,
        latest_event_at: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a project summary dict from pre-fetched stats.

        Stats (counts, timestamps) are passed in rather than fetched here
        to avoid cross-store coupling. Callers query each store separately.
        """
        project = self.get_project(project_id)
        if project is None:
            return {"error": f"Project '{project_id}' not found"}

        return {
            "project": project.to_dict(),
            "statistics": {
                "snapshot_count": snapshot_count,
                "llm_event_count": llm_event_count,
                "latest_snapshot_at": latest_snapshot_at,
                "latest_event_at": latest_event_at,
            },
            "status": {
                "active": project.is_active(),
                "archived": project.archived,
                "ingestion_enabled": project.ingestion_enabled,
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_project(row: dict[str, Any]) -> Project:
    return Project(
        project_id=str(row["project_id"]),
        name=str(row["name"]),
        description=str(row.get("description", "")),
        tags=_parse_json_list(row.get("tags", "[]")),
        created_at=str(row.get("created_at", "")),
        retention_profile=str(row.get("retention_profile", "standard")),
        deployment_profile=str(row.get("deployment_profile", "standard")),
        ingestion_enabled=bool(row.get("ingestion_enabled", 1)),
        archived=bool(row.get("archived", 0)),
        metadata=_parse_json_dict(row.get("metadata", "{}")),
        schema_version=str(row.get("schema_version", "1.0")),
    )


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            if isinstance(val, list):
                return [str(x) for x in val]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def _parse_json_dict(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            if isinstance(val, dict):
                return {str(k): str(v) for k, v in val.items()}
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _coerce_list(val: Any) -> list:
    if isinstance(val, list):
        return val
    return []


def _coerce_dict(val: Any) -> dict:
    if isinstance(val, dict):
        return val
    return {}
