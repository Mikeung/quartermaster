from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    REPOSITORY = "repository"
    SERVICE = "service"
    LLM_PROVIDER = "llm_provider"
    VECTOR_DB = "vector_db"
    FRAMEWORK = "framework"
    DOCKER = "docker"
    PROCESS = "process"
    PORT = "port"
    WORKFLOW_ENGINE = "workflow_engine"


class RelationshipType(str, Enum):
    USES_LLM_PROVIDER = "USES_LLM_PROVIDER"
    USES_FRAMEWORK = "USES_FRAMEWORK"
    USES_VECTOR_DB = "USES_VECTOR_DB"
    USES_WORKFLOW_ENGINE = "USES_WORKFLOW_ENGINE"
    RUNS_IN_DOCKER = "RUNS_IN_DOCKER"
    RUNS_SERVICE = "RUNS_SERVICE"
    EXPOSES_PORT = "EXPOSES_PORT"
    USES_PROCESS_MANAGER = "USES_PROCESS_MANAGER"
    LIKELY_RELATED_TO = "LIKELY_RELATED_TO"
    SHARES_ENV_WITH = "SHARES_ENV_WITH"
    DEPENDS_ON = "DEPENDS_ON"


@dataclass(frozen=True)
class Evidence:
    source: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "detail": self.detail}


@dataclass
class Node:
    id: str
    node_type: NodeType
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type.value,
            "label": self.label,
            "metadata": self.metadata,
        }


@dataclass
class Edge:
    source: str
    target: str
    relationship: RelationshipType
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship.value,
            "confidence": round(self.confidence, 2),
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class TopologyGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        if not any(n.id == node.id for n in self.nodes):
            self.nodes.append(node)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def get_node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def nodes_by_type(self, node_type: NodeType) -> list[Node]:
        return [n for n in self.nodes if n.node_type == node_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


@dataclass
class InferredWorkflow:
    name: str
    description: str
    confidence: float
    evidence: list[str]
    llm_providers: list[str]
    estimated_cost_tier: str  # "low", "medium", "high", "unknown"
    workflow_type: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "llm_providers": self.llm_providers,
            "estimated_cost_tier": self.estimated_cost_tier,
            "workflow_type": self.workflow_type,
        }


@dataclass
class CostObservation:
    observation: str
    evidence: list[str]
    severity: str  # "info", "warning", "high"
    estimated_tier: str  # "low", "medium", "high", "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation,
            "evidence": self.evidence,
            "severity": self.severity,
            "estimated_tier": self.estimated_tier,
        }


@dataclass
class Recommendation:
    title: str
    observation: str
    evidence: list[str]
    confidence: float
    impact: str  # "low", "medium", "high"
    category: str  # "cost", "complexity", "topology", "observability"
    suggested_investigation: str
    urgency: str = "monitor"  # "immediate", "soon", "monitor", "informational"
    recurrence_count: int = 0  # occurrence_count from FindingStore; 0 = unknown
    finding_key: str = ""  # stable type identifier for canonical identity (never changes with wording)
    resource_key: str = ""  # structural resource identifier for canonical identity
    relevance: str = "informational"  # "actionable", "informational", "telemetry_only"
    first_seen_at: str = ""  # ISO timestamp from FindingStore
    last_seen_at: str = ""   # ISO timestamp from FindingStore

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "observation": self.observation,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 2),
            "impact": self.impact,
            "category": self.category,
            "suggested_investigation": self.suggested_investigation,
            "urgency": self.urgency,
            "recurrence_count": self.recurrence_count,
            "relevance": self.relevance,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
        }
