"""
Event adapters — thin, explicit wrappers around common AI SDK response objects.

Each adapter converts a provider SDK response into a valid LLM event dict.
None of these adapters patch globals, modify SDK internals, or auto-instrument.
All usage is explicit: call the adapter function after your own API call.
"""
from integrations.adapters.anthropic_adapter import adapt_anthropic_response
from integrations.adapters.celery_adapter import CeleryTaskEventHelper
from integrations.adapters.http_adapter import adapt_http_response
from integrations.adapters.langchain_adapter import LangChainCallbackAdapter
from integrations.adapters.openai_adapter import adapt_openai_response

__all__ = [
    "CeleryTaskEventHelper",
    "LangChainCallbackAdapter",
    "adapt_anthropic_response",
    "adapt_http_response",
    "adapt_openai_response",
]
