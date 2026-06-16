"""
Explicit domain vocabulary for Quartermaster.

These models define the semantic concepts the system works with:
assets, relationships, workflows, drift events, LLM usage, and evidence.

They are descriptive — they clarify what the system observes and reports.
They are NOT a replacement for the graph models in topology/models.py,
which handle the runtime topology graph construction.

All models are advisory-only. None trigger autonomous action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AssetKind(str, Enum):
    REPOSITORY = "repository"
    SERVICE = "service"
    LLM_PROVIDER = "llm_provider"
    VECTOR_STORE = "vector_store"
    WORKFLOW_ENGINE = "workflow_engine"
    CONTAINER = "container"
    PROCESS = "process"
    NETWORK_PORT = "network_port"
    FRAMEWORK = "framework"


class RelationshipKind(str, Enum):
    USES = "uses"
    RUNS_IN = "runs_in"
    EXPOSES = "exposes"
    DEPENDS_ON = "depends_on"
    ORCHESTRATES = "orchestrates"
    ROUTES_TO = "routes_to"


class WorkflowPatternKind(str, Enum):
    TELEGRAM_LLM_PIPELINE = "telegram_llm_pipeline"
    OCR_SUMMARIZATION = "ocr_summarization"
    API_LLM_WRAPPER = "api_llm_wrapper"
    SCHEDULED_LLM_JOB = "scheduled_llm_job"
    MULTI_PROVIDER_ORCHESTRATION = "multi_provider_orchestration"
    RAG_PIPELINE = "rag_pipeline"
    MULTI_AGENT_SYSTEM = "multi_agent_system"
    ASYNC_LLM_WORKER = "async_llm_worker"


class DriftKind(str, Enum):
    LLM_PROVIDER_ADDED = "llm_provider_added"
    LLM_PROVIDER_REMOVED = "llm_provider_removed"
    FRAMEWORK_ADDED = "framework_added"
    FRAMEWORK_REMOVED = "framework_removed"
    DOCKER_INTRODUCED = "docker_introduced"
    DOCKER_REMOVED = "docker_removed"
    CI_INTRODUCED = "ci_introduced"
    CI_REMOVED = "ci_removed"
    LANGUAGE_CHANGED = "language_changed"


@dataclass(frozen=True)
class EvidenceItem:
    """A single piece of evidence supporting an inference or recommendation."""
    source: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "detail": self.detail}


@dataclass
class Asset:
    """A discovered infrastructure element — repository, service, provider, port, etc.

    Assets are facts: they were observed to exist. No interpretation attached here.
    """
    id: str
    kind: AssetKind
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "label": self.label,
            "metadata": self.metadata,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass
class AssetRelationship:
    """A detected relationship between two assets.

    Relationships carry evidence and a confidence score because they are inferred,
    not directly observed. A relationship is never asserted without evidence.
    """
    source_id: str
    target_id: str
    kind: RelationshipKind
    confidence: float
    evidence: list[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind.value,
            "confidence": round(self.confidence, 2),
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class WorkflowPattern:
    """A high-level AI workflow pattern inferred from topology and package evidence.

    Patterns are inferences — they are always accompanied by the evidence that
    triggered them and a confidence score reflecting inference certainty.
    """
    pattern: WorkflowPatternKind
    name: str
    description: str
    confidence: float
    evidence: list[EvidenceItem]
    llm_providers: list[str]
    estimated_cost_tier: str  # "low", "medium", "high", "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern.value,
            "name": self.name,
            "description": self.description,
            "confidence": round(self.confidence, 2),
            "evidence": [e.to_dict() for e in self.evidence],
            "llm_providers": self.llm_providers,
            "estimated_cost_tier": self.estimated_cost_tier,
        }


@dataclass
class DriftEvent:
    """A detected change between two consecutive operational snapshots.

    Drift events are facts: something changed. They do not prescribe action.
    """
    kind: DriftKind
    description: str
    before: str | None
    after: str | None
    snapshot_id: int
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "description": self.description,
            "before": self.before,
            "after": self.after,
            "snapshot_id": self.snapshot_id,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class LLMUsageProfile:
    """Aggregated view of LLM usage in an observed system.

    Constructed from structural evidence — package manifests, import patterns,
    active ports. Not from billing data or runtime telemetry.
    All values are heuristic estimates, not measurements.
    """
    providers: list[str]
    workflow_patterns: list[WorkflowPatternKind]
    estimated_cost_tier: str  # "low", "medium", "high", "unknown"
    has_vector_store: bool
    has_workflow_engine: bool
    has_usage_tracking: bool
    cost_observations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": self.providers,
            "workflow_patterns": [p.value for p in self.workflow_patterns],
            "estimated_cost_tier": self.estimated_cost_tier,
            "has_vector_store": self.has_vector_store,
            "has_workflow_engine": self.has_workflow_engine,
            "has_usage_tracking": self.has_usage_tracking,
            "cost_observations": self.cost_observations,
        }


@dataclass
class RecommendationEvidence:
    """Structured evidence chain for an advisory recommendation.

    Every recommendation must cite the observations and inferences that
    produced it. Evidence chains make recommendations auditable and explainable.
    """
    observations: list[str]
    inferences: list[str]
    confidence: float
    traceable_sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "inferences": self.inferences,
            "confidence": round(self.confidence, 2),
            "traceable_sources": self.traceable_sources,
        }
