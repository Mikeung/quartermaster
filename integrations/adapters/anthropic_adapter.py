"""
Anthropic SDK adapter — converts anthropic.types.Message responses into
valid LLM event dicts for operational memory ingestion.

Usage (explicit, no monkey-patching):
    import time
    import anthropic
    from integrations.adapters.anthropic_adapter import adapt_anthropic_response

    client = anthropic.Anthropic()
    t0 = time.monotonic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}],
    )
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_anthropic_response(message, workflow="my-workflow", latency_ms=latency_ms)
    mem_client.send_event(event)

IMPORTANT:
- Never accesses message.content blocks (these contain response text)
- Never accesses message.content[*].text
- Only reads usage (token counts), model, stop_reason, stop_sequence
"""

from __future__ import annotations

from typing import Any


def adapt_anthropic_response(
    message: Any,
    *,
    workflow: str,
    latency_ms: float | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Convert an Anthropic Message response to an event dict.

    Args:
        message: The Message object returned by client.messages.create().
        workflow: Logical workflow name (e.g. "document-extractor").
        latency_ms: End-to-end latency in ms. If None, zero is recorded.
        metadata: Optional additional operational metadata.

    Returns:
        Event dict ready for OperationalMemoryClient.send_event().
    """
    model = _safe_get(message, "model", default="unknown")
    usage = _safe_get(message, "usage")
    stop_reason = _safe_get(message, "stop_reason")

    prompt_tokens = 0
    completion_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0

    if usage is not None:
        prompt_tokens = int(_safe_get(usage, "input_tokens", default=0) or 0)
        completion_tokens = int(_safe_get(usage, "output_tokens", default=0) or 0)
        # Cache tokens (Anthropic prompt caching feature)
        cache_creation_tokens = int(
            _safe_get(usage, "cache_creation_input_tokens", default=0) or 0
        )
        cache_read_tokens = int(
            _safe_get(usage, "cache_read_input_tokens", default=0) or 0
        )

    extra_meta: dict[str, str] = {}
    if stop_reason:
        extra_meta["stop_reason"] = str(stop_reason)
    if cache_creation_tokens:
        extra_meta["cache_creation_tokens"] = str(cache_creation_tokens)
    if cache_read_tokens:
        extra_meta["cache_read_tokens"] = str(cache_read_tokens)
    if metadata:
        extra_meta.update(metadata)

    event: dict[str, Any] = {
        "provider": "anthropic",
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


def adapt_anthropic_error(
    exc: Exception,
    *,
    workflow: str,
    model: str,
    latency_ms: float | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build a failed event from an Anthropic SDK exception.

    Args:
        exc: The exception raised by the Anthropic SDK.
        workflow: Logical workflow name.
        model: Model that was being called.
        latency_ms: Time elapsed before the error, if measurable.
        metadata: Optional additional metadata.

    Returns:
        Event dict with success=False and classified error_type.
    """
    error_type = _classify_anthropic_error(exc)
    extra_meta: dict[str, str] = {}
    if metadata:
        extra_meta.update(metadata)

    return {
        "provider": "anthropic",
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
    if obj is None:
        return default
    try:
        val = getattr(obj, attr, None)
        if val is None and hasattr(obj, "get"):
            val = obj.get(attr)
        return val if val is not None else default
    except Exception:
        return default


def _classify_anthropic_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate_limit" in msg or "529" in msg:
        return "rate_limit"
    if "overloaded" in msg:
        return "overloaded"
    if "timeout" in name or "timeout" in msg:
        return "timeout"
    if "authen" in name or "401" in msg:
        return "authentication"
    if "permission" in name or "403" in msg:
        return "permission"
    if "badrequest" in name or "invalid" in msg or "400" in msg:
        return "invalid_request"
    if "context" in msg or "too long" in msg:
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
