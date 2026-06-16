"""Finding identity persistence layer.

Canonical finding identity is a deterministic SHA-256 hash of:
  (target_id, finding_type, resource, scope, collector_type)

Severity is EXCLUDED from the identity hash. It is mutable operational state.
Severity escalation (LOW → HIGH) updates the existing finding record in-place;
it does NOT create a new finding_id.

Wording changes (title, recommendation text) do NOT change finding identity.
"""

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUPPRESS_AFTER_COUNT = 3  # consecutive active appearances before suppression
MIN_SUPPRESSION_HOURS = 24  # minimum elapsed hours before count-based suppression activates

_SEVERITY_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# Deterministic operational relevance by finding_type.
# Survivability and security types are listed here.
# Recommendation findings use _FINDING_KEY_RELEVANCE in recommendation_engine.py.
OPERATIONAL_RELEVANCE_MAP: dict[str, str] = {
    # Survivability — all actionable: these are active system health issues
    "kernel_oom_kill": "actionable",
    "repeated_service_restart": "actionable",
    "dependency_unreachable": "actionable",
    "monitor_stale": "actionable",
    # Security — names match security_scanner.py finding_type fields (canonical identity)
    "credential_in_unit_file": "actionable",
    "world_readable_env_file": "informational",   # persists; low urgency; /root/ paths protected by dir perms
    "port_exposed_publicly": "actionable",         # specific port+process, requires operator decision
    # Infrastructure drift
    "stable_listener_disappeared": "actionable",
    "service_disappeared": "actionable",
    "coverage_gap": "informational",
    # Economic observability (Phase A) — spend is advisory; operator decides budget
    "economic_anomaly": "actionable",
    "spend_spike": "actionable",
    "abnormal_burn_rate": "actionable",
    "runaway_agent_cost": "actionable",
    "unknown_cost_owner": "actionable",     # spend exists; owner must be established
    "insufficient_context": "informational", # advisory: a recommendation was withheld
    # Project/engineering observability (Phase B) — situational awareness
    "project_activity": "informational",
    "engineering_burst": "informational",
    "subsystem_rebuild": "informational",
    "deployment_event": "actionable",       # a deploy is a change a human should know happened
    # Agent observability (Phase C)
    "agent_activity": "informational",
    "agent_cost": "actionable",
    "agent_burst": "informational",
    "agent_runtime": "informational",
}

# Actionability level is independent of severity.
# Example: monitor_stale is MEDIUM severity but HIGH actionability
# because a broken monitor is an operational blind spot.
ACTIONABILITY_MAP: dict[str, str] = {
    "kernel_oom_kill": "high",
    "repeated_service_restart": "medium",
    "dependency_unreachable": "high",
    "monitor_stale": "high",
    "credential_in_unit_file": "high",
    "world_readable_env_file": "medium",
    "port_exposed_publicly": "high",
    "stable_listener_disappeared": "high",
    "service_disappeared": "high",
    "coverage_gap": "low",
    # Economic
    "economic_anomaly": "high",
    "spend_spike": "high",
    "abnormal_burn_rate": "high",
    "runaway_agent_cost": "high",
    "unknown_cost_owner": "high",
    "insufficient_context": "low",
    # Project / engineering
    "project_activity": "low",
    "engineering_burst": "low",
    "subsystem_rebuild": "medium",
    "deployment_event": "medium",
    # Agent
    "agent_activity": "low",
    "agent_cost": "medium",
    "agent_burst": "low",
    "agent_runtime": "low",
}

