"""
Investigation consolidation — reduce recommendation fragmentation.

Current issue: many recommendations may describe the same underlying operational theme.
This module groups related recommendations and collapses redundant findings into
consolidated concerns with shared evidence.

Example:
  5 recommendations about: retries, OCR, memory pressure, orchestration overhead
  → consolidated into: "High-cost unstable OCR processing workflow"

Requirements:
- deterministic only
- bounded grouping (by category, then by evidence keyword overlap)
- preserve traceability (all source recommendations cited)
- explainable membership criteria

Advisory only. Does not modify source recommendations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cognition.heuristics import HeuristicRegistry

logger = logging.getLogger(__name__)

_HEURISTICS = HeuristicRegistry()

# ---------------------------------------------------------------------------
# Category group labels — used to name consolidated concerns
# ---------------------------------------------------------------------------

_CATEGORY_LABELS: dict[str, str] = {
    "cost": "Cost Management",
    "llm": "LLM Operations",
    "token": "Token Efficiency",
    "performance": "Performance",
    "stability": "Operational Stability",
    "reliability": "Reliability",
    "observability": "Observability",
    "security": "Security",
    "orchestration": "Orchestration",
    "workflow": "Workflow Configuration",
    "provider": "Provider Management",
    "routing": "LLM Routing",
}

# Keywords used to detect evidence overlap between recommendations
_EVIDENCE_KEYWORDS: list[str] = [
    "ocr", "retry", "token", "cost", "memory", "orchestration", "agent",
    "provider", "langchain", "autogen", "rag", "vector", "embedding",
    "docker", "service", "workflow", "stream",
]


@dataclass
class ConsolidatedConcern:
    """A consolidated operational concern derived from multiple related recommendations.

    Preserves all source recommendation titles for traceability.
    """
    title: str
    description: str
    contributing_recs: list[str]        # source recommendation titles
    contributing_patterns: list[str]    # pattern names (if cluster provided)
    shared_evidence: list[str]          # evidence items that appeared in multiple sources
    category_tags: list[str]
    severity_hint: str
    confidence: float
    member_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "contributing_recs": self.contributing_recs,
            "contributing_patterns": self.contributing_patterns,
            "shared_evidence": self.shared_evidence,
            "category_tags": self.category_tags,
            "severity_hint": self.severity_hint,
            "confidence": round(self.confidence, 3),
            "member_count": self.member_count,
            "note": "Consolidated from source recommendations — all sources preserved for traceability.",
        }


class ConsolidationEngine:
    """Groups and collapses related recommendations into consolidated concerns.

    Pass 1: Group by primary category.
    Pass 2: Within each category group, merge by shared evidence keywords.
    Pass 3: If clusters are provided, use cluster membership to bridge cross-category groups.
    """

    def consolidate(
        self,
        recommendations: list[dict[str, Any]],
        patterns: list[dict[str, Any]] | None = None,
        clusters: list[dict[str, Any]] | None = None,
    ) -> list[ConsolidatedConcern]:
        """Produce consolidated concerns from a list of recommendations.

        recommendations: list of serialized Recommendation dicts
        patterns: optional list of matched OperationalPattern dicts
        clusters: optional list of serialized ConcernCluster dicts (active only)
        """
        if not recommendations:
            return []

        matched_pattern_names = {
            p["name"] for p in (patterns or []) if p.get("matched")
        }

        # Pass 1: group by category
        by_category: dict[str, list[dict]] = {}
        for rec in recommendations:
            cat = rec.get("category", "unknown")
            by_category.setdefault(cat, []).append(rec)

        # Pass 2: within each category, merge by evidence keyword overlap
        consolidated: list[ConsolidatedConcern] = []
        for category, recs in by_category.items():
            groups = self._group_by_evidence_overlap(recs)
            for group in groups:
                concern = self._build_concern(group, category, matched_pattern_names)
                consolidated.append(concern)

        # Pass 3: cross-category cluster bridging
        if clusters:
            consolidated = self._apply_cluster_bridging(consolidated, clusters)

        consolidated.sort(key=lambda c: (-c.member_count, -c.confidence))

        logger.info(
            "Consolidation complete",
            extra={
                "input_recommendations": len(recommendations),
                "output_concerns": len(consolidated),
            },
        )
        return consolidated

    def _group_by_evidence_overlap(
        self, recs: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """Group recommendations by shared evidence keywords.

        Uses a simple union-find on keyword co-occurrence.
        Deterministic: sorts recs by title before grouping.
        """
        min_shared = int(_HEURISTICS.threshold("consolidation_min_shared_evidence"))
        sorted_recs = sorted(recs, key=lambda r: r.get("title", ""))

        def keywords(rec: dict) -> set[str]:
            text = " ".join([
                rec.get("title", ""),
                rec.get("category", ""),
                " ".join(rec.get("evidence", [])),
            ]).lower()
            return {kw for kw in _EVIDENCE_KEYWORDS if kw in text}

        groups: list[list[dict]] = []
        assigned: set[int] = set()

        for i, rec_a in enumerate(sorted_recs):
            if i in assigned:
                continue
            group = [rec_a]
            assigned.add(i)
            kw_a = keywords(rec_a)
            for j, rec_b in enumerate(sorted_recs):
                if j <= i or j in assigned:
                    continue
                kw_b = keywords(rec_b)
                if len(kw_a & kw_b) >= min_shared:
                    group.append(rec_b)
                    assigned.add(j)
                    kw_a = kw_a | kw_b  # expand keyword set for chaining
            groups.append(group)

        return groups

    def _build_concern(
        self,
        recs: list[dict[str, Any]],
        category: str,
        matched_patterns: set[str],
    ) -> ConsolidatedConcern:
        titles = [r.get("title", "") for r in recs]
        all_evidence: list[str] = []
        for rec in recs:
            all_evidence.extend(rec.get("evidence", []))

        # Find shared evidence (appears in 2+ source recommendations)
        evidence_counts: dict[str, int] = {}
        for ev in all_evidence:
            evidence_counts[ev] = evidence_counts.get(ev, 0) + 1
        shared = [ev for ev, count in evidence_counts.items() if count >= 2][:4]
        if not shared:
            shared = all_evidence[:3]

        # Severity: take the highest from member recs
        impacts = [r.get("impact", "low") for r in recs]
        severity = "high" if "high" in impacts else ("moderate" if "medium" in impacts else "low")

        # Confidence: average
        confs = [float(r.get("confidence", 0.5)) for r in recs]
        confidence = round(sum(confs) / len(confs), 3)

        # Title: use first rec title if single, else generate from category
        cat_label = _CATEGORY_LABELS.get(category, category.replace("_", " ").title())
        if len(recs) == 1:
            title = titles[0]
        else:
            title = f"{cat_label} — {len(recs)} related concern(s)"

        description = (
            f"Consolidated from {len(recs)} {cat_label.lower()} recommendation(s). "
            f"Grouped by shared evidence keywords."
        )

        # Related patterns from same category
        related_patterns = [
            p for p in matched_patterns
            if category.lower() in p.replace("_", " ").lower()
        ]

        return ConsolidatedConcern(
            title=title,
            description=description,
            contributing_recs=titles,
            contributing_patterns=related_patterns[:3],
            shared_evidence=shared,
            category_tags=[category],
            severity_hint=severity,
            confidence=confidence,
            member_count=len(recs),
        )

    def _apply_cluster_bridging(
        self,
        concerns: list[ConsolidatedConcern],
        clusters: list[dict[str, Any]],
    ) -> list[ConsolidatedConcern]:
        """Merge concerns that belong to the same active cluster.

        If two concerns share significant membership in the same cluster,
        merge them into a single cross-category concern.
        """
        result: list[ConsolidatedConcern] = []
        merged: set[int] = set()

        active_clusters = [c for c in clusters if c.get("active")]

        for i, concern_a in enumerate(concerns):
            if i in merged:
                continue
            merged_group = [concern_a]
            for j, concern_b in enumerate(concerns):
                if j <= i or j in merged:
                    continue
                # Check if both concerns appear in the same cluster
                for cluster in active_clusters:
                    cluster_recs = set(cluster.get("member_recommendations", []))
                    a_in_cluster = any(r in cluster_recs for r in concern_a.contributing_recs)
                    b_in_cluster = any(r in cluster_recs for r in concern_b.contributing_recs)
                    if a_in_cluster and b_in_cluster:
                        merged_group.append(concern_b)
                        merged.add(j)
                        break
            if len(merged_group) > 1:
                result.append(_merge_concerns(merged_group))
            else:
                result.append(concern_a)

        return result


def _merge_concerns(concerns: list[ConsolidatedConcern]) -> ConsolidatedConcern:
    all_recs = []
    all_evidence = []
    all_patterns = []
    all_tags = []

    for c in concerns:
        all_recs.extend(c.contributing_recs)
        all_evidence.extend(c.shared_evidence)
        all_patterns.extend(c.contributing_patterns)
        all_tags.extend(c.category_tags)

    unique_recs = list(dict.fromkeys(all_recs))
    unique_evidence = list(dict.fromkeys(all_evidence))[:5]
    unique_patterns = list(dict.fromkeys(all_patterns))[:4]
    unique_tags = list(dict.fromkeys(all_tags))

    impacts = [c.severity_hint for c in concerns]
    severity = "high" if "high" in impacts else ("moderate" if "moderate" in impacts else "low")
    confidence = round(sum(c.confidence for c in concerns) / len(concerns), 3)

    tag_labels = [_CATEGORY_LABELS.get(t, t) for t in unique_tags[:2]]
    title = f"{' + '.join(tag_labels)} — {len(unique_recs)} cross-cutting concern(s)"

    return ConsolidatedConcern(
        title=title,
        description=(
            f"Cross-category consolidation from {len(concerns)} concern group(s) "
            f"with shared cluster membership."
        ),
        contributing_recs=unique_recs,
        contributing_patterns=unique_patterns,
        shared_evidence=unique_evidence,
        category_tags=unique_tags,
        severity_hint=severity,
        confidence=confidence,
        member_count=len(unique_recs),
    )
