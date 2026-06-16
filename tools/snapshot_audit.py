"""
Snapshot integrity auditing — read-only quality check for stored snapshots.

Detects:
- missing required sections
- malformed data types
- empty evidence chains in recommendations
- invalid confidence ranges (< 0 or > 1)
- inconsistent timestamps (out-of-order)
- orphaned recommendations (missing category or impact fields)
- unusual recommendation volume (potential scan anomaly)

IMPORTANT:
- Read-only tooling. Does NOT modify snapshots.
- Audit findings are informational — not directives.
- Advisory only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_AUDIT_CATEGORIES = {
    "schema": "Missing or malformed required fields",
    "evidence": "Empty or shallow evidence chains",
    "confidence": "Out-of-range confidence values",
    "timestamp": "Timestamp ordering or format issues",
    "volume": "Unusual data volume (potential anomaly)",
    "orphan": "Incomplete recommendation records",
}


@dataclass
class AuditFinding:
    snapshot_id: int | None  # None if cross-snapshot finding
    category: str            # from _AUDIT_CATEGORIES keys
    message: str
    severity: str            # "error", "warning", "info"
    field: str               # which field is affected (e.g. "data.recommendations")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "category": self.category,
            "message": self.message,
            "severity": self.severity,
            "field": self.field,
        }


@dataclass
class AuditReport:
    total_snapshots: int
    clean_snapshots: int       # snapshots with no errors or warnings (info findings do not disqualify)
    findings: list[AuditFinding]
    error_count: int
    warning_count: int
    info_count: int
    audited_at: str            # ISO UTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_snapshots": self.total_snapshots,
            "clean_snapshots": self.clean_snapshots,
            "findings": [f.to_dict() for f in self.findings],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "audited_at": self.audited_at,
        }

    def markdown(self) -> str:
        lines: list[str] = []

        lines.append("# Snapshot Audit Report")
        lines.append("")
        lines.append(f"**Audited at:** {self.audited_at}")
        lines.append(f"**Total snapshots:** {self.total_snapshots}")
        lines.append(f"**Clean snapshots:** {self.clean_snapshots}")
        lines.append("")
        lines.append("## Finding Counts")
        lines.append("")
        lines.append(f"- Errors: {self.error_count}")
        lines.append(f"- Warnings: {self.warning_count}")
        lines.append(f"- Info: {self.info_count}")
        lines.append("")

        if not self.findings:
            lines.append("## Findings")
            lines.append("")
            lines.append("No findings. All snapshots passed audit checks.")
        else:
            # Group findings by category
            by_category: dict[str, list[AuditFinding]] = {}
            for finding in self.findings:
                by_category.setdefault(finding.category, []).append(finding)

            lines.append("## Findings by Category")
            lines.append("")
            for category, cat_findings in sorted(by_category.items()):
                cat_label = _AUDIT_CATEGORIES.get(category, category)
                lines.append(f"### {category.title()} — {cat_label}")
                lines.append("")
                for f in cat_findings:
                    snap_label = (
                        f"snapshot {f.snapshot_id}"
                        if f.snapshot_id is not None
                        else "cross-snapshot"
                    )
                    lines.append(
                        f"- **[{f.severity.upper()}]** ({snap_label}) `{f.field}`: {f.message}"
                    )
                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            "_This audit is advisory only. Findings are informational and do not "
            "trigger automatic remediation. Review and act at your discretion._"
        )

        return "\n".join(lines)


class SnapshotAuditor:
    """Read-only auditor for stored snapshots."""

    def audit(self, snapshots: list[dict]) -> AuditReport:
        """Run all checks across a list of snapshots and build an aggregate report."""
        all_findings: list[AuditFinding] = []

        # Per-snapshot checks
        # dirty = has at least one error or warning (info findings are not disqualifying)
        dirty_ids: set[int | None] = set()
        for snapshot in snapshots:
            findings = self.audit_single(snapshot)
            all_findings.extend(findings)
            has_actionable = any(f.severity in ("error", "warning") for f in findings)
            if has_actionable:
                sid = snapshot.get("id")
                dirty_ids.add(sid)

        # Cross-snapshot checks
        cross_findings = self._check_timestamps(snapshots)
        all_findings.extend(cross_findings)
        # Cross-snapshot findings use snapshot_id=None — do not mark individual snapshots dirty

        error_count = sum(1 for f in all_findings if f.severity == "error")
        warning_count = sum(1 for f in all_findings if f.severity == "warning")
        info_count = sum(1 for f in all_findings if f.severity == "info")

        # Clean = snapshots with no errors or warnings (info findings are informational only)
        clean_snapshots = len(snapshots) - len(
            {sid for sid in dirty_ids if sid is not None}
        )

        audited_at = datetime.now(UTC).isoformat()

        return AuditReport(
            total_snapshots=len(snapshots),
            clean_snapshots=clean_snapshots,
            findings=all_findings,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            audited_at=audited_at,
        )

    def audit_single(self, snapshot: dict) -> list[AuditFinding]:
        """Run all single-snapshot checks and return aggregated findings."""
        findings: list[AuditFinding] = []
        findings.extend(self._check_schema(snapshot))
        findings.extend(self._check_timestamp_format(snapshot))
        findings.extend(self._check_evidence_chains(snapshot))
        findings.extend(self._check_confidence_ranges(snapshot))
        findings.extend(self._check_orphaned_recs(snapshot))
        findings.extend(self._check_volume(snapshot))
        return findings

    def _check_timestamp_format(self, snapshot: dict) -> list[AuditFinding]:
        """Check that created_at is a parseable ISO timestamp."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")
        raw_ts = snapshot.get("created_at")
        if raw_ts is None:
            return findings  # already caught by schema check
        try:
            datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="timestamp",
                message=f"created_at is not a parseable ISO timestamp: {raw_ts!r}",
                severity="error",
                field="created_at",
            ))
        return findings

    # ------------------------------------------------------------------
    # Per-snapshot checks
    # ------------------------------------------------------------------

    def _check_schema(self, snapshot: dict) -> list[AuditFinding]:
        """Check required top-level fields and expected data structure."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")

        if "id" not in snapshot:
            findings.append(AuditFinding(
                snapshot_id=None,
                category="schema",
                message="Snapshot is missing required field 'id'",
                severity="error",
                field="id",
            ))

        if "created_at" not in snapshot:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message="Snapshot is missing required field 'created_at'",
                severity="error",
                field="created_at",
            ))

        if "data" not in snapshot:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message="Snapshot is missing required field 'data'",
                severity="error",
                field="data",
            ))
            # Cannot check sub-fields without data
            return findings

        data = snapshot["data"]

        if not isinstance(data, dict):
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message=f"Field 'data' must be a dict, got {type(data).__name__}",
                severity="error",
                field="data",
            ))
            return findings

        if "recommendations" not in data:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message="Missing field 'data.recommendations'",
                severity="error",
                field="data.recommendations",
            ))
        elif not isinstance(data["recommendations"], list):
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message=(
                    f"Field 'data.recommendations' must be a list, "
                    f"got {type(data['recommendations']).__name__}"
                ),
                severity="error",
                field="data.recommendations",
            ))

        if "scanner_results" not in data:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message="Missing field 'data.scanner_results'",
                severity="error",
                field="data.scanner_results",
            ))
        elif not isinstance(data["scanner_results"], dict):
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="schema",
                message=(
                    f"Field 'data.scanner_results' must be a dict, "
                    f"got {type(data['scanner_results']).__name__}"
                ),
                severity="error",
                field="data.scanner_results",
            ))

        return findings

    def _check_evidence_chains(self, snapshot: dict) -> list[AuditFinding]:
        """Flag recommendations with empty or shallow evidence chains."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")
        recs = snapshot.get("data", {}).get("recommendations")
        if not isinstance(recs, list):
            return findings

        for i, rec in enumerate(recs):
            if not isinstance(rec, dict):
                continue
            evidence = rec.get("evidence")
            if evidence is None:
                continue
            if isinstance(evidence, list):
                if len(evidence) == 0:
                    findings.append(AuditFinding(
                        snapshot_id=sid,
                        category="evidence",
                        message=f"Recommendation[{i}] has an empty evidence list",
                        severity="warning",
                        field=f"data.recommendations[{i}].evidence",
                    ))
                elif len(evidence) == 1 and isinstance(evidence[0], str) and evidence[0].strip() == "":
                    findings.append(AuditFinding(
                        snapshot_id=sid,
                        category="evidence",
                        message=f"Recommendation[{i}] has a single empty-string evidence entry",
                        severity="warning",
                        field=f"data.recommendations[{i}].evidence",
                    ))

        return findings

    def _check_confidence_ranges(self, snapshot: dict) -> list[AuditFinding]:
        """Flag confidence values outside [0.0, 1.0]."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")
        recs = snapshot.get("data", {}).get("recommendations")
        if not isinstance(recs, list):
            return findings

        for i, rec in enumerate(recs):
            if not isinstance(rec, dict):
                continue
            if "confidence" not in rec:
                continue
            conf = rec["confidence"]
            if not isinstance(conf, (int, float)):
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="confidence",
                    message=(
                        f"Recommendation[{i}] confidence is not a number: {conf!r}"
                    ),
                    severity="error",
                    field=f"data.recommendations[{i}].confidence",
                ))
                continue
            if conf < 0.0 or conf > 1.0:
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="confidence",
                    message=(
                        f"Recommendation[{i}] has invalid confidence {conf} "
                        f"(must be in [0.0, 1.0])"
                    ),
                    severity="error",
                    field=f"data.recommendations[{i}].confidence",
                ))

        return findings

    def _check_orphaned_recs(self, snapshot: dict) -> list[AuditFinding]:
        """Flag recommendations missing required or expected fields."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")
        recs = snapshot.get("data", {}).get("recommendations")
        if not isinstance(recs, list):
            return findings

        for i, rec in enumerate(recs):
            if not isinstance(rec, dict):
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="orphan",
                    message=f"Recommendation[{i}] is not a dict: {type(rec).__name__}",
                    severity="error",
                    field=f"data.recommendations[{i}]",
                ))
                continue

            if "title" not in rec:
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="orphan",
                    message=f"Recommendation[{i}] is missing required field 'title'",
                    severity="error",
                    field=f"data.recommendations[{i}].title",
                ))

            if "category" not in rec:
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="orphan",
                    message=f"Recommendation[{i}] is missing field 'category'",
                    severity="warning",
                    field=f"data.recommendations[{i}].category",
                ))

            if "impact" not in rec:
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="orphan",
                    message=f"Recommendation[{i}] is missing field 'impact'",
                    severity="warning",
                    field=f"data.recommendations[{i}].impact",
                ))

        return findings

    def _check_volume(self, snapshot: dict) -> list[AuditFinding]:
        """Flag unusually high or zero recommendation counts."""
        findings: list[AuditFinding] = []
        sid = snapshot.get("id")
        recs = snapshot.get("data", {}).get("recommendations")
        if not isinstance(recs, list):
            return findings

        count = len(recs)
        if count > 50:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="volume",
                message=(
                    f"Unusually high recommendation volume: {count} recommendations "
                    f"(threshold: 50) — possible scan anomaly"
                ),
                severity="info",
                field="data.recommendations",
            ))
        elif count == 0:
            findings.append(AuditFinding(
                snapshot_id=sid,
                category="volume",
                message="No recommendations present in snapshot",
                severity="info",
                field="data.recommendations",
            ))

        return findings

    # ------------------------------------------------------------------
    # Cross-snapshot checks
    # ------------------------------------------------------------------

    def _check_timestamps(self, snapshots: list[dict]) -> list[AuditFinding]:
        """Cross-snapshot check for timestamp ordering and parseability."""
        findings: list[AuditFinding] = []

        parsed: list[tuple[int, datetime]] = []
        for snapshot in snapshots:
            sid = snapshot.get("id")
            raw_ts = snapshot.get("created_at")
            if raw_ts is None:
                # Missing created_at already caught by schema check
                continue
            try:
                dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                parsed.append((sid, dt))
            except (ValueError, TypeError):
                findings.append(AuditFinding(
                    snapshot_id=sid,
                    category="timestamp",
                    message=f"created_at value is not a parseable ISO timestamp: {raw_ts!r}",
                    severity="error",
                    field="created_at",
                ))

        # Check ascending order
        for i in range(1, len(parsed)):
            prev_sid, prev_dt = parsed[i - 1]
            curr_sid, curr_dt = parsed[i]
            if curr_dt < prev_dt:
                findings.append(AuditFinding(
                    snapshot_id=None,
                    category="timestamp",
                    message=(
                        f"Snapshots are not in ascending created_at order: "
                        f"snapshot {prev_sid} ({prev_dt.isoformat()}) "
                        f"is after snapshot {curr_sid} ({curr_dt.isoformat()})"
                    ),
                    severity="warning",
                    field="created_at",
                ))

        return findings
