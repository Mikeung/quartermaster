"""
Integration Profiles — reduce operator guesswork when connecting common stacks.

Each profile documents:
- recommended event fields
- workflow naming conventions
- batching recommendations
- retention recommendations
- ingestion frequency guidance
- example metadata tags

Purpose: give operators a starting point, not a constraint.
Profiles are advisory only — operators may deviate as needed.

Supported stacks:
  fastapi, n8n, langchain, openai_sdk, anthropic_sdk, celery, ocr_pipeline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntegrationProfile:
    """Advisory guidance for integrating a specific stack with operational memory."""

    stack: str
    display_name: str
    description: str

    # Event field guidance
    recommended_workflow_prefix: str
    required_fields: tuple[str, ...] = ("provider", "model", "workflow", "prompt_tokens",
                                         "completion_tokens", "latency_ms", "success")
    recommended_metadata_keys: tuple[str, ...] = ()
    request_kind: str = "completion"

    # Operational guidance
    batching_recommended: bool = False
    suggested_batch_size: int = 1
    suggested_retention_days: int = 30
    suggested_max_events_per_hour: int = 1_000
    send_on_failure: bool = True

    # Workflow naming convention
    workflow_naming_note: str = ""

    # Cautions (human-readable advisory notes)
    cautions: tuple[str, ...] = ()

    # Example event for documentation
    example_event: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stack": self.stack,
            "display_name": self.display_name,
            "description": self.description,
            "recommended_workflow_prefix": self.recommended_workflow_prefix,
            "required_fields": list(self.required_fields),
            "recommended_metadata_keys": list(self.recommended_metadata_keys),
            "request_kind": self.request_kind,
            "batching_recommended": self.batching_recommended,
            "suggested_batch_size": self.suggested_batch_size,
            "suggested_retention_days": self.suggested_retention_days,
            "suggested_max_events_per_hour": self.suggested_max_events_per_hour,
            "send_on_failure": self.send_on_failure,
            "workflow_naming_note": self.workflow_naming_note,
            "cautions": list(self.cautions),
            "example_event": self.example_event,
        }


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

_FASTAPI_PROFILE = IntegrationProfile(
    stack="fastapi",
    display_name="FastAPI",
    description=(
        "FastAPI endpoints that call LLMs as part of request handling. "
        "Events should be sent after the LLM response is received, not before."
    ),
    recommended_workflow_prefix="api",
    recommended_metadata_keys=("endpoint", "http_method", "status_code", "environment"),
    request_kind="chat",
    batching_recommended=False,
    suggested_batch_size=1,
    suggested_retention_days=30,
    suggested_max_events_per_hour=500,
    send_on_failure=True,
    workflow_naming_note=(
        "Use 'api/<endpoint-slug>' format, e.g. 'api/summarize-document'. "
        "Avoid including user IDs or session tokens in workflow names."
    ),
    cautions=(
        "Do not include request path parameters that contain user data in workflow names.",
        "Avoid storing HTTP request bodies in metadata — they likely contain user content.",
        "Latency should cover the full LLM round-trip, not just the FastAPI handler.",
    ),
    example_event={
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "workflow": "api/summarize-document",
        "prompt_tokens": 1200,
        "completion_tokens": 350,
        "latency_ms": 2800.0,
        "success": True,
        "request_kind": "chat",
        "metadata": {"endpoint": "/summarize", "http_method": "POST", "environment": "production"},
    },
)

_N8N_PROFILE = IntegrationProfile(
    stack="n8n",
    display_name="n8n",
    description=(
        "n8n workflow automation nodes that call LLMs via HTTP Request or AI Agent nodes. "
        "Events are best sent from a dedicated 'Send to Operational Memory' HTTP node "
        "placed immediately after the LLM node in the workflow."
    ),
    recommended_workflow_prefix="n8n",
    recommended_metadata_keys=("workflow_name", "node_name", "execution_mode"),
    request_kind="completion",
    batching_recommended=False,
    suggested_batch_size=1,
    suggested_retention_days=14,
    suggested_max_events_per_hour=200,
    send_on_failure=True,
    workflow_naming_note=(
        "Use 'n8n/<workflow-name>/<node-name>' format. "
        "Keep workflow names short and descriptive. "
        "Avoid including data values from trigger nodes."
    ),
    cautions=(
        "n8n workflows often include user-submitted data in node outputs — never forward node data as metadata.",
        "AI Agent nodes may call LLMs multiple times per execution; instrument each call separately.",
        "Error workflows can cause duplicate events if not guarded.",
    ),
    example_event={
        "provider": "openai",
        "model": "gpt-4o-mini",
        "workflow": "n8n/email-triage/classify-email",
        "prompt_tokens": 450,
        "completion_tokens": 80,
        "latency_ms": 1100.0,
        "success": True,
        "metadata": {"workflow_name": "email-triage", "node_name": "classify-email", "execution_mode": "production"},
    },
)

_LANGCHAIN_PROFILE = IntegrationProfile(
    stack="langchain",
    display_name="LangChain",
    description=(
        "LangChain chains and agents that call LLMs through LangChain's model abstractions. "
        "Use the LangChainCallbackAdapter to capture events from LLM callbacks."
    ),
    recommended_workflow_prefix="langchain",
    recommended_metadata_keys=("chain_type", "agent_type", "tool_name", "run_id"),
    request_kind="chat",
    batching_recommended=True,
    suggested_batch_size=10,
    suggested_retention_days=30,
    suggested_max_events_per_hour=1_000,
    send_on_failure=True,
    workflow_naming_note=(
        "Use 'langchain/<chain-or-agent-type>' format, "
        "e.g. 'langchain/rag-qa', 'langchain/react-agent'. "
        "Include the tool name for agent tool calls: 'langchain/react-agent/search-tool'."
    ),
    cautions=(
        "LangChain callbacks expose llm_output which may contain response text — never forward it.",
        "Avoid passing LangChain Document objects or retrieved chunks as metadata.",
        "Agent loops can generate many events per user request; batch them to reduce load.",
        "run_id is safe to include in metadata (it's a UUID, not user data).",
    ),
    example_event={
        "provider": "openai",
        "model": "gpt-4o",
        "workflow": "langchain/rag-qa",
        "prompt_tokens": 2100,
        "completion_tokens": 420,
        "latency_ms": 4200.0,
        "success": True,
        "request_kind": "chat",
        "metadata": {"chain_type": "retrieval_qa", "run_id": "abc-123"},
    },
)

_OPENAI_SDK_PROFILE = IntegrationProfile(
    stack="openai_sdk",
    display_name="OpenAI Python SDK",
    description=(
        "Direct usage of the OpenAI Python SDK (openai.ChatCompletion.create or client.chat.completions.create). "
        "Wrap each call site with the OpenAIAdapter to capture events."
    ),
    recommended_workflow_prefix="openai",
    recommended_metadata_keys=("endpoint_type", "stream", "function_call"),
    request_kind="chat",
    batching_recommended=False,
    suggested_batch_size=1,
    suggested_retention_days=30,
    suggested_max_events_per_hour=500,
    send_on_failure=True,
    workflow_naming_note=(
        "Name workflows after the logical operation, not the API method. "
        "E.g. 'openai/email-draft', not 'openai/chat_completions_create'."
    ),
    cautions=(
        "Never pass the 'messages' list, 'choices', or 'content' fields as metadata.",
        "usage.prompt_tokens and usage.completion_tokens are safe to capture.",
        "Streaming responses require special handling: capture tokens from final chunk only.",
    ),
    example_event={
        "provider": "openai",
        "model": "gpt-4o-mini",
        "workflow": "openai/email-draft",
        "prompt_tokens": 600,
        "completion_tokens": 200,
        "latency_ms": 1800.0,
        "success": True,
        "metadata": {"stream": "false"},
    },
)

_ANTHROPIC_SDK_PROFILE = IntegrationProfile(
    stack="anthropic_sdk",
    display_name="Anthropic Python SDK",
    description=(
        "Direct usage of the Anthropic Python SDK (anthropic.Anthropic().messages.create). "
        "Wrap each call site with the AnthropicAdapter to capture events."
    ),
    recommended_workflow_prefix="anthropic",
    recommended_metadata_keys=("stop_reason", "cache_creation_tokens", "cache_read_tokens"),
    request_kind="chat",
    batching_recommended=False,
    suggested_batch_size=1,
    suggested_retention_days=30,
    suggested_max_events_per_hour=500,
    send_on_failure=True,
    workflow_naming_note=(
        "Name workflows after the feature or agent, not the API method. "
        "E.g. 'anthropic/document-extractor', not 'anthropic/messages_create'."
    ),
    cautions=(
        "Never forward Message.content blocks — they contain response text.",
        "usage.input_tokens and usage.output_tokens are safe to capture.",
        "Cache tokens (cache_creation_input_tokens, cache_read_input_tokens) are safe metadata.",
        "Stop reason (end_turn, max_tokens, stop_sequence) is safe metadata.",
    ),
    example_event={
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "workflow": "anthropic/document-extractor",
        "prompt_tokens": 3200,
        "completion_tokens": 580,
        "latency_ms": 5100.0,
        "success": True,
        "metadata": {"stop_reason": "end_turn", "cache_read_tokens": "1800"},
    },
)

_CELERY_PROFILE = IntegrationProfile(
    stack="celery",
    display_name="Celery Workers",
    description=(
        "Celery background tasks that call LLMs as part of async job processing. "
        "Events should be sent from within the task body, after the LLM call completes."
    ),
    recommended_workflow_prefix="celery",
    recommended_metadata_keys=("task_name", "queue", "retries", "task_id"),
    request_kind="completion",
    batching_recommended=True,
    suggested_batch_size=20,
    suggested_retention_days=14,
    suggested_max_events_per_hour=2_000,
    send_on_failure=True,
    workflow_naming_note=(
        "Use 'celery/<task-module>/<task-name>' format. "
        "E.g. 'celery/tasks.enrichment/enrich-entity'. "
        "task_id is safe metadata (UUID, not user data)."
    ),
    cautions=(
        "High-volume Celery workers can exceed default ingestion limits — set max_events_per_hour appropriately.",
        "Batch events when tasks run in tight loops to reduce HTTP overhead.",
        "Do not include task args or kwargs in metadata — they likely contain application data.",
        "Retry count is safe and useful metadata.",
    ),
    example_event={
        "provider": "openai",
        "model": "gpt-4o-mini",
        "workflow": "celery/tasks.enrichment/enrich-entity",
        "prompt_tokens": 800,
        "completion_tokens": 150,
        "latency_ms": 1600.0,
        "success": True,
        "metadata": {"task_name": "enrich-entity", "queue": "enrichment", "retries": "0"},
    },
)

_OCR_PIPELINE_PROFILE = IntegrationProfile(
    stack="ocr_pipeline",
    display_name="OCR Pipeline",
    description=(
        "OCR pipelines that use LLMs for post-OCR correction, entity extraction, "
        "or document classification. These typically have high token counts and "
        "high per-request costs."
    ),
    recommended_workflow_prefix="ocr",
    recommended_metadata_keys=("document_type", "page_count", "ocr_engine", "extraction_mode"),
    request_kind="completion",
    batching_recommended=True,
    suggested_batch_size=10,
    suggested_retention_days=60,
    suggested_max_events_per_hour=300,
    send_on_failure=True,
    workflow_naming_note=(
        "Use 'ocr/<stage>/<document-type>' format. "
        "E.g. 'ocr/extraction/invoice', 'ocr/correction/medical-record'. "
        "Never include document identifiers or patient IDs in workflow names."
    ),
    cautions=(
        "OCR pipelines often process sensitive documents — never include document content in metadata.",
        "page_count and document_type are safe; document_id, filename, and path are not.",
        "Token counts on OCR correction tasks can be very high — set retention accordingly.",
        "Consider extended retention profile for compliance-sensitive document pipelines.",
    ),
    example_event={
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "workflow": "ocr/extraction/invoice",
        "prompt_tokens": 8500,
        "completion_tokens": 1200,
        "latency_ms": 12000.0,
        "success": True,
        "metadata": {"document_type": "invoice", "page_count": "3", "extraction_mode": "structured"},
    },
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, IntegrationProfile] = {
    "fastapi": _FASTAPI_PROFILE,
    "n8n": _N8N_PROFILE,
    "langchain": _LANGCHAIN_PROFILE,
    "openai_sdk": _OPENAI_SDK_PROFILE,
    "anthropic_sdk": _ANTHROPIC_SDK_PROFILE,
    "celery": _CELERY_PROFILE,
    "ocr_pipeline": _OCR_PIPELINE_PROFILE,
}


def get_profile(stack: str) -> IntegrationProfile | None:
    """Return the integration profile for a given stack name, or None if unknown."""
    return _PROFILES.get(stack.lower())


def list_profiles() -> list[IntegrationProfile]:
    """Return all registered integration profiles."""
    return list(_PROFILES.values())


def profile_names() -> list[str]:
    """Return all known stack names."""
    return list(_PROFILES.keys())
