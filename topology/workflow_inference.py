import logging
import os
from typing import Any

from topology.models import InferredWorkflow, NodeType, TopologyGraph

logger = logging.getLogger(__name__)

_TELEGRAM_PKGS = frozenset({"python-telegram-bot", "telethon", "aiogram", "telebot", "pyrogram"})
_OCR_PKGS = frozenset({"pytesseract", "easyocr", "paddleocr", "tesseract", "pdf2image", "pdfplumber", "pymupdf", "pypdf2", "pdfminer"})
_ASYNC_PKGS = frozenset({"celery", "dramatiq", "rq", "huey", "faststream", "aio-pika", "pika", "kafka-python", "aiokafka"})
_AGENT_PKGS = frozenset({"crewai", "autogen", "pyautogen", "langchain-agents", "agency-swarm"})
_RAG_PKGS = frozenset({"chromadb", "pinecone", "weaviate", "qdrant-client", "faiss-cpu", "faiss-gpu", "sentence-transformers"})


class WorkflowInferenceEngine:
    """Infers high-level AI workflow patterns from topology and scan data.

    Pattern matching is rule-based and deterministic.
    Results are advisory observations, not operational directives.
    """

    def infer(
        self,
        scan_payload: dict[str, Any],
        topology: TopologyGraph,
        target: str,
    ) -> list[InferredWorkflow]:
        all_pkgs = _read_all_packages(target)
        llm_providers = [
            n.label for n in topology.nodes_by_type(NodeType.LLM_PROVIDER)
        ]
        workflow_engines = [
            n.label for n in topology.nodes_by_type(NodeType.WORKFLOW_ENGINE)
        ]
        vector_dbs = [
            n.label for n in topology.nodes_by_type(NodeType.VECTOR_DB)
        ]

        detectors = [
            self._detect_telegram_llm_pipeline,
            self._detect_ocr_summarization,
            self._detect_api_llm_wrapper,
            self._detect_scheduled_llm_job,
            self._detect_multi_provider_orchestration,
            self._detect_rag_pipeline,
            self._detect_multi_agent_system,
            self._detect_async_llm_worker,
        ]

        results: list[InferredWorkflow] = []
        for detector in detectors:
            workflow = detector(scan_payload, all_pkgs, llm_providers, workflow_engines, vector_dbs)
            if workflow is not None:
                results.append(workflow)

        logger.info(
            "Workflow inference complete",
            extra={"inferred_count": len(results), "target": target},
        )
        return results

    def _detect_telegram_llm_pipeline(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        has_telegram = bool(all_pkgs & _TELEGRAM_PKGS)
        has_llm = bool(llm_providers)
        if not (has_telegram and has_llm):
            return None

        evidence = []
        matched_telegram = sorted(all_pkgs & _TELEGRAM_PKGS)
        evidence.append(f"Telegram SDK detected: {', '.join(matched_telegram)}")
        evidence.append(f"LLM providers: {', '.join(llm_providers)}")

        return InferredWorkflow(
            name="TELEGRAM_LLM_PIPELINE",
            description="Telegram bot receiving messages and routing them through an LLM for responses or processing.",
            confidence=0.88,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="medium",
            workflow_type="event_driven",
        )

    def _detect_ocr_summarization(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        has_ocr = bool(all_pkgs & _OCR_PKGS)
        has_llm = bool(llm_providers)
        if not (has_ocr and has_llm):
            return None

        matched_ocr = sorted(all_pkgs & _OCR_PKGS)
        evidence = [
            f"OCR/PDF library detected: {', '.join(matched_ocr)}",
            f"LLM providers: {', '.join(llm_providers)}",
            "Pattern: document ingestion followed by LLM summarization/extraction",
        ]

        return InferredWorkflow(
            name="OCR_SUMMARIZATION_PIPELINE",
            description="Document or image ingestion pipeline that extracts text via OCR/PDF parsing and passes it to an LLM for summarization or structured extraction.",
            confidence=0.85,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="high",
            workflow_type="batch_processing",
        )

    def _detect_api_llm_wrapper(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        repo = scan_payload.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
        frameworks = repo.get("frameworks", [])
        has_web_framework = any(
            fw in frameworks for fw in ("fastapi", "flask", "django", "express", "fastify", "nestjs", "hono")
        )
        has_llm = bool(llm_providers)
        if not (has_web_framework and has_llm):
            return None

        evidence = [
            f"Web framework: {', '.join(f for f in frameworks if f in ('fastapi', 'flask', 'django', 'express', 'fastify', 'nestjs', 'hono'))}",
            f"LLM providers: {', '.join(llm_providers)}",
            "Pattern: HTTP API layer wrapping LLM calls",
        ]

        return InferredWorkflow(
            name="API_LLM_WRAPPER",
            description="HTTP API service that exposes LLM capabilities through REST endpoints, acting as a proxy or enhancement layer over one or more LLM providers.",
            confidence=0.80,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="medium",
            workflow_type="api_service",
        )

    def _detect_scheduled_llm_job(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        repo = scan_payload.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
        process_managers = repo.get("process_managers", [])
        ci_cd = repo.get("ci_cd", [])
        has_scheduler = bool(process_managers or ci_cd)
        has_scheduler = has_scheduler or any(
            p in all_pkgs for p in ("apscheduler", "schedule", "rq", "celery", "cron")
        )
        has_llm = bool(llm_providers)
        if not (has_scheduler and has_llm):
            return None

        scheduler_evidence = []
        if process_managers:
            scheduler_evidence.append(f"Process managers: {', '.join(process_managers)}")
        if ci_cd:
            scheduler_evidence.append(f"CI/CD pipelines: {', '.join(ci_cd)}")
        sched_pkgs = [p for p in ("apscheduler", "schedule", "rq", "celery") if p in all_pkgs]
        if sched_pkgs:
            scheduler_evidence.append(f"Scheduling packages: {', '.join(sched_pkgs)}")

        evidence = scheduler_evidence + [f"LLM providers: {', '.join(llm_providers)}"]

        return InferredWorkflow(
            name="SCHEDULED_LLM_JOB",
            description="Periodic or scheduled job that runs LLM inference on a timer — e.g., nightly summarization, daily digest generation, or recurring data processing.",
            confidence=0.75,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="low",
            workflow_type="scheduled_batch",
        )

    def _detect_multi_provider_orchestration(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        if len(llm_providers) < 2:
            return None

        evidence = [
            f"Multiple LLM providers detected: {', '.join(llm_providers)}",
            "Pattern: multi-provider routing, fallback, or comparison",
        ]
        if workflow_engines:
            evidence.append(f"Workflow engines: {', '.join(workflow_engines)}")

        return InferredWorkflow(
            name="MULTI_PROVIDER_ORCHESTRATION",
            description="System that routes requests across multiple LLM providers — for fallback resilience, cost optimization, capability routing, or A/B comparison.",
            confidence=0.82,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="high",
            workflow_type="orchestration",
        )

    def _detect_rag_pipeline(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        vector_dbs: list[str],
        workflow_engines: list[str],
    ) -> InferredWorkflow | None:
        has_vector_db = bool(vector_dbs) or bool(all_pkgs & _RAG_PKGS)
        has_embeddings = "embeddings" in all_pkgs or "sentence-transformers" in all_pkgs
        has_llm = bool(llm_providers)
        if not (has_vector_db and has_llm):
            return None

        evidence = [f"Vector stores: {', '.join(vector_dbs)}"] if vector_dbs else []
        rag_pkgs = sorted(all_pkgs & _RAG_PKGS)
        if rag_pkgs:
            evidence.append(f"RAG-related packages: {', '.join(rag_pkgs)}")
        if has_embeddings:
            evidence.append("Embedding generation detected")
        evidence.append(f"LLM providers: {', '.join(llm_providers)}")

        return InferredWorkflow(
            name="RAG_PIPELINE",
            description="Retrieval-Augmented Generation pipeline: documents are embedded into a vector store, retrieved by similarity search, and injected into LLM prompts as context.",
            confidence=0.87,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="high",
            workflow_type="retrieval_augmented_generation",
        )

    def _detect_multi_agent_system(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        has_agent_framework = bool(all_pkgs & _AGENT_PKGS)
        agent_engines = [e for e in workflow_engines if e in ("crewai", "autogen", "langchain")]
        if not (has_agent_framework or agent_engines):
            return None

        matched_agent = sorted(all_pkgs & _AGENT_PKGS)
        evidence = []
        if matched_agent:
            evidence.append(f"Agent framework packages: {', '.join(matched_agent)}")
        if agent_engines:
            evidence.append(f"Agent orchestration engines: {', '.join(agent_engines)}")
        evidence.append(f"LLM providers: {', '.join(llm_providers)}")

        return InferredWorkflow(
            name="MULTI_AGENT_SYSTEM",
            description="Multi-agent system where multiple LLM-powered agents collaborate, delegate tasks, and coordinate to complete complex objectives.",
            confidence=0.83,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="high",
            workflow_type="multi_agent",
        )

    def _detect_async_llm_worker(
        self,
        scan_payload: dict[str, Any],
        all_pkgs: set[str],
        llm_providers: list[str],
        workflow_engines: list[str],
        vector_dbs: list[str],
    ) -> InferredWorkflow | None:
        has_async_queue = bool(all_pkgs & _ASYNC_PKGS)
        has_llm = bool(llm_providers)
        if not (has_async_queue and has_llm):
            return None

        matched_async = sorted(all_pkgs & _ASYNC_PKGS)
        evidence = [
            f"Async/queue packages: {', '.join(matched_async)}",
            f"LLM providers: {', '.join(llm_providers)}",
            "Pattern: background worker consuming from queue, calling LLM asynchronously",
        ]

        return InferredWorkflow(
            name="ASYNC_LLM_WORKER",
            description="Asynchronous worker pattern: requests are queued and processed by background workers that make LLM calls, decoupling request ingestion from LLM latency.",
            confidence=0.78,
            evidence=evidence,
            llm_providers=llm_providers,
            estimated_cost_tier="medium",
            workflow_type="async_worker",
        )


def _read_all_packages(target: str) -> set[str]:
    """Return all package names from requirements.txt, pyproject.toml, and package.json."""
    packages: set[str] = set()

    req = os.path.join(target, "requirements.txt")
    if os.path.isfile(req):
        try:
            import re
            for line in open(req):
                line = line.strip()
                if line and not line.startswith("#"):
                    pkg = re.split(r"[>=<!;\[ ]", line)[0].strip().lower()
                    if pkg:
                        packages.add(pkg)
        except OSError:
            pass

    pyproject = os.path.join(target, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            import re
            content = open(pyproject).read()
            for m in re.finditer(r'"([a-zA-Z0-9][a-zA-Z0-9_\-]*)\s*[>=<!,\[]', content):
                packages.add(m.group(1).lower().replace("_", "-"))
        except OSError:
            pass

    pkg_json = os.path.join(target, "package.json")
    if os.path.isfile(pkg_json):
        try:
            import json
            data = json.loads(open(pkg_json).read())
            for section in ("dependencies", "devDependencies", "peerDependencies"):
                if isinstance(data.get(section), dict):
                    packages.update(k.lower() for k in data[section].keys())
        except (OSError, json.JSONDecodeError):
            pass

    return packages
