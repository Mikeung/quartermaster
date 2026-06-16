
from topology.builder import TopologyBuilder
from topology.workflow_inference import WorkflowInferenceEngine


def _minimal_payload(frameworks=None, llm_sdks=None, process_managers=None, ci_cd=None):
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
                    "process_managers": process_managers or [],
                    "ci_cd": ci_cd or [],
                    "capabilities": {"has_database": False},
                },
                "service_scanner": {"listening_ports": []},
            }
        },
        "llm_detections": [],
    }


def _build_graph(payload):
    return TopologyBuilder().build_from_scan(payload)


def test_no_workflows_without_llm():
    payload = _minimal_payload()
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, "/tmp/test-repo")
    assert workflows == []


def test_api_llm_wrapper_detected(tmp_path):
    payload = _minimal_payload(frameworks=["fastapi"], llm_sdks=["openai"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    names = [w.name for w in workflows]
    assert "API_LLM_WRAPPER" in names


def test_multi_provider_detected(tmp_path):
    payload = _minimal_payload(llm_sdks=["openai", "anthropic"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    names = [w.name for w in workflows]
    assert "MULTI_PROVIDER_ORCHESTRATION" in names


def test_single_provider_no_multi_provider(tmp_path):
    payload = _minimal_payload(llm_sdks=["openai"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    names = [w.name for w in workflows]
    assert "MULTI_PROVIDER_ORCHESTRATION" not in names


def test_workflow_has_required_fields(tmp_path):
    payload = _minimal_payload(frameworks=["fastapi"], llm_sdks=["openai"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    assert len(workflows) > 0
    for wf in workflows:
        assert wf.name
        assert wf.description
        assert 0.0 <= wf.confidence <= 1.0
        assert wf.estimated_cost_tier in ("low", "medium", "high", "unknown")
        assert isinstance(wf.evidence, list)
        assert len(wf.evidence) > 0


def test_telegram_llm_pipeline(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("python-telegram-bot>=20.0\nopenai>=1.0\n")
    payload = _minimal_payload(llm_sdks=["openai"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    names = [w.name for w in workflows]
    assert "TELEGRAM_LLM_PIPELINE" in names


def test_scheduled_job_via_process_manager(tmp_path):
    payload = _minimal_payload(llm_sdks=["openai"], process_managers=["pm2"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    names = [w.name for w in workflows]
    assert "SCHEDULED_LLM_JOB" in names


def test_to_dict_serializable(tmp_path):
    payload = _minimal_payload(frameworks=["fastapi"], llm_sdks=["openai", "anthropic"])
    graph = _build_graph(payload)
    workflows = WorkflowInferenceEngine().infer(payload, graph, str(tmp_path))
    for wf in workflows:
        d = wf.to_dict()
        assert isinstance(d, dict)
        assert "name" in d
        assert "confidence" in d
        assert "workflow_type" in d
