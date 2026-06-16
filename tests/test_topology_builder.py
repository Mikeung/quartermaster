
from topology.builder import TopologyBuilder, _classify_sdk
from topology.models import NodeType, RelationshipType


def _make_payload(
    repo_name="test-repo",
    frameworks=None,
    llm_sdks=None,
    docker_present=False,
    process_managers=None,
    llm_detections=None,
    listening_ports=None,
) -> dict:
    return {
        "scanner_results": {
            "results": {
                "repo_scanner": {
                    "name": repo_name,
                    "primary_language": "python",
                    "total_files": 10,
                    "has_git": True,
                    "git_branch": "main",
                    "target": f"/tmp/{repo_name}",
                    "frameworks": frameworks or [],
                    "llm_sdks": llm_sdks or [],
                    "docker": {"present": docker_present, "indicators": ["dockerfile"] if docker_present else []},
                    "process_managers": process_managers or [],
                },
                "service_scanner": {
                    "listening_ports": listening_ports or [],
                },
            }
        },
        "llm_detections": llm_detections or [],
    }


def test_empty_payload_returns_empty_graph():
    graph = TopologyBuilder().build_from_scan({})
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0


def test_repo_node_created():
    payload = _make_payload()
    graph = TopologyBuilder().build_from_scan(payload)
    assert any(n.id == "repo:test-repo" for n in graph.nodes)
    repo_node = graph.get_node("repo:test-repo")
    assert repo_node is not None
    assert repo_node.node_type == NodeType.REPOSITORY


def test_framework_nodes_and_edges():
    payload = _make_payload(frameworks=["fastapi", "react"])
    graph = TopologyBuilder().build_from_scan(payload)

    fw_ids = {n.id for n in graph.nodes if n.node_type == NodeType.FRAMEWORK}
    assert "framework:fastapi" in fw_ids
    assert "framework:react" in fw_ids

    edge_targets = {e.target for e in graph.edges if e.relationship == RelationshipType.USES_FRAMEWORK}
    assert "framework:fastapi" in edge_targets
    assert "framework:react" in edge_targets


def test_docker_node_and_edge():
    payload = _make_payload(docker_present=True)
    graph = TopologyBuilder().build_from_scan(payload)

    docker_node = graph.get_node("docker:test-repo")
    assert docker_node is not None
    assert docker_node.node_type == NodeType.DOCKER

    docker_edge = next(
        (e for e in graph.edges if e.relationship == RelationshipType.RUNS_IN_DOCKER), None
    )
    assert docker_edge is not None
    assert docker_edge.confidence == 1.0


def test_llm_sdk_nodes_from_packages():
    payload = _make_payload(llm_sdks=["openai", "anthropic"])
    graph = TopologyBuilder().build_from_scan(payload)

    llm_nodes = {n.id for n in graph.nodes if n.node_type == NodeType.LLM_PROVIDER}
    assert "llm_provider:openai" in llm_nodes
    assert "llm_provider:anthropic" in llm_nodes


def test_vector_db_classification():
    payload = _make_payload(llm_sdks=["vector-db-chroma"])
    graph = TopologyBuilder().build_from_scan(payload)

    vdb_nodes = [n for n in graph.nodes if n.node_type == NodeType.VECTOR_DB]
    assert len(vdb_nodes) == 1
    assert vdb_nodes[0].label == "chroma"


def test_workflow_engine_classification():
    payload = _make_payload(llm_sdks=["langchain"])
    graph = TopologyBuilder().build_from_scan(payload)

    we_nodes = [n for n in graph.nodes if n.node_type == NodeType.WORKFLOW_ENGINE]
    assert len(we_nodes) == 1
    assert we_nodes[0].label == "langchain"


def test_llm_detection_deduplication():
    payload = _make_payload(
        llm_sdks=["openai"],
        llm_detections=[{"provider": "openai", "confidence": "high", "evidence": ["import openai"]}],
    )
    graph = TopologyBuilder().build_from_scan(payload)

    openai_edges = [
        e for e in graph.edges
        if e.target == "llm_provider:openai" and e.relationship == RelationshipType.USES_LLM_PROVIDER
    ]
    assert len(openai_edges) == 1


def test_llm_detection_new_provider_added():
    payload = _make_payload(
        llm_sdks=["openai"],
        llm_detections=[{"provider": "anthropic", "confidence": "high", "evidence": ["import anthropic"]}],
    )
    graph = TopologyBuilder().build_from_scan(payload)

    llm_nodes = {n.id for n in graph.nodes if n.node_type == NodeType.LLM_PROVIDER}
    assert "llm_provider:openai" in llm_nodes
    assert "llm_provider:anthropic" in llm_nodes


def test_port_nodes_from_service_scanner():
    payload = _make_payload(
        listening_ports=[
            {"port": 8000, "service": "fastapi/uvicorn", "process": "uvicorn"},
            {"port": 11434, "service": "ollama", "process": "ollama"},
        ]
    )
    graph = TopologyBuilder().build_from_scan(payload)

    port_nodes = {n.id for n in graph.nodes if n.node_type == NodeType.PORT}
    assert "port:8000" in port_nodes
    assert "port:11434" in port_nodes


def test_process_manager_nodes():
    payload = _make_payload(process_managers=["pm2", "gunicorn"])
    graph = TopologyBuilder().build_from_scan(payload)

    proc_nodes = {n.id for n in graph.nodes if n.node_type == NodeType.PROCESS}
    assert "process:pm2" in proc_nodes
    assert "process:gunicorn" in proc_nodes


def test_classify_sdk_llm():
    node_type, rel, canonical = _classify_sdk("openai")
    assert node_type == NodeType.LLM_PROVIDER
    assert rel == RelationshipType.USES_LLM_PROVIDER
    assert canonical == "openai"


def test_classify_sdk_vector_db():
    node_type, rel, canonical = _classify_sdk("vector-db-qdrant")
    assert node_type == NodeType.VECTOR_DB
    assert rel == RelationshipType.USES_VECTOR_DB
    assert canonical == "qdrant"


def test_classify_sdk_workflow_engine():
    node_type, rel, canonical = _classify_sdk("langchain")
    assert node_type == NodeType.WORKFLOW_ENGINE
    assert rel == RelationshipType.USES_WORKFLOW_ENGINE


def test_add_node_deduplication():
    from topology.models import Node, TopologyGraph

    graph = TopologyGraph()
    node = Node(id="test:1", node_type=NodeType.REPOSITORY, label="test")
    graph.add_node(node)
    graph.add_node(node)
    assert len(graph.nodes) == 1


def test_to_dict_structure():
    payload = _make_payload(frameworks=["fastapi"], llm_sdks=["openai"])
    graph = TopologyBuilder().build_from_scan(payload)
    d = graph.to_dict()
    assert "node_count" in d
    assert "edge_count" in d
    assert "nodes" in d
    assert "edges" in d
    assert d["node_count"] == len(d["nodes"])
