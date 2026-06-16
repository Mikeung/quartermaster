"""Tests for cognition/patterns.py — PatternLibrary."""

from __future__ import annotations

from cognition.patterns import OperationalPattern, PatternLibrary


def _payload(packages: list[str] | None = None, workflows: list | None = None,
             llm_providers: list[str] | None = None):
    pkg_list = list(packages or [])
    prov_data = [{"provider": p, "model": "m"} for p in (llm_providers or [])]
    return {
        "workflows": workflows or [],
        "llm_detections": prov_data,
        "scanner_results": {
            "results": {
                "repo_scanner": {"packages": pkg_list},
            }
        },
    }


def _rt(score: float = 0.8, status: str = "healthy", failed_services: list | None = None):
    return {
        "health_score": score,
        "overall_status": status,
        "instability_signals": [],
        "failed_services": failed_services or [],
    }


class TestPatternLibraryBasic:
    def test_match_all_returns_list(self):
        patterns = PatternLibrary().match_all({})
        assert isinstance(patterns, list)
        assert len(patterns) == 9

    def test_all_are_operational_patterns(self):
        patterns = PatternLibrary().match_all({})
        assert all(isinstance(p, OperationalPattern) for p in patterns)

    def test_matched_only_subset(self):
        all_patterns = PatternLibrary().match_all({})
        matched = PatternLibrary().matched_only({})
        assert len(matched) <= len(all_patterns)
        assert all(p.matched for p in matched)

    def test_to_dict_structure(self):
        patterns = PatternLibrary().match_all({})
        d = patterns[0].to_dict()
        assert "name" in d
        assert "matched" in d
        assert "matching_evidence" in d
        assert "severity_hint" in d
        assert "description" in d
        assert "operational_impact" in d
        assert "mitigation_guidance" in d


class TestRetryAmplification:
    def test_matches_with_retry_packages(self):
        payload = _payload(packages=["tenacity"], llm_providers=["openai"])
        patterns = PatternLibrary().match_all(payload)
        retry = next((p for p in patterns if "retry" in p.name), None)
        assert retry is not None
        assert retry.matched is True

    def test_no_match_without_retry(self):
        payload = _payload(packages=["requests"])
        patterns = PatternLibrary().match_all(payload)
        retry = next((p for p in patterns if "retry" in p.name), None)
        assert retry is not None
        assert retry.matched is False


class TestFrameworkStacking:
    def test_matches_multiple_frameworks(self):
        payload = _payload(packages=["langchain", "autogen", "llama-index"])
        patterns = PatternLibrary().match_all(payload)
        stacking = next((p for p in patterns if "stacking" in p.name), None)
        assert stacking is not None
        assert stacking.matched is True

    def test_single_framework_no_match(self):
        payload = _payload(packages=["langchain"])
        patterns = PatternLibrary().match_all(payload)
        stacking = next((p for p in patterns if "stacking" in p.name), None)
        assert stacking is not None
        assert stacking.matched is False


class TestOcrTokenAmplification:
    def test_matches_ocr_plus_llm(self):
        payload = _payload(
            packages=["pytesseract"],
            llm_providers=["openai"]
        )
        patterns = PatternLibrary().match_all(payload)
        ocr = next((p for p in patterns if "ocr" in p.name.lower()), None)
        assert ocr is not None
        assert ocr.matched is True

    def test_ocr_without_llm_no_match(self):
        payload = _payload(packages=["pytesseract"])
        patterns = PatternLibrary().match_all(payload)
        ocr = next((p for p in patterns if "ocr" in p.name.lower()), None)
        assert ocr is not None
        assert ocr.matched is False


class TestSingleProviderDependency:
    def test_matches_single_provider(self):
        wf = [{"name": "rag", "workflow_type": "rag_pipeline"}]
        payload = _payload(llm_providers=["openai"], workflows=wf)
        patterns = PatternLibrary().match_all(payload)
        single = next((p for p in patterns if "single_provider" in p.name), None)
        assert single is not None
        assert single.matched is True

    def test_no_match_multiple_providers(self):
        wf = [{"name": "rag", "workflow_type": "rag_pipeline"}]
        payload = _payload(llm_providers=["openai", "anthropic"], workflows=wf)
        patterns = PatternLibrary().match_all(payload)
        single = next((p for p in patterns if "single_provider" in p.name), None)
        assert single is not None
        assert single.matched is False

    def test_no_match_no_providers(self):
        payload = _payload()
        patterns = PatternLibrary().match_all(payload)
        single = next((p for p in patterns if "single_provider" in p.name), None)
        assert single is not None
        assert single.matched is False


class TestUnstableWorkerPattern:
    def test_matches_with_docker_restarts(self):
        wf = [{"name": "worker", "workflow_type": "async_worker"}]
        payload = _payload(workflows=wf)
        rt = {"health_score": 0.3, "overall_status": "degraded",
              "has_docker_restarts": True, "docker_restart_details": ["container1 restarted 5x"],
              "resource_pressure": [], "failed_services": []}
        patterns = PatternLibrary().match_all(payload, runtime_health=rt)
        worker = next((p for p in patterns if "worker" in p.name), None)
        assert worker is not None
        assert worker.matched is True

    def test_no_match_healthy_runtime(self):
        wf = [{"name": "worker", "workflow_type": "async_worker"}]
        payload = _payload(workflows=wf)
        rt = {"health_score": 0.9, "overall_status": "healthy",
              "has_docker_restarts": False, "resource_pressure": [], "failed_services": []}
        patterns = PatternLibrary().match_all(payload, runtime_health=rt)
        worker = next((p for p in patterns if "worker" in p.name), None)
        assert worker is not None
        assert worker.matched is False


class TestTemporalVolatility:
    def test_volatile_infra_matches_high_volatility(self):
        payload = _payload()
        patterns = PatternLibrary().match_all(payload, temporal_volatility=0.75)
        volatile = next((p for p in patterns if "volatile" in p.name), None)
        assert volatile is not None
        assert volatile.matched is True

    def test_no_match_low_volatility(self):
        payload = _payload()
        patterns = PatternLibrary().match_all(payload, temporal_volatility=0.2)
        volatile = next((p for p in patterns if "volatile" in p.name), None)
        assert volatile is not None
        assert volatile.matched is False


class TestMatchingEvidence:
    def test_matching_evidence_populated_when_matched(self):
        payload = _payload(packages=["tenacity"], llm_providers=["openai"])
        patterns = PatternLibrary().match_all(payload)
        retry = next((p for p in patterns if "retry" in p.name), None)
        assert retry is not None
        assert retry.matched is True
        assert len(retry.matching_evidence) > 0

    def test_matching_evidence_empty_when_not_matched(self):
        payload = _payload(packages=["requests"])
        patterns = PatternLibrary().match_all(payload)
        retry = next((p for p in patterns if "retry" in p.name), None)
        assert retry is not None
        assert retry.matched is False
        assert retry.matching_evidence == []
