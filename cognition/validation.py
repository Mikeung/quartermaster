"""
Cognition consistency validation — detect internal inconsistencies across synthesis outputs.

Purpose:
Catch outputs where heuristic thresholds or synthesis logic has drifted
such that findings contradict each other or make implausible claims.

Examples of inconsistencies detected:
- HIGH severity with zero supporting evidence
- Critical systemic concern with no contributing themes
- Unstable orchestration cluster with no orchestration patterns
- Ecosystem health "degrading" but no themes detected
- Confidence > 0.9 from a single snapshot
- High drift score with no significant drift dimensions

IMPORTANT:
- Validation WARNS. It does NOT auto-correct outputs.
- Findings are surfaced to operators/developers, not hidden.
- False positives are acceptable — false negatives are not.
- No modifications to any data structures.

Advisory only. Deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Validation warning codes
WARN_HIGH_SEVERITY_NO_EVIDENCE = "HIGH_SEVERITY_NO_EVIDENCE"
WARN_CRITICAL_CONCERN_NO_THEMES = "CRITICAL_CONCERN_NO_THEMES"
WARN_DEGRADING_HEALTH_NO_THEMES = "DEGRADING_HEALTH_NO_THEMES"
WARN_CONFIDENCE_TOO_HIGH_SINGLE_SNAP = "CONFIDENCE_TOO_HIGH_SINGLE_SNAP"
WARN_HIGH_DRIFT_NO_SIGNIFICANT_DIM = "HIGH_DRIFT_NO_SIGNIFICANT_DIM"
WARN_CLUSTER_ACTIVE_NO_SIGNALS = "CLUSTER_ACTIVE_NO_SIGNALS"
WARN_THEME_NO_EVIDENCE = "THEME_NO_EVIDENCE"
WARN_CONFIDENCE_OUT_OF_RANGE = "CONFIDENCE_OUT_OF_RANGE"
WARN_SYSTEMIC_SINGLE_THEME = "SYSTEMIC_SINGLE_THEME"
WARN_DRIFT_SCORE_INCONSISTENT = "DRIFT_SCORE_INCONSISTENT"


@dataclass
class ValidationWarning:
    """A single consistency warning from cognition validation."""
    code: str
    message: str
    severity: str  # "error" | "warning" | "info"
    context: dict[str, Any] = field(default_factory=dict)
    check_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "context": self.context,
            "check_name": self.check_name,
        }


@dataclass
class ConsistencyCheck:
    """Result of one named consistency check."""
    name: str
    description: str
    passed: bool
    warnings: list[ValidationWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "passed": self.passed,
            "warning_count": len(self.warnings),
            "warnings": [w.to_dict() for w in self.warnings],
        }


@dataclass
class ValidationReport:
    """Aggregate result of all consistency checks."""
    checks: list[ConsistencyCheck]
    total_warnings: int
    passed_checks: int
    failed_checks: int
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "total_warnings": self.total_warnings,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "generated_at": self.generated_at,
            "advisory": (
                "Validation warnings indicate potential inconsistencies. "
                "They do not modify outputs — human review is required."
            ),
        }

    def markdown(self) -> str:
        now = self.generated_at
        lines = [
            "# Cognition Consistency Validation Report",
            f"**Generated:** {now}",
            f"**Checks run:** {len(self.checks)}  "
            f"**Passed:** {self.passed_checks}  "
            f"**Failed:** {self.failed_checks}  "
            f"**Warnings:** {self.total_warnings}",
            "",
        ]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"## [{status}] {check.name}")
            lines.append(f"*{check.description}*")
            if check.warnings:
                for w in check.warnings:
                    prefix = "[WARNING]" if w.severity == "warning" else "[ERROR]" if w.severity == "error" else "[INFO]"
                    lines.append(f"- {prefix} `{w.code}`: {w.message}")
            else:
                lines.append("- No inconsistencies detected.")
            lines.append("")
        lines += [
            "---",
            "*Advisory only — validation warns operators. It does not modify outputs.*",
        ]
        return "\n".join(lines)


class CognitionValidator:
    """
    Run consistency checks across synthesis, clustering, drift, and snapshot outputs.

    Each check is independent — a failure in one does not prevent others from running.
    All checks are read-only.
    """

    def validate_synthesis(
        self, summary: dict[str, Any]
    ) -> ConsistencyCheck:
        """Check ecosystem synthesis output for internal consistency."""
        warnings: list[ValidationWarning] = []
        name = "synthesis_consistency"
        desc = "Ecosystem synthesis output consistency"

        overall = summary.get("overall_health", "unknown")
        themes = summary.get("themes", [])
        concerns = summary.get("systemic_concerns", [])
        confidence = summary.get("confidence", 0.0)
        snap_count = summary.get("snapshot_count", 0)

        # Degrading health with no themes
        if overall in ("degrading", "critical") and len(themes) == 0:
            warnings.append(ValidationWarning(
                code=WARN_DEGRADING_HEALTH_NO_THEMES,
                message=(
                    f"Overall health is '{overall}' but no operational themes were detected. "
                    "Health classification may be based on runtime data alone — verify."
                ),
                severity="warning",
                context={"overall_health": overall, "theme_count": 0},
                check_name=name,
            ))

        # Systemic concern with fewer than 2 contributing themes
        for concern in concerns:
            ct = concern.get("contributing_themes", [])
            if len(ct) < 2:
                warnings.append(ValidationWarning(
                    code=WARN_SYSTEMIC_SINGLE_THEME,
                    message=(
                        f"Systemic concern '{concern.get('title', '?')}' has "
                        f"fewer than 2 contributing themes ({len(ct)}). "
                        "Systemic concerns require cross-theme co-occurrence."
                    ),
                    severity="warning",
                    context={"title": concern.get("title"), "contributing_themes": ct},
                    check_name=name,
                ))

        # Confidence too high for single snapshot
        if confidence > 0.85 and snap_count <= 1:
            warnings.append(ValidationWarning(
                code=WARN_CONFIDENCE_TOO_HIGH_SINGLE_SNAP,
                message=(
                    f"Confidence {confidence:.2f} appears high for snapshot_count={snap_count}. "
                    "Single-snapshot confidence typically cannot exceed ~0.6."
                ),
                severity="warning",
                context={"confidence": confidence, "snapshot_count": snap_count},
                check_name=name,
            ))

        # Confidence out of range
        if not (0.0 <= confidence <= 1.0):
            warnings.append(ValidationWarning(
                code=WARN_CONFIDENCE_OUT_OF_RANGE,
                message=f"Confidence value {confidence} is outside valid range [0.0, 1.0].",
                severity="error",
                context={"confidence": confidence},
                check_name=name,
            ))

        # Theme has no evidence
        for theme in themes:
            if not theme.get("evidence"):
                warnings.append(ValidationWarning(
                    code=WARN_THEME_NO_EVIDENCE,
                    message=(
                        f"Theme '{theme.get('name', '?')}' has no evidence items. "
                        "Themes must be evidence-backed."
                    ),
                    severity="error",
                    context={"theme": theme.get("name")},
                    check_name=name,
                ))

        return ConsistencyCheck(
            name=name,
            description=desc,
            passed=len(warnings) == 0,
            warnings=warnings,
        )

    def validate_clusters(
        self, clusters: list[dict[str, Any]]
    ) -> ConsistencyCheck:
        """Check concern cluster output for activation consistency."""
        warnings: list[ValidationWarning] = []
        name = "cluster_consistency"
        desc = "Concern cluster activation consistency"

        for cluster in clusters:
            active = cluster.get("active", False)
            score = cluster.get("cluster_score", 0.0)
            member_patterns = cluster.get("member_patterns", [])
            member_recs = cluster.get("member_recommendations", [])
            cluster_name = cluster.get("name", "unknown")

            # Active cluster with no signals at all
            if active and not member_patterns and not member_recs:
                evidence = cluster.get("evidence", [])
                if not evidence:
                    warnings.append(ValidationWarning(
                        code=WARN_CLUSTER_ACTIVE_NO_SIGNALS,
                        message=(
                            f"Cluster '{cluster_name}' is active but has no member "
                            "patterns, recommendations, or evidence. Activation appears unsupported."
                        ),
                        severity="warning",
                        context={"cluster_name": cluster_name, "score": score},
                        check_name=name,
                    ))

            # Cluster score out of range
            if not (0.0 <= score <= 1.0):
                warnings.append(ValidationWarning(
                    code=WARN_CONFIDENCE_OUT_OF_RANGE,
                    message=f"Cluster '{cluster_name}' has score {score} outside [0.0, 1.0].",
                    severity="error",
                    context={"cluster_name": cluster_name, "score": score},
                    check_name=name,
                ))

        return ConsistencyCheck(
            name=name,
            description=desc,
            passed=len(warnings) == 0,
            warnings=warnings,
        )

    def validate_drift(
        self, analysis: dict[str, Any]
    ) -> ConsistencyCheck:
        """Check systemic drift analysis for consistency."""
        warnings: list[ValidationWarning] = []
        name = "drift_consistency"
        desc = "Systemic drift analysis consistency"

        overall_score = analysis.get("overall_drift_score", 0.0)
        sig_count = analysis.get("significant_drift_count", 0)
        trends = analysis.get("drift_trends", [])

        # High drift score but no significant dimensions
        if overall_score > 0.30 and sig_count == 0:
            warnings.append(ValidationWarning(
                code=WARN_HIGH_DRIFT_NO_SIGNIFICANT_DIM,
                message=(
                    f"Overall drift score {overall_score:.2f} is elevated "
                    f"but significant_drift_count is 0. "
                    "Score should reflect significant dimensions."
                ),
                severity="warning",
                context={"overall_drift_score": overall_score, "significant_count": sig_count},
                check_name=name,
            ))

        # Inconsistency: sig_count reported differs from computed
        computed_sig = sum(1 for t in trends if t.get("significant", False))
        if sig_count != computed_sig:
            warnings.append(ValidationWarning(
                code=WARN_DRIFT_SCORE_INCONSISTENT,
                message=(
                    f"significant_drift_count={sig_count} but "
                    f"{computed_sig} trend(s) have significant=True. "
                    "Count does not match trend flags."
                ),
                severity="error",
                context={"reported": sig_count, "computed": computed_sig},
                check_name=name,
            ))

        # Drift score out of range
        if not (0.0 <= overall_score <= 1.0):
            warnings.append(ValidationWarning(
                code=WARN_CONFIDENCE_OUT_OF_RANGE,
                message=f"overall_drift_score {overall_score} is outside [0.0, 1.0].",
                severity="error",
                context={"overall_drift_score": overall_score},
                check_name=name,
            ))

        return ConsistencyCheck(
            name=name,
            description=desc,
            passed=len(warnings) == 0,
            warnings=warnings,
        )

    def validate_recommendations(
        self, recommendations: list[dict[str, Any]]
    ) -> ConsistencyCheck:
        """Check recommendations for internal consistency."""
        warnings: list[ValidationWarning] = []
        name = "recommendation_consistency"
        desc = "Recommendation internal consistency"

        for rec in recommendations:
            title = rec.get("title", "?")
            impact = rec.get("impact", "")
            evidence = rec.get("evidence", [])
            confidence = rec.get("confidence", None)

            # High impact with no evidence
            if impact in ("high", "critical") and not evidence:
                warnings.append(ValidationWarning(
                    code=WARN_HIGH_SEVERITY_NO_EVIDENCE,
                    message=(
                        f"Recommendation '{title}' has impact='{impact}' "
                        "but no supporting evidence. High-impact items require evidence."
                    ),
                    severity="warning",
                    context={"title": title, "impact": impact},
                    check_name=name,
                ))

            # Confidence out of range
            if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
                warnings.append(ValidationWarning(
                    code=WARN_CONFIDENCE_OUT_OF_RANGE,
                    message=f"Recommendation '{title}' has confidence={confidence} outside [0.0, 1.0].",
                    severity="error",
                    context={"title": title, "confidence": confidence},
                    check_name=name,
                ))

        return ConsistencyCheck(
            name=name,
            description=desc,
            passed=len(warnings) == 0,
            warnings=warnings,
        )

    def run_all(
        self,
        *,
        summary: dict[str, Any] | None = None,
        clusters: list[dict[str, Any]] | None = None,
        drift: dict[str, Any] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> ValidationReport:
        """Run all applicable consistency checks and return a ValidationReport."""
        checks: list[ConsistencyCheck] = []

        if summary is not None:
            checks.append(self.validate_synthesis(summary))
        if clusters is not None:
            checks.append(self.validate_clusters(clusters))
        if drift is not None:
            checks.append(self.validate_drift(drift))
        if recommendations is not None:
            checks.append(self.validate_recommendations(recommendations))

        total_warnings = sum(len(c.warnings) for c in checks)
        passed = sum(1 for c in checks if c.passed)
        failed = len(checks) - passed

        logger.info(
            "Cognition validation complete",
            extra={"checks": len(checks), "warnings": total_warnings, "failed": failed},
        )

        return ValidationReport(
            checks=checks,
            total_warnings=total_warnings,
            passed_checks=passed,
            failed_checks=failed,
            generated_at=datetime.now(UTC).isoformat(),
        )