_SEVERITY_RATIONALE: dict[str, str] = {
    "kernel_oom_kill": "Kernel OOM killer terminated the process — active memory exhaustion; all in-flight work was lost at termination.",
    "repeated_service_restart": "Service has restarted abnormally — indicates a crash loop, OOM pressure, or misconfiguration.",
    "dependency_unreachable": "Core dependency is unreachable — dependent services may be failing or timing out silently.",
    "monitor_stale": "Monitoring pipeline has not reported in the expected window — operational blind spot; failures may go undetected.",
    "credential_in_unit_file": "API credentials are embedded in a systemd unit file — readable by any user who can run 'systemctl cat'.",
    "world_readable_env_file": "Secret file has world-readable permissions — any local user can read API keys or tokens.",
    "port_exposed_publicly": "Service is bound to 0.0.0.0 — reachable from any network interface without a reverse proxy.",
    "stable_listener_disappeared": "A previously stable listening port is no longer present — the service may have crashed or been stopped.",
    "service_disappeared": "A running service is no longer active — indicates a crash, stop, or unexpected termination.",
    "coverage_gap": "Service has no scan coverage — topology and cost intelligence are absent for this workload.",
    # Economic
    "economic_anomaly": "Observed spend deviates from the established baseline — a new spender, model, or cost pattern appeared.",
    "spend_spike": "Spend in the window materially exceeds the trailing baseline — a sudden increase in LLM/API cost.",
    "abnormal_burn_rate": "Sustained USD-per-hour burn exceeds the configured rate — cost is accruing faster than expected.",
    "runaway_agent_cost": "A single workflow/agent dominated spend over a long uninterrupted run — the signature of an unattended cost runaway.",
    "unknown_cost_owner": "Paid LLM/API spend was observed that the system cannot attribute to any agent/project — ownership of the cost is undetermined.",
    "insufficient_context": "An economic recommendation was withheld because full accountability (who/what/where/when/which/cost) was not available — acting without it could mislead.",
    # Project / engineering
    "project_activity": "Engineering activity (commits/file changes) was observed in this repository during the window.",
    "engineering_burst": "Commit/file-change volume in the window crossed the burst threshold — a significant engineering push.",
    "subsystem_rebuild": "Changes concentrated heavily in one subsystem — that component was substantially rewritten or rebuilt.",
    "deployment_event": "Commits touched deployment infrastructure or declared a release — a deploy likely occurred.",
    # Agent
    "agent_activity": "A non-interactive agent (AI coding agent, bot, or automation) produced changes during the window.",
    "agent_cost": "LLM/API spend was attributed to this agent/project during the window.",
    "agent_burst": "Agent-attributed change volume in the window crossed the burst threshold — high autonomous activity.",
    "agent_runtime": "The agent was continuously active across a long span — long unattended runs are where cost and risk accrue.",
}


def reasoning_trace(finding: dict) -> str:
    """Deterministic one-to-three-sentence explanation of why a finding exists.

    Covers: type-specific trigger rationale, recurrence context, suppression state,
    and actionability context. No LLM. No probabilistic explanations. Fully reproducible.
    """
    ftype = finding.get("finding_type", "")
    severity = finding.get("severity", "UNKNOWN")
    count = finding.get("occurrence_count", 1)
    first = finding.get("first_seen", "")
    last = finding.get("last_seen", "")

    parts: list[str] = [
        _SEVERITY_RATIONALE.get(ftype, f"Finding type '{ftype}' detected.")
    ]
    if count > 1:
        date_str = first[:10] if first else "initial detection"
        parts.append(f"Observed {count} times since {date_str}.")
    if is_suppressed(count, first, last):
        parts.append("Suppressed from active display: seen 3+ times over 24h — stable known issue.")
    actionability = ACTIONABILITY_MAP.get(ftype, "medium")
    if actionability == "high":
        parts.append(f"High actionability: {severity} severity requires direct investigation.")
    elif actionability == "low":
        parts.append("Low actionability — informational context; no immediate action required.")
    return " ".join(parts)


