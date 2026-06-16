
from llm_intelligence.cost_intelligence import LLMCostIntelligence
from reports.recommendation_engine import RecommendationEngine
from topology.builder import TopologyBuilder
from topology.workflow_inference import WorkflowInferenceEngine


def _payload(frameworks=None, llm_sdks=None, env_files=None, has_database=False):
    return {
        "scanner_results": {
            "results": {
                "repo_scanner": {
                    "name": "test-repo",
                    "primary_language": "python",
                    "total_files": 5,
                    "has_git": False,
                    "git_branch": None,
                    "target": "/tmp/test-repo",
                    "frameworks": frameworks or [],
                    "llm_sdks": llm_sdks or [],
                    "docker": {"present": False, "indicators": []},
                    "process_managers": [],
                    "ci_cd": [],
                    "env_files": env_files or [],
                    "capabilities": {"has_database": has_database},
                },
                "service_scanner": {"listening_ports": []},
            }
        },
        "llm_detections": [],
    }


def test_empty_no_recommendations():
    payload = _payload()
    topology = TopologyBuilder().build_from_scan(payload)
    recs = RecommendationEngine().generate(topology, [], [], payload)
    assert recs == []


def test_llm_without_env_file_recommendation():
    payload = _payload(llm_sdks=["openai"])
    topology = TopologyBuilder().build_from_scan(payload)
    workflows = WorkflowInferenceEngine().infer(payload, topology, "/tmp/test-repo")
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)

    titles = [r.title for r in recs]
    assert any("env" in t.lower() or "api key" in t.lower() for t in titles)


def test_recommendation_has_required_fields():
    payload = _payload(llm_sdks=["openai"], frameworks=["fastapi"])
    topology = TopologyBuilder().build_from_scan(payload)
    workflows = WorkflowInferenceEngine().infer(payload, topology, "/tmp/test-repo")
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)

    for rec in recs:
        assert rec.title
        assert rec.observation
        assert isinstance(rec.evidence, list)
        assert 0.0 <= rec.confidence <= 1.0
        assert rec.impact in ("low", "medium", "high")
        assert rec.category in ("cost", "complexity", "topology", "observability")
        assert rec.suggested_investigation


def test_to_dict_serializable():
    payload = _payload(llm_sdks=["openai"], frameworks=["fastapi"])
    topology = TopologyBuilder().build_from_scan(payload)
    workflows = WorkflowInferenceEngine().infer(payload, topology, "/tmp/test-repo")
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)

    for rec in recs:
        d = rec.to_dict()
        assert isinstance(d, dict)
        assert "title" in d
        assert "confidence" in d
        assert "impact" in d


def test_recommendations_sorted_by_confidence():
    payload = _payload(llm_sdks=["openai", "anthropic"], frameworks=["fastapi"])
    topology = TopologyBuilder().build_from_scan(payload)
    workflows = WorkflowInferenceEngine().infer(payload, topology, "/tmp/test-repo")
    cost_obs = LLMCostIntelligence().observe(topology, workflows, payload)
    recs = RecommendationEngine().generate(topology, workflows, cost_obs, payload)

    for i in range(len(recs) - 1):
        assert recs[i].confidence >= recs[i + 1].confidence


def test_observability_recommendation_with_web_api():
    payload = _payload(llm_sdks=["openai"], frameworks=["fastapi"])
    topology = TopologyBuilder().build_from_scan(payload)
    recs = RecommendationEngine().generate(topology, [], [], payload)

    categories = [r.category for r in recs]
    assert "observability" in categories
