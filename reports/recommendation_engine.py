import logging
from typing import TYPE_CHECKING, Any

from memory.finding_store import compute_finding_id, is_suppressed
from topology.models import (
    CostObservation,
    InferredWorkflow,
    NodeType,
    Recommendation,
    TopologyGraph,
)

if TYPE_CHECKING:
    from memory.finding_store import FindingStore

logger = logging.getLogger(__name__)

_IMPACT_TO_SEVERITY = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

# Operator-visible relevance tiers for each finding key.
# "actionable" — requires investigation or a decision by the operator.
# "informational" — useful structural context; operator may choose to act.
_FINDING_KEY_RELEVANCE: dict[str, str] = {
    "rec_no_env_file": "actionable",            # security posture: missing secret isolation
    "rec_batch_llm_no_ratelimit": "actionable",  # causes silent failures under load
    "rec_multi_agent_no_tracing": "informational",
    "rec_rag_chunk_quality": "informational",
    "rec_scheduled_llm_no_idempotency": "informational",
    "rec_cost_risk_high": "informational",
    "rec_cost_pattern_warning": "informational",
    "rec_llm_api_no_telemetry": "informational",
    "rec_no_vector_store": "informational",
    "rec_ollama_cloud_mix": "informational",
}


class RecommendationEngine:
    """Generates advisory recommendations from topology, workflow, and cost intelligence.

    Recommendations are observations only — they suggest investigation, not action.
    All output is advisory. No autonomous changes are made.
    """

    def generate(
        self,
        topology: TopologyGraph,
        workflows: list[InferredWorkflow],
        cost_observations: list[CostObservation],
        scan_payload: dict[str, Any],
        finding_store: "FindingStore | None" = None,
        target_id: str = "",
    ) -> list[Recommendation]:
        candidates: list[Recommendation] = []

        candidates.extend(self._recommend_from_topology(topology, scan_payload))
        candidates.extend(self._recommend_from_workflows(workflows, topology))
        candidates.extend(self._recommend_from_costs(cost_observations, topology))
        candidates.extend(self._recommend_observability(topology, scan_payload))

        # Sort by confidence descending, then impact
        impact_order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(
            key=lambda r: (-r.confidence, impact_order.get(r.impact, 99))
        )

        if finding_store is None or not target_id:
            # No persistence path — return all candidates without suppression
            logger.info(
                "Recommendation engine complete (no persistence)",
                extra={"candidates": len(candidates), "suppressed": 0, "surfaced": len(candidates)},
            )
            return candidates

        # Persist each candidate to FindingStore and collect occurrence counts
        active_ids: set[str] = set()
        for rec in candidates:
            if not rec.finding_key:
                # No stable key — skip persistence for this recommendation
                continue
            fid = compute_finding_id(
                target_id=target_id,
                finding_type=rec.finding_key,
                resource=rec.resource_key,
                scope=rec.category,
                collector_type="recommendation_engine",
            )
            row = finding_store.upsert(
                finding_id=fid,
                target_id=target_id,
                finding_type=rec.finding_key,
                resource=rec.resource_key,
                scope=rec.category,
                severity=_IMPACT_TO_SEVERITY.get(rec.impact, "MEDIUM"),
                collector_type="recommendation_engine",
                title=rec.title,
                description=rec.observation,
                recommendation=rec.suggested_investigation,
                evidence=rec.evidence,
                confidence=rec.confidence,
            )
            rec.recurrence_count = row["occurrence_count"]
            rec.relevance = _FINDING_KEY_RELEVANCE.get(rec.finding_key, "informational")
            rec.first_seen_at = row.get("first_seen", "")
            rec.last_seen_at = row.get("last_seen", "")
            active_ids.add(fid)

        # Mark absent findings as resolved (counter resets on reactivation)
        finding_store.mark_resolved(active_ids, target_id=target_id, collector_type="recommendation_engine")

        suppressed_count = 0
        recommendations: list[Recommendation] = []
        for rec in candidates:
            if rec.finding_key and is_suppressed(
                rec.recurrence_count, rec.first_seen_at, rec.last_seen_at
            ):
                suppressed_count += 1
                logger.debug(
                    "Recommendation suppressed: %s count=%d first_seen=%s",
                    rec.finding_key, rec.recurrence_count, rec.first_seen_at,
                )
            else:
                recommendations.append(rec)

        logger.info(
            "Recommendation engine complete",
            extra={
                "candidates": len(candidates),
                "suppressed": suppressed_count,
                "surfaced": len(recommendations),
                "target": target_id,
            },
        )
        return recommendations

    def _recommend_from_topology(
        self, topology: TopologyGraph, scan_payload: dict[str, Any]
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        llm_providers = [n.label for n in topology.nodes_by_type(NodeType.LLM_PROVIDER)]
        vector_dbs = [n.label for n in topology.nodes_by_type(NodeType.VECTOR_DB)]
        ports = topology.nodes_by_type(NodeType.PORT)

        if not llm_providers:
            return recs

        # LLM + no vector DB → possible missed RAG opportunity
        if llm_providers and not vector_dbs:
            recs.append(Recommendation(
                title="No vector store detected alongside LLM usage",
                observation="LLM providers are in use but no vector database was found. If this system performs document retrieval or semantic search, a vector store may be missing or not yet added.",
                evidence=[f"LLM providers: {', '.join(llm_providers)}", "No vector DB detected in package manifest or active ports"],
                confidence=0.60,
                impact="medium",
                category="topology",
                suggested_investigation="Check if semantic search or document Q&A is planned. If so, consider instrumenting a vector store (Chroma, Qdrant, Pinecone) to improve retrieval accuracy.",
                finding_key="rec_no_vector_store",
                resource_key="",
            ))

        # Ollama on port 11434 alongside cloud providers → potential routing gap
        ollama_port = any(p.metadata.get("service_hint") == "ollama" for p in ports)
        has_cloud_llm = any(p in ("openai", "anthropic", "gemini") for p in llm_providers)
        if ollama_port and has_cloud_llm:
            recs.append(Recommendation(
                title="Ollama running alongside cloud LLM providers",
                observation="Local Ollama instance detected (port 11434) alongside cloud LLM providers. This suggests a hybrid setup — verify routing logic directs appropriate workloads to local vs. cloud inference.",
                evidence=["Port 11434 active (Ollama)", f"Cloud providers: {', '.join(p for p in llm_providers if p in ('openai', 'anthropic', 'gemini'))}"],
                confidence=0.80,
                impact="medium",
                category="cost",
                suggested_investigation="Audit routing logic to confirm which request types go to Ollama vs. cloud APIs. Local inference for non-critical tasks can reduce cloud spend significantly.",
                finding_key="rec_ollama_cloud_mix",
                resource_key="ollama",
            ))

        repo = scan_payload.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
        env_files = repo.get("env_files", [])
        if llm_providers and not env_files:
            recs.append(Recommendation(
                title="No .env file detected — API key configuration unclear",
                observation="LLM providers are in use but no .env or environment configuration file was found. API keys may be hardcoded or missing.",
                evidence=[f"LLM providers: {', '.join(llm_providers)}", "No .env file detected in repository root"],
                confidence=0.72,
                impact="high",
                category="topology",
                suggested_investigation="Verify API keys are stored securely in environment variables, not hardcoded in source. Add a .env.example file documenting required keys.",
                finding_key="rec_no_env_file",
                resource_key=".env",
            ))

        return recs

    def _recommend_from_workflows(
        self, workflows: list[InferredWorkflow], topology: TopologyGraph
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []

        for wf in workflows:
            if wf.workflow_type == "batch_processing":
                recs.append(Recommendation(
                    title=f"Batch LLM workflow ({wf.name}) — add rate limiting and retry logic",
                    observation="Document/OCR batch pipeline detected. Batch LLM workloads frequently hit provider rate limits, causing silent failures or partial outputs.",
                    evidence=wf.evidence,
                    confidence=wf.confidence * 0.9,
                    impact="high",
                    category="complexity",
                    suggested_investigation="Review error handling around LLM API calls in batch pipelines. Ensure exponential backoff with jitter is implemented. Log failed items for reprocessing.",
                    finding_key="rec_batch_llm_no_ratelimit",
                    resource_key=wf.name,
                ))

            if wf.workflow_type == "multi_agent":
                recs.append(Recommendation(
                    title="Multi-agent system detected — instrument inter-agent communication",
                    observation="Multi-agent orchestration framework is in use. Without tracing, debugging agent loops and identifying runaway behavior is very difficult.",
                    evidence=wf.evidence,
                    confidence=wf.confidence * 0.85,
                    impact="high",
                    category="observability",
                    suggested_investigation="Add structured logging to agent handoffs, including task descriptions and token counts. Consider setting maximum iteration limits on agent loops.",
                    finding_key="rec_multi_agent_no_tracing",
                    resource_key=wf.name,
                ))

            if wf.workflow_type == "retrieval_augmented_generation":
                recs.append(Recommendation(
                    title="RAG pipeline — validate retrieval quality and chunk size",
                    observation="Retrieval-Augmented Generation pipeline inferred. RAG quality depends heavily on chunking strategy and embedding model choice.",
                    evidence=wf.evidence,
                    confidence=wf.confidence * 0.85,
                    impact="medium",
                    category="complexity",
                    suggested_investigation="Review chunk sizes (typically 256–1024 tokens), overlap strategy, and embedding model. Add retrieval quality metrics (e.g., hit rate, MRR) if not already present.",
                    finding_key="rec_rag_chunk_quality",
                    resource_key=wf.name,
                ))

            if wf.workflow_type == "scheduled_batch":
                recs.append(Recommendation(
                    title="Scheduled LLM job — ensure idempotency and failure alerting",
                    observation="Periodic LLM job detected. Scheduled jobs that fail silently can result in stale outputs without any visible indication of failure.",
                    evidence=wf.evidence,
                    confidence=wf.confidence * 0.80,
                    impact="medium",
                    category="observability",
                    suggested_investigation="Verify the scheduled job logs success/failure to a persistent store. Add alerting on missed runs. Ensure re-runs produce correct output (idempotent design).",
                    finding_key="rec_scheduled_llm_no_idempotency",
                    resource_key=wf.name,
                ))

        return recs

    def _recommend_from_costs(
        self, cost_observations: list[CostObservation], topology: TopologyGraph
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []

        for obs in cost_observations:
            if obs.severity == "high":
                recs.append(Recommendation(
                    title=f"Cost risk: {obs.observation[:60]}...",
                    observation=obs.observation,
                    evidence=obs.evidence,
                    confidence=0.75,
                    impact="high",
                    category="cost",
                    suggested_investigation="Investigate token volume and cost for this pattern. Add token counting to LLM call wrappers and set budget alerts on provider dashboards.",
                    finding_key="rec_cost_risk_high",
                    resource_key=obs.observation[:60],
                ))
            elif obs.severity == "warning" and obs.estimated_tier == "high":
                recs.append(Recommendation(
                    title=f"Cost pattern: {obs.observation[:60]}...",
                    observation=obs.observation,
                    evidence=obs.evidence,
                    confidence=0.65,
                    impact="medium",
                    category="cost",
                    suggested_investigation="Review LLM call volume and token consumption for this workflow. Consider caching repeated prompts or reducing context window size.",
                    finding_key="rec_cost_pattern_warning",
                    resource_key=obs.observation[:60],
                ))

        return recs

    def _recommend_observability(
        self, topology: TopologyGraph, scan_payload: dict[str, Any]
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []
        llm_providers = [n.label for n in topology.nodes_by_type(NodeType.LLM_PROVIDER)]

        if not llm_providers:
            return recs

        repo = scan_payload.get("scanner_results", {}).get("results", {}).get("repo_scanner", {})
        frameworks = repo.get("frameworks", [])
        has_web = any(f in frameworks for f in ("fastapi", "flask", "django", "express"))

        if has_web and llm_providers:
            recs.append(Recommendation(
                title="LLM API service — add request-level latency and token tracking",
                observation="Web API with LLM backend detected. Without per-request telemetry, latency regressions and cost spikes are invisible.",
                evidence=[
                    f"Web frameworks: {', '.join(f for f in frameworks if f in ('fastapi', 'flask', 'django', 'express'))}",
                    f"LLM providers: {', '.join(llm_providers)}",
                ],
                confidence=0.70,
                impact="medium",
                category="observability",
                suggested_investigation="Add middleware or decorator to log: request ID, LLM provider called, model, token count (prompt + completion), latency, and status. Export to structured logs or metrics.",
                finding_key="rec_llm_api_no_telemetry",
                resource_key="",
            ))

        return recs