def operator_posture(finding: dict) -> str:
    """Deterministic operator action posture.

    Returns one of:
    - 'immediate_attention': CRITICAL, or HIGH + high actionability
    - 'investigate':         HIGH + medium actionability, or MEDIUM + high actionability,
                             or MEDIUM + actionable relevance
    - 'monitor':             MEDIUM + medium actionability + informational relevance
    - 'informational_only':  LOW severity, or low actionability
    """
    severity = finding.get("severity", "LOW")
    ftype = finding.get("finding_type", "")
    actionability = ACTIONABILITY_MAP.get(ftype, "medium")
    relevance = OPERATIONAL_RELEVANCE_MAP.get(ftype, "informational")

    if severity == "CRITICAL":
        return "immediate_attention"
    if severity == "HIGH":
        if actionability == "high":
            return "immediate_attention"
        return "investigate"
    if severity == "MEDIUM":
        if actionability == "high":
            return "investigate"
        if relevance == "actionable":
            return "investigate"
        return "monitor"
    if actionability == "low" or relevance == "informational":
        return "informational_only"
    return "monitor"


def persistence_density(occurrence_count: int, first_seen: str, last_seen: str) -> float:
    """Return occurrences per day between first_seen and last_seen.

    Uses a 0.5-day floor so same-day findings don't produce artificially
    high density values. Falls back to float(occurrence_count) on bad timestamps.
    """
    try:
        fs = datetime.fromisoformat(first_seen)
        ls = datetime.fromisoformat(last_seen)
        elapsed_days = max(0.5, (ls - fs).total_seconds() / 86400)
        return round(occurrence_count / elapsed_days, 2)
    except Exception:
        return float(occurrence_count)


def trend_label(occurrence_count: int, density: float) -> str:
    """Deterministic trend classification for a finding.

    Returns one of: "new" | "recurring" | "persistent" | "frequent"

    - new:        first observation (count == 1)
    - recurring:  2–4 occurrences at low frequency
    - persistent: 5+ occurrences, or long-running at any count
    - frequent:   density >= 1.0/day (accelerating pattern)
    """
    if occurrence_count == 1:
        return "new"
    if density >= 1.0:
        return "frequent"
    if occurrence_count >= 5:
        return "persistent"
    return "recurring"


def is_suppressed(occurrence_count: int, first_seen: str, last_seen: str) -> bool:
    """Return True if a finding should be suppressed from display.

    Requires BOTH count threshold AND minimum elapsed duration.
    Prevents a finding that appears 3 times in rapid succession (e.g., within
    one hour) from being suppressed before the operator has seen it for a day.

    Falls back to count-only if timestamps are unparseable.
    """
    if occurrence_count < SUPPRESS_AFTER_COUNT:
        return False
    try:
        fs = datetime.fromisoformat(first_seen)
        ls = datetime.fromisoformat(last_seen)
        elapsed_hours = (ls - fs).total_seconds() / 3600
        return elapsed_hours >= MIN_SUPPRESSION_HOURS
    except Exception:
        return True  # unparseable timestamps: fall back to count-only suppression

