"""
OpenAI SDK adapter — converts openai.types.chat.ChatCompletion responses into
valid LLM event dicts for operational memory ingestion.

Usage (explicit, no monkey-patching):
    import time
    import openai
    from integrations.adapters.openai_adapter import adapt_openai_response

    client = openai.OpenAI()
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_openai_response(response, workflow="my-workflow", latency_ms=latency_ms)
    mem_client.send_event(event)

IMPORTANT:
- Never accesses response.choices[*].message.content
- Never accesses response.choices[*].message.tool_calls[*].function.arguments
- Only reads usage (token counts), model, finish_reason
"""

from __future__ import annotations

from typing import Any


def adapt_openai_response(
    response: Any,
    *,
    workflow: str,
    latency_ms: float | None = None,
    metadata: dict[str, str] | None = None,
    provider: str = "openai",
) -> dict[str, Any]:
    """
    Convert an openai ChatCompletion (or Completion) response object to an event dict.

    Works with both the new (>=1.0) and legacy (<1.0) openai SDK shapes.

    Args:
        response: The response object returned by client.chat.completions.create().
        workflow: Logical workflow name (e.g. "email-draft").
        latency_ms: End-to-end latency in ms. If None, a zero is recorded.
        metadata: Optional additional operational metadata.
        provider: Override if using an OpenAI-compatible endpoint (e.g. "together").

    Returns:
        Event dict ready for OperationalMemoryClient.send_event().
    """
    model = _safe_get(response, "model", default="unknown")
    usage = _safe_get(response, "usage")
    prompt_tokens = 0
    completion_tokens = 0

    if usage is not None:
        prompt_tokens = int(_safe_get(usage, "prompt_tokens", default=0) or 0)
        completion_tokens = int(_safe_get(usage, "completion_tokens", default=0) or 0)

    # finish_reason from first choice — safe (no content)
    finish_reason = None
    choices = _safe_get(response, "choices")
    if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
        first_choice = choices[0]
        finish_reason = _safe_get(first_choice, "finish_reason")

    extra_meta: dict[str, str] = {}
    if finish_reason:
        extra_meta["finish_reason"] = str(finish_reason)
    if metadata:
        extra_meta.update(metadata)

    event: dict[str, Any] = {
        "provider": provider,
        "model": str(model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": float(latency_ms or 0.0),
        "success": True,
        "request_kind": "chat",
        "schema_version": "1.0",
    }
    if extra_meta:
        event["metadata"] = _truncate_metadata(extra_meta)
    return event


def adapt_openai_error(
    exc: Exception,
    *,
    workflow: str,
    model: str,
    latency_ms: float | None = None,
    metadata: dict[str, str] | None = None,
    provider: str = "openai",
) -> dict[str, Any]:
    """
    Build a failed event from an OpenAI SDK exception.

    Args:
        exc: The exception raised by the OpenAI SDK.
        workflow: Logical workflow name.
        model: Model that was being called.
        latency_ms: Time elapsed before the error, if measurable.
        metadata: Optional additional metadata.
        provider: Override for OpenAI-compatible providers.

    Returns:
        Event dict with success=False and classified error_type.
    """
    error_type = _classify_openai_error(exc)
    extra_meta: dict[str, str] = {}
    if metadata:
        extra_meta.update(metadata)

    return {
        "provider": provider,
        "model": str(model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": float(latency_ms or 0.0),
        "success": False,
        "request_kind": "chat",
        "error_type": error_type,
        "schema_version": "1.0",
        **({"metadata": _truncate_metadata(extra_meta)} if extra_meta else {}),
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    """Attribute or key access with fallback."""
    if obj is None:
        return default
    try:
        return getattr(obj, attr, None) or (obj.get(attr) if hasattr(obj, "get") else None) or default
    except Exception:
        return default


def _classify_openai_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return "rate_limit"
    if "timeout" in name:
        return "timeout"
    if "authen" in name:
        return "authentication"
    if "permission" in name:
        return "permission"
    if "badrequest" in name or "invalid" in name:
        return "invalid_request"
    if "context" in name or "tokenlimit" in name:
        return "context_length"
    if "connection" in name or "network" in name:
        return "connection"
    return "api_error"


def _truncate_metadata(meta: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for k, v in meta.items():
        if len(result) >= 10:
            break
        result[str(k)] = str(v)[:256]
    return result
