"""
Operational pattern library.

Maintains deterministic operational pattern signatures derived from
infrastructure structure and runtime signals.

Each pattern describes a known operational concern, what evidence is
required to match it, and bounded mitigation guidance.

IMPORTANT:
- Deterministic signature matching only — no ML, no embeddings
- Evidence requirements are explicit structural checks
- Confidence is structural, not probabilistic
- Mitigation guidance is advisory only, never prescriptive
- Correlation is allowed; certainty is NOT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_RETRY_PKGS = frozenset({"tenacity", "backoff", "retry", "retrying"})
_ORCHESTRATION_FRAMEWORKS = frozenset({"langchain", "langgraph", "autogen", "crewai", "haystack", "llamaindex", "llama-index"})
_OCR_PKGS = frozenset({"pytesseract", "tesseract", "easyocr", "paddleocr", "pdfplumber", "pymupdf", "pdfminer"})
_USAGE_TRACKING_PKGS = frozenset({"langfuse", "helicone", "traceloop", "phoenix", "opentelemetry"})
_VECTOR_DB_INDICATORS = frozenset({"chromadb", "pinecone", "weaviate", "qdrant", "milvus", "faiss", "pgvector"})
_HIGH_COST_WORKFLOWS = frozenset({
    "multi_agent_orchestration", "rag_pipeline", "llm_retry_loop",
    "agent_pipeline", "streaming_inference",
})
_MULTI_AGENT_WORKFLOWS = frozenset({"multi_agent_orchestration", "agent_pipeline"})


@dataclass
class OperationalPattern:
    """A matched or unmatched operational pattern signature."""
    name: str
    description: str
    evidence_requirements: list[str]   # what was checked
    operational_impact: str
    mitigation_guidance: str           # advisory only
    confidence_notes: str
    matched: bool
    matching_evidence: list[str]       # what was actually found
    severity_hint: str                 # "low", "moderate", "high"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "evidence_requirements": self.evidence_requirements,
            "operational_impact": self.operational_impact,
            "mitigation_guidance": self.mitigation_guidance,
            "confidence_notes": self.confidence_notes,
            "matched": self.matched,
            "matching_evidence": self.matching_evidence,
            "severity_hint": self.severity_hint,
        }


class PatternLibrary:
    """Match deterministic operational pattern signatures against scan payload.

    Each pattern check is independent. Results include both matched and
    unmatched patterns so operators can see what was looked for.
    """

    def match_all(
        self,
        scan_payload: dict[str, Any],
        runtime_health: dict[str, Any] | None = None,
        temporal_volatility: float | None = None,
    ) -> list[OperationalPattern]:
        """Match all known patterns against the provided scan payload.

        scan_payload: serialized snapshot data dict
        runtime_health: optional serialized RuntimeHealthReport
        temporal_volatility: optional float from TemporalAnalysis
        """
        rt = runtime_health or {}
        checkers = [
            self._retry_amplification,
            self._framework_stacking,
            self._orchestration_sprawl,
            self._unstable_worker_pattern,
            self._volatile_provider_switching,
            self._ocr_token_amplification,
            self._excessive_multi_agent_layering,
            self._cost_blind_rag,
            self._single_provider_dependency,
        ]

        patterns: list[OperationalPattern] = []
        for checker in checkers:
            try:
                pattern = checker(scan_payload, rt, temporal_volatility)
                patterns.append(pattern)
            except Exception as exc:
                logger.warning(
                    "Pattern check failed",
                    extra={"checker": checker.__name__, "error": str(exc)},
                )

        matched = [p for p in patterns if p.matched]
        logger.info(
            "Pattern library scan complete",
            extra={"total_patterns": len(patterns), "matched": len(matched)},
        )
        return patterns

    def matched_only(
        self,
        scan_payload: dict[str, Any],
        runtime_health: dict[str, Any] | None = None,
        temporal_volatility: float | None = None,
    ) -> list[OperationalPattern]:
        return [p for p in self.match_all(scan_payload, runtime_health, temporal_volatility) if p.matched]

    # ------------------------------------------------------------------
    # Pattern signatures
    # ------------------------------------------------------------------

    def _retry_amplification(self, payload, rt, volatility) -> OperationalPattern:
        pkgs = _packages(payload)
        llm_providers = _llm_providers(payload)
        workflows = _workflow_types(payload)

        retry_present = bool(_RETRY_PKGS & pkgs)
        has_llm = bool(llm_providers)
        has_retry_workflow = "llm_retry_loop" in workflows

        matched = retry_present and has_llm
        evidence: list[str] = []
        if retry_present:
            found = list(_RETRY_PKGS & pkgs)
            evidence.append(f"Retry packages: {', '.join(found)}")
        if has_llm:
            evidence.append(f"LLM providers: {', '.join(list(llm_providers)[:3])}")
        if has_retry_workflow:
            evidence.append("Retry workflow pattern inferred")

        return OperationalPattern(
            name="retry_amplification",
            description=(
                "Retry library present alongside LLM provider. "
                "Each retried call re-sends the full prompt, "
                "potentially multiplying token consumption on error bursts."
            ),
            evidence_requirements=[
                "Retry package (tenacity/backoff/retry) in dependencies",
                "LLM provider detected",
            ],
            operational_impact="Token cost amplification on failures; unpredictable cost spikes",
            mitigation_guidance=(
                "Consider exponential backoff with jitter and maximum retry caps. "
                "Add observability on retry counts. Consider prompt truncation on retries."
            ),
            confidence_notes=(
                "Structural match only — retry packages may not be used on LLM calls specifically"
            ),
            matched=matched,
            matching_evidence=evidence,
            severity_hint="high" if has_retry_workflow else "moderate",
        )

    def _framework_stacking(self, payload, rt, volatility) -> OperationalPattern:
        pkgs = _packages(payload)
        found = list(_ORCHESTRATION_FRAMEWORKS & pkgs)
        matched = len(found) >= 3

        evidence: list[str] = []
        if found:
            evidence.append(f"Orchestration frameworks: {', '.join(found)}")
        if len(found) >= 2:
            evidence.append(f"{len(found)} frameworks detected — potential dependency overlap")

        return OperationalPattern(
            name="framework_stacking",
            description=(
                "Three or more LLM orchestration frameworks detected simultaneously. "
                "Each framework adds its own abstraction layer, token overhead, "
                "and dependency surface."
            ),
            evidence_requirements=["3+ orchestration frameworks in dependencies (langchain, autogen, crewai, etc.)"],
            operational_impact=(
                "Increased complexity, conflicting abstractions, "
                "higher dependency surface area, token overhead from multiple contexts"
            ),
            mitigation_guidance=(
                "Evaluate whether all frameworks are actively used. "
                "Consider consolidating to one primary orchestration framework."
            ),
            confidence_notes="Structural match — all detected frameworks may not be used in production code paths",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="moderate",
        )

    def _orchestration_sprawl(self, payload, rt, volatility) -> OperationalPattern:
        llm_providers = _llm_providers(payload)
        workflows = _workflow_types(payload)
        cost_obs = payload.get("cost_observations", [])

        multi_agent = bool(_MULTI_AGENT_WORKFLOWS & workflows)
        multi_provider = len(llm_providers) >= 2
        high_cost = any(o.get("severity") == "high" for o in cost_obs)

        matched = multi_agent and multi_provider and high_cost
        evidence: list[str] = []
        if multi_agent:
            evidence.append(f"Multi-agent workflow: {', '.join(_MULTI_AGENT_WORKFLOWS & workflows)}")
        if multi_provider:
            evidence.append(f"Multiple LLM providers: {', '.join(list(llm_providers)[:4])}")
        if high_cost:
            evidence.append("High-severity cost observation present")

        return OperationalPattern(
            name="orchestration_sprawl",
            description=(
                "Multi-agent orchestration with multiple LLM providers "
                "and confirmed high-cost signals. "
                "Token costs compound at each agent boundary."
            ),
            evidence_requirements=[
                "Multi-agent or agent-pipeline workflow detected",
                "2+ LLM providers",
                "High-severity cost observation",
            ],
            operational_impact="Compounding token costs; unpredictable latency; complex failure modes",
            mitigation_guidance=(
                "Map each agent to its minimum required model. "
                "Route cheaper tasks to smaller/cheaper models. "
                "Add per-agent cost observability."
            ),
            confidence_notes="All three signals must be present — partial matches are not flagged",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="high",
        )

    def _unstable_worker_pattern(self, payload, rt, volatility) -> OperationalPattern:
        workflows = _workflow_types(payload)
        has_async_worker = "async_worker" in workflows
        has_restarts = rt.get("has_docker_restarts", False)
        mem_pressure = any("Memory" in p for p in rt.get("resource_pressure", []))

        matched = has_async_worker and (has_restarts or mem_pressure)
        evidence: list[str] = []
        if has_async_worker:
            evidence.append("Async worker workflow pattern detected")
        if has_restarts:
            evidence.extend(rt.get("docker_restart_details", [])[:2])
        if mem_pressure:
            evidence.append("Memory pressure detected in runtime health")

        return OperationalPattern(
            name="unstable_worker_pattern",
            description=(
                "Async worker workflow combined with container restart instability "
                "or memory pressure. Worker processes may be losing in-flight tasks "
                "or being killed by OOM."
            ),
            evidence_requirements=[
                "Async worker workflow detected",
                "Docker container restarts or memory pressure",
            ],
            operational_impact="Task loss, duplicate processing, unpredictable throughput",
            mitigation_guidance=(
                "Review worker memory limits. "
                "Add dead-letter queues for failed tasks. "
                "Investigate container restart cause before adding replicas."
            ),
            confidence_notes="Requires both structural (workflow) and runtime (health) signals",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="high" if has_restarts and mem_pressure else "moderate",
        )

    def _volatile_provider_switching(self, payload, rt, volatility) -> OperationalPattern:
        matched = volatility is not None and volatility >= 0.50
        evidence: list[str] = []
        if volatility is not None:
            evidence.append(f"Infrastructure volatility score: {volatility:.2f}")
        if matched:
            evidence.append("High volatility may include LLM provider or framework changes")

        return OperationalPattern(
            name="volatile_provider_switching",
            description=(
                "High infrastructure volatility score suggests frequent changes "
                "to LLM providers, frameworks, or workflows. "
                "Frequent switching increases integration risk."
            ),
            evidence_requirements=["Temporal volatility score >= 0.50"],
            operational_impact="Integration instability, prompt compatibility risk, unpredictable cost changes",
            mitigation_guidance=(
                "Stabilize provider selection before optimizing usage. "
                "Review change history to identify root cause of frequent switching."
            ),
            confidence_notes="Volatility score covers all infrastructure changes, not only provider changes",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="moderate",
        )

    def _ocr_token_amplification(self, payload, rt, volatility) -> OperationalPattern:
        pkgs = _packages(payload)
        llm_providers = _llm_providers(payload)
        ocr_found = list(_OCR_PKGS & pkgs)
        matched = bool(ocr_found) and bool(llm_providers)

        evidence: list[str] = []
        if ocr_found:
            evidence.append(f"OCR/PDF packages: {', '.join(ocr_found)}")
        if llm_providers:
            evidence.append(f"LLM provider present: {', '.join(list(llm_providers)[:2])}")

        return OperationalPattern(
            name="ocr_token_amplification",
            description=(
                "OCR or PDF processing library detected alongside LLM provider. "
                "Document pages generate hundreds to thousands of tokens each. "
                "Batch document runs compound cost quickly."
            ),
            evidence_requirements=[
                "OCR/PDF package (pytesseract/pdfplumber/pymupdf/etc.)",
                "LLM provider detected",
            ],
            operational_impact="High and variable token costs per document; cost hard to predict without document count",
            mitigation_guidance=(
                "Track token cost per document. "
                "Consider chunking and summarization before LLM input. "
                "Evaluate self-hosted OCR + smaller LLM for extraction tasks."
            ),
            confidence_notes="Structural match only — OCR and LLM may not be used in the same pipeline path",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="moderate",
        )

    def _excessive_multi_agent_layering(self, payload, rt, volatility) -> OperationalPattern:
        pkgs = _packages(payload)
        workflows = _workflow_types(payload)
        orch_frameworks = list(_ORCHESTRATION_FRAMEWORKS & pkgs)
        has_multi_agent = bool(_MULTI_AGENT_WORKFLOWS & workflows)

        matched = has_multi_agent and len(orch_frameworks) >= 2
        evidence: list[str] = []
        if has_multi_agent:
            evidence.append(f"Multi-agent workflow: {', '.join(_MULTI_AGENT_WORKFLOWS & workflows)}")
        if orch_frameworks:
            evidence.append(f"Orchestration frameworks: {', '.join(orch_frameworks)}")

        return OperationalPattern(
            name="excessive_multi_agent_layering",
            description=(
                "Multi-agent workflow detected with 2+ orchestration frameworks. "
                "Each framework layer adds token overhead, latency, and potential "
                "for conflicting agent coordination logic."
            ),
            evidence_requirements=[
                "Multi-agent workflow inferred",
                "2+ orchestration frameworks",
            ],
            operational_impact=(
                "Token costs multiply per agent turn; latency compounds; "
                "debugging cross-framework agent behavior is complex"
            ),
            mitigation_guidance=(
                "Consolidate to one orchestration framework. "
                "Map agent responsibilities explicitly. "
                "Consider whether all agent layers add value."
            ),
            confidence_notes="Framework presence is structural — not all may be active in agent paths",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="moderate",
        )

    def _cost_blind_rag(self, payload, rt, volatility) -> OperationalPattern:
        pkgs = _packages(payload)
        workflows = _workflow_types(payload)
        has_rag = "rag_pipeline" in workflows
        has_vector = bool(_VECTOR_DB_INDICATORS & pkgs)
        has_tracking = bool(_USAGE_TRACKING_PKGS & pkgs)

        matched = (has_rag or has_vector) and not has_tracking
        evidence: list[str] = []
        if has_rag:
            evidence.append("RAG pipeline workflow detected")
        if has_vector:
            evidence.append(f"Vector DB: {', '.join(_VECTOR_DB_INDICATORS & pkgs)}")
        if not has_tracking:
            evidence.append("No LLM usage tracking package detected (langfuse/helicone/etc.)")

        return OperationalPattern(
            name="cost_blind_rag",
            description=(
                "RAG pipeline or vector database detected without LLM usage tracking. "
                "RAG queries inject retrieval context into every prompt, "
                "making token costs hard to measure without observability tooling."
            ),
            evidence_requirements=[
                "RAG workflow or vector DB package",
                "No usage tracking package (langfuse/helicone/etc.)",
            ],
            operational_impact="Unknown actual token cost per query; cost optimization is difficult without baseline",
            mitigation_guidance=(
                "Add LLM observability tooling (langfuse, helicone, or OpenTelemetry). "
                "Track tokens per retrieval + generation step separately."
            ),
            confidence_notes="Package-based check — tracking may be implemented without the detected packages",
            matched=matched,
            matching_evidence=evidence,
            severity_hint="low",
        )

    def _single_provider_dependency(self, payload, rt, volatility) -> OperationalPattern:
        llm_providers = _llm_providers(payload)
        workflows = _workflow_types(payload)
        has_high_cost_workflow = bool(_HIGH_COST_WORKFLOWS & workflows)

        matched = len(llm_providers) == 1 and has_high_cost_workflow
        evidence: list[str] = []
        if llm_providers:
            evidence.append(f"Single LLM provider: {next(iter(llm_providers))}")
        if has_high_cost_workflow:
            evidence.append(f"High-cost workflow(s): {', '.join(_HIGH_COST_WORKFLOWS & workflows)}")
        if matched:
            evidence.append("No fallback or secondary provider detected")

        return OperationalPattern(
            name="single_provider_dependency",
            description=(
                "Single LLM provider detected with a high-cost workflow. "
                "Provider unavailability or price changes affect the entire system "
                "with no fallback path."
            ),
            evidence_requirements=[
                "Exactly one LLM provider detected",
                "High-cost workflow (multi-agent/RAG/retry/streaming) present",
            ],
            operational_impact="Provider outage = full system unavailability; no cost hedging options",
            mitigation_guidance=(
                "Evaluate a secondary provider for fallback and cost hedging. "
                "Abstract the LLM call layer to make provider switching easier."
            ),
            confidence_notes=(
                "Single-provider detection is structural — multiple providers may be configured "
                "in environment variables without appearing in code"
            ),
            matched=matched,
            matching_evidence=evidence,
            severity_hint="moderate",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _packages(payload: dict[str, Any]) -> frozenset[str]:
    repo = payload.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
    pkgs = repo.get("packages", [])
    return frozenset(p.lower() for p in pkgs if isinstance(p, str))


def _llm_providers(payload: dict[str, Any]) -> frozenset[str]:
    detections = payload.get("llm_detections", [])
    return frozenset(d.get("provider", "") for d in detections if d.get("provider"))


def _workflow_types(payload: dict[str, Any]) -> frozenset[str]:
    workflows = payload.get("workflows", [])
    return frozenset(w.get("workflow_type", "") for w in workflows if w.get("workflow_type"))