_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    finding_id       TEXT PRIMARY KEY,
    target_id        TEXT NOT NULL,
    finding_type     TEXT NOT NULL,
    resource         TEXT NOT NULL,
    scope            TEXT NOT NULL,
    severity         TEXT NOT NULL,
    collector_type   TEXT NOT NULL,
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    resolved_at      TEXT,
    title            TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    recommendation   TEXT NOT NULL DEFAULT '',
    evidence         TEXT NOT NULL DEFAULT '[]',
    confidence       REAL NOT NULL DEFAULT 1.0,
    four_w           TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_findings_target
    ON findings(target_id, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_findings_active
    ON findings(resolved_at, severity, last_seen DESC);
CREATE TABLE IF NOT EXISTS finding_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    event_ts     TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_finding_events_fid
    ON finding_events(finding_id, event_ts DESC);
"""


def _canonicalize(
    target_id: str,
    finding_type: str,
    resource: str,
    scope: str,
    collector_type: str,
) -> dict[str, str]:
    """Normalize identity fields for deterministic hashing.

    Severity is intentionally excluded: it is operational state, not identity.
    The same finding observed at LOW severity and later at HIGH severity is the
    same finding — the severity column in the findings table is updated in-place.
    """
    return {
        "collector_type": collector_type.strip().lower(),
        "finding_type": finding_type.strip().lower().replace(" ", "_"),
        "resource": resource.strip().replace("\\", "/").rstrip("/").lower(),
        "scope": scope.strip().lower(),
        "target_id": target_id.strip().lower(),
    }


def compute_finding_id(
    target_id: str,
    finding_type: str,
    resource: str,
    scope: str,
    collector_type: str,
) -> str:
    """Deterministic SHA-256 finding identifier.

    Stable across: wording changes, severity escalation, occurrence count changes.
    Changes only when the structural identity changes: different target, type,
    resource, scope, or collector.
    """
    canonical = _canonicalize(target_id, finding_type, resource, scope, collector_type)
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"fnd_{digest[:32]}"


def _higher_severity(a: str, b: str) -> str:
    """Return the higher of two severity strings (HIGH > MEDIUM > LOW)."""
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


class FindingStore:
    """Persistent finding identity store backed by SQLite.

    Shares the same database file as OperationalStore (findings table is additive).
    Manages its own connection — do not share the connection with OperationalStore.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Additive migration: add four_w (4W intelligence) to pre-existing DBs.
        try:
            self._conn.execute("ALTER TABLE findings ADD COLUMN four_w TEXT NOT NULL DEFAULT '{}'")
            self._conn.commit()
            logger.info("FindingStore: added four_w column")
        except sqlite3.OperationalError:
            pass  # column already exists
        self._migrate_legacy_finding_ids()
        logger.info("FindingStore connected: %s", self._db_path)

    def disconnect(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _migrate_legacy_finding_ids(self) -> None:
        """Remap finding_ids computed with severity to new severity-free IDs.

        Idempotent: rows where stored finding_id already equals the recomputed
        ID are skipped. Safe to call on every connect().

        Collision handling: if two legacy findings (differing only by severity)
        map to the same new ID, they are merged — occurrence counts are summed,
        first_seen takes the minimum, last_seen takes the maximum, severity
        takes the higher value, resolved_at is NULL if either finding was active.
        """
        assert self._conn is not None
        rows = self._conn.execute("SELECT * FROM findings").fetchall()
        if not rows:
            return

        remapped = 0
        merged = 0

        for row in rows:
            old = dict(row)
            old_id = old["finding_id"]

            new_id = compute_finding_id(
                target_id=old["target_id"],
                finding_type=old["finding_type"],
                resource=old["resource"],
                scope=old["scope"],
                collector_type=old["collector_type"],
            )

            if new_id == old_id:
                continue  # Already using severity-free ID; skip

            collision = self._conn.execute(
                "SELECT * FROM findings WHERE finding_id = ?", (new_id,)
            ).fetchone()

            if collision is None:
                # Simple remap: update the primary key in place
                self._conn.execute(
                    "UPDATE findings SET finding_id = ? WHERE finding_id = ?",
                    (new_id, old_id),
                )
                remapped += 1
                logger.info(
                    "Finding remapped: %s → %s (severity removed from hash)",
                    old_id, new_id,
                )
            else:
                # Collision: two legacy findings that differed only by severity
                # now map to the same identity. Merge into the collision row.
                col = dict(collision)

                merged_first_seen = min(old["first_seen"], col["first_seen"])
                merged_last_seen = max(old["last_seen"], col["last_seen"])
                merged_count = old["occurrence_count"] + col["occurrence_count"]
                merged_severity = _higher_severity(old["severity"], col["severity"])

                # If either was active (resolved_at IS NULL), result is active
                old_resolved = old.get("resolved_at")
                col_resolved = col.get("resolved_at")
                if old_resolved is None or col_resolved is None:
                    merged_resolved_at = None
                else:
                    merged_resolved_at = max(old_resolved, col_resolved)

                self._conn.execute(
                    """UPDATE findings SET
                       first_seen = ?, last_seen = ?, occurrence_count = ?,
                       severity = ?, resolved_at = ?
                       WHERE finding_id = ?""",
                    (merged_first_seen, merged_last_seen, merged_count,
                     merged_severity, merged_resolved_at, new_id),
                )
                self._conn.execute(
                    "DELETE FROM findings WHERE finding_id = ?", (old_id,)
                )
                merged += 1
                logger.info(
                    "Finding merged: %s + %s → %s (severity collision resolved, count=%d)",
                    old_id, new_id, new_id, merged_count,
                )

        if remapped or merged:
            self._conn.commit()
            logger.info(
                "Legacy finding_id migration complete: %d remapped, %d merged",
                remapped, merged,
            )

    def _emit_event(self, finding_id: str, event_type: str, detail: str = "") -> None:
        """Append a lifecycle event to finding_events. Does not commit — caller commits."""
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO finding_events (finding_id, event_type, event_ts, detail) "
            "VALUES (?, ?, ?, ?)",
            (finding_id, event_type, datetime.now(UTC).isoformat(), detail),
        )

    def upsert(
        self,
        *,
        finding_id: str,
        target_id: str,
        finding_type: str,
        resource: str,
        scope: str,
        severity: str,
        collector_type: str,
        title: str,
        description: str = "",
        recommendation: str = "",
        evidence: list[str] | None = None,
        confidence: float = 1.0,
        four_w: dict | None = None,
    ) -> dict[str, Any]:
        """Insert or update a finding. Returns the current row state after write.

        - New finding:        occurrence_count = 1, first_seen = now
        - Existing active:    occurrence_count += 1, last_seen = now, severity updated
        - Reactivated:        occurrence_count reset to 1, resolved_at cleared

        Severity is stored and updated as mutable state. Escalation (LOW → HIGH)
        on the same finding_id updates the severity column without affecting
        finding_id, first_seen, or occurrence_count continuity.
        """
        assert self._conn is not None
        now = datetime.now(UTC).isoformat()
        evidence_json = json.dumps(evidence or [])
        four_w_json = json.dumps(four_w or {})

        existing = self._conn.execute(
            "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """INSERT INTO findings
                   (finding_id, target_id, finding_type, resource, scope, severity,
                    collector_type, first_seen, last_seen, occurrence_count,
                    title, description, recommendation, evidence, confidence, four_w)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                (finding_id, target_id, finding_type, resource, scope, severity,
                 collector_type, now, now, title, description, recommendation,
                 evidence_json, confidence, four_w_json),
            )
            logger.info(
                "Finding NEW: %s type=%s target=%s resource=%s severity=%s",
                finding_id, finding_type, target_id, resource, severity,
            )
            self._emit_event(finding_id, "created", f"severity={severity}")
        else:
            existing_dict = dict(existing)
            was_resolved = existing_dict.get("resolved_at") is not None
            prev_severity = existing_dict.get("severity", severity)

            if was_resolved:
                self._conn.execute(
                    """UPDATE findings SET
                       last_seen = ?, occurrence_count = 1, resolved_at = NULL,
                       title = ?, description = ?, recommendation = ?,
                       evidence = ?, confidence = ?, severity = ?, four_w = ?
                       WHERE finding_id = ?""",
                    (now, title, description, recommendation,
                     evidence_json, confidence, severity, four_w_json, finding_id),
                )
                logger.info(
                    "Finding REACTIVATED: %s type=%s target=%s severity=%s (was resolved)",
                    finding_id, finding_type, target_id, severity,
                )
                self._emit_event(finding_id, "reactivated", f"severity={severity}")
            else:
                if prev_severity != severity:
                    logger.info(
                        "Finding severity escalation: %s %s→%s (identity preserved)",
                        finding_id, prev_severity, severity,
                    )
                    self._emit_event(finding_id, "escalated", f"{prev_severity}→{severity}")
                self._conn.execute(
                    """UPDATE findings SET
                       last_seen = ?, occurrence_count = occurrence_count + 1,
                       title = ?, description = ?, recommendation = ?,
                       evidence = ?, confidence = ?, severity = ?, four_w = ?
                       WHERE finding_id = ?""",
                    (now, title, description, recommendation,
                     evidence_json, confidence, severity, four_w_json, finding_id),
                )
                logger.debug(
                    "Finding UPDATED: %s type=%s target=%s severity=%s",
                    finding_id, finding_type, target_id, severity,
                )

        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
        ).fetchone()
        return _deserialize_finding(dict(row))

    def mark_resolved(
        self,
        active_finding_ids: set[str],
        target_id: str,
        collector_type: str,
    ) -> int:
        """Mark findings as resolved if absent from the current active set.

        Scoped to target_id + collector_type — no cross-target interference.
        Returns count of newly resolved findings.
        """
        assert self._conn is not None
        now = datetime.now(UTC).isoformat()

        existing_active = self._conn.execute(
            """SELECT finding_id FROM findings
               WHERE target_id = ? AND collector_type = ? AND resolved_at IS NULL""",
            (target_id, collector_type),
        ).fetchall()

        to_resolve = [
            row["finding_id"] for row in existing_active
            if row["finding_id"] not in active_finding_ids
        ]
        if not to_resolve:
            return 0

        placeholders = ",".join("?" * len(to_resolve))
        self._conn.execute(
            f"UPDATE findings SET resolved_at = ? WHERE finding_id IN ({placeholders})",
            [now] + to_resolve,
        )
        for fid in to_resolve:
            self._emit_event(fid, "resolved", f"target={target_id} collector={collector_type}")
        self._conn.commit()
        logger.info(
            "Findings resolved: %d for target=%s collector=%s",
            len(to_resolve), target_id, collector_type,
        )
        return len(to_resolve)

    def get_active_findings(
        self,
        target_id: str | None = None,
        collector_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return unresolved findings, optionally scoped by target_id and/or collector_type."""
        assert self._conn is not None
        where = ["resolved_at IS NULL"]
        params: list[Any] = []
        if target_id is not None:
            where.append("target_id = ?")
            params.append(target_id)
        if collector_type is not None:
            where.append("collector_type = ?")
            params.append(collector_type)
        clause = " AND ".join(where)
        rows = self._conn.execute(
            f"SELECT * FROM findings WHERE {clause} ORDER BY last_seen DESC",
            params,
        ).fetchall()
        return [_deserialize_finding(dict(r)) for r in rows]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
        ).fetchone()
        return _deserialize_finding(dict(row)) if row else None

    def get_finding_events(self, finding_id: str) -> list[dict[str, Any]]:
        """Return the append-only event log for a finding, oldest first."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT event_type, event_ts, detail FROM finding_events "
            "WHERE finding_id = ? ORDER BY event_ts ASC",
            (finding_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_notification(self, finding_id: str, detail: str = "") -> None:
        """Append a 'notified' lifecycle event — the audit trail for a sent alert.

        Reuses the append-only finding_events log so a finding's notification
        history sits alongside its created/escalated/resolved events. Commits
        immediately (notifications are independent of any scan transaction).
        """
        assert self._conn is not None
        self._emit_event(finding_id, "notified", detail)
        self._conn.commit()

    def last_notification(self, finding_id: str) -> str | None:
        """Return the timestamp of the most recent 'notified' event, or None."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT MAX(event_ts) FROM finding_events "
            "WHERE finding_id = ? AND event_type = 'notified'",
            (finding_id,),
        ).fetchone()
        return str(row[0]) if row and row[0] else None


def _deserialize_finding(row: dict[str, Any]) -> dict[str, Any]:
    if "evidence" in row and isinstance(row["evidence"], str):
        try:
            row["evidence"] = json.loads(row["evidence"])
        except (json.JSONDecodeError, ValueError):
            row["evidence"] = []
    if "four_w" in row and isinstance(row["four_w"], str):
        try:
            row["four_w"] = json.loads(row["four_w"])
        except (json.JSONDecodeError, ValueError):
            row["four_w"] = {}
    return row
