import logging
from typing import Any

from topology.models import Edge, Evidence, Node, NodeType, RelationshipType, TopologyGraph

logger = logging.getLogger(__name__)

LLM_PROVIDER_SDKS = frozenset({
    "openai", "anthropic", "gemini", "google-gemini", "ollama",
    "cohere", "mistral", "groq", "together-ai", "openai-tokenizer",
})

VECTOR_DB_SDKS = frozenset({
    "vector-db-chroma", "vector-db-pinecone", "vector-db-weaviate",
    "vector-db-qdrant", "chromadb", "pinecone", "weaviate", "qdrant", "embeddings",
})

WORKFLOW_ENGINE_SDKS = frozenset({
    "langchain", "litellm", "llama-index", "crewai", "autogen",
    "dspy", "instructor", "vercel-ai", "mcp", "huggingface",
})


class TopologyBuilder:
    """Builds an in-memory operational topology graph from a scan payload.

    Evidence-based. Deterministic. No graph database required.
    Advisory output only — does not modify any systems.
    """

    def build_from_scan(self, scan_payload: dict[str, Any]) -> TopologyGraph:
        graph = TopologyGraph()

        results = scan_payload.get("scanner_results", {}).get("results", {})
        repo_data = results.get("repo_scanner", {})
        service_data = results.get("service_scanner", {})
        llm_detections = scan_payload.get("llm_detections", [])

        if not repo_data or "error" in repo_data:
            logger.warning("No valid repo data in scan payload — returning empty topology graph")
            return graph

        repo_name = repo_data.get("name", "unknown-repo")
        repo_id = f"repo:{repo_name}"

        graph.add_node(Node(
            id=repo_id,
            node_type=NodeType.REPOSITORY,
            label=repo_name,
            metadata={
                "primary_language": repo_data.get("primary_language"),
                "total_files": repo_data.get("total_files"),
                "has_git": repo_data.get("has_git"),
                "git_branch": repo_data.get("git_branch"),
                "target": repo_data.get("target"),
            },
        ))

        # Frameworks → USES_FRAMEWORK edges
        for fw in repo_data.get("frameworks", []):
            fw_id = f"framework:{fw}"
            graph.add_node(Node(id=fw_id, node_type=NodeType.FRAMEWORK, label=fw))
            graph.add_edge(Edge(
                source=repo_id,
                target=fw_id,
                relationship=RelationshipType.USES_FRAMEWORK,
                confidence=0.95,
                evidence=[Evidence("package_manifest", f"{fw} detected in package dependencies")],
            ))

        # Docker → RUNS_IN_DOCKER edge
        docker_info = repo_data.get("docker", {})
        if docker_info.get("present"):
            docker_id = f"docker:{repo_name}"
            indicators = docker_info.get("indicators", [])
            graph.add_node(Node(
                id=docker_id,
                node_type=NodeType.DOCKER,
                label=f"{repo_name}:docker",
                metadata={"indicators": indicators},
            ))
            graph.add_edge(Edge(
                source=repo_id,
                target=docker_id,
                relationship=RelationshipType.RUNS_IN_DOCKER,
                confidence=1.0,
                evidence=[Evidence("filesystem", f"Docker indicators: {', '.join(indicators)}")],
            ))

        # LLM/VectorDB/Workflow SDKs from package manifests (high confidence)
        for sdk in repo_data.get("llm_sdks", []):
            node_type, rel_type, canonical = _classify_sdk(sdk)
            node_id = f"{node_type.value}:{canonical}"
            graph.add_node(Node(id=node_id, node_type=node_type, label=canonical))
            graph.add_edge(Edge(
                source=repo_id,
                target=node_id,
                relationship=rel_type,
                confidence=0.92,
                evidence=[Evidence("package_manifest", f"{sdk} found in dependencies")],
            ))

        # LLM usage detected in source code (medium confidence, deduped)
        for det in llm_detections:
            provider = det["provider"]
            node_type, rel_type, canonical = _classify_sdk(provider)
            node_id = f"{node_type.value}:{canonical}"
            conf = 0.85 if det.get("confidence") == "high" else 0.70

            graph.add_node(Node(id=node_id, node_type=node_type, label=canonical))
            already_connected = any(
                e.source == repo_id and e.target == node_id for e in graph.edges
            )
            if not already_connected:
                graph.add_edge(Edge(
                    source=repo_id,
                    target=node_id,
                    relationship=rel_type,
                    confidence=conf,
                    evidence=[
                        Evidence(ev, "import pattern detected in source")
                        for ev in det.get("evidence", [])[:2]
                    ],
                ))

        # Process managers → USES_PROCESS_MANAGER edges
        for pm in repo_data.get("process_managers", []):
            pm_id = f"process:{pm}"
            graph.add_node(Node(id=pm_id, node_type=NodeType.PROCESS, label=pm))
            graph.add_edge(Edge(
                source=repo_id,
                target=pm_id,
                relationship=RelationshipType.USES_PROCESS_MANAGER,
                confidence=0.90,
                evidence=[Evidence("filesystem", f"{pm} config file detected")],
            ))

        # Listening ports from service scanner → EXPOSES_PORT edges
        for port_info in (service_data or {}).get("listening_ports", []):
            port = port_info.get("port")
            service_hint = port_info.get("service", f"unknown-{port}")
            port_id = f"port:{port}"
            graph.add_node(Node(
                id=port_id,
                node_type=NodeType.PORT,
                label=f":{port} ({service_hint})",
                metadata={"service_hint": service_hint, "process": port_info.get("process")},
            ))
            graph.add_edge(Edge(
                source=repo_id,
                target=port_id,
                relationship=RelationshipType.EXPOSES_PORT,
                confidence=0.90,
                evidence=[Evidence("service_scanner", f"Active listener on port {port}")],
            ))

        logger.info(
            "Topology built",
            extra={
                "repo": repo_name,
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
            },
        )
        return graph


def _classify_sdk(sdk: str) -> tuple[NodeType, RelationshipType, str]:
    """Map an SDK name to (NodeType, RelationshipType, canonical_label)."""
    if sdk in LLM_PROVIDER_SDKS:
        return NodeType.LLM_PROVIDER, RelationshipType.USES_LLM_PROVIDER, sdk
    if sdk in VECTOR_DB_SDKS or "vector-db" in sdk:
        canonical = sdk.replace("vector-db-", "")
        return NodeType.VECTOR_DB, RelationshipType.USES_VECTOR_DB, canonical
    if sdk in WORKFLOW_ENGINE_SDKS:
        return NodeType.WORKFLOW_ENGINE, RelationshipType.USES_WORKFLOW_ENGINE, sdk
    return NodeType.LLM_PROVIDER, RelationshipType.USES_LLM_PROVIDER, sdk
