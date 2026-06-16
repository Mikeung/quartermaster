"""
Generic HTTP wrapper adapter — build LLM event dicts from arbitrary HTTP
responses to LLM provider APIs.

Useful for:
- Custom provider integrations not covered by SDK adapters
- Proxied or self-hosted LLM endpoints
- Any HTTP call to an LLM API where you control the response parsing

Usage:
    import time, httpx
    from integrations.adapters.http_adapter import adapt_http_response

    t0 = time.monotonic()
    resp = httpx.post("https://api.example.com/v1/chat", json=payload)
    latency_ms = (time.monotonic() - t0) * 1000

    data = resp.json()
    event = adapt_http_response(
        response_json=data,
        workflow="my-workflow",
        provider="my-provider",
        model="my-model",
        latency_ms=latency_ms,
        status_code=resp.status_code,
    )
    mem_client.send_event(event)
"""

from __future__ import annotations

from typing import Any


def adapt_http_response(
    response_json: dict[str, Any],
    *,
    workflow: str,
    provider: str,
    model: str,
    latency_ms: float,
    status_code: int = 200,
    request_kind: str = "completion",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build an event dict from a raw HTTP JSON response.

    Attempts to extract token counts from common response shapes:
    - OpenAI-compatible: response.usage.{prompt_tokens, completion_tokens}
    - Anthropic-compatible: response.usage.{input_tokens, output_tokens}
    - Custom: falls back to 0 if usage is absent

    NEVER reads: choices[*].message.content, content blocks, or any text fields.

    Args:
        response_json: Parsed JSON body of the LLM API response.
        workflow: Logical workflow label.
        provider: Provider name (e.g. "together", "groq", "ollama").
        model: Model name.
        latency_ms: End-to-end latency in milliseconds.
        status_code: HTTP status code.
        request_kind: One of completion/chat/embedding/etc.
        metadata: Optional additional metadata.

    Returns:
        Event dict for OperationalMemoryClient.send_event().
    """
    success = 200 <= status_code < 300
    prompt_tokens, completion_tokens = _extract_tokens(response_json)
    error_type = _classify_http_error(status_code) if not success else None

    # Safe fields from common response shapes
    resolved_model = (
        _safe_get(response_json, "model")
        or model
    )

    extra_meta: dict[str, str] = {"status_code": str(status_code)}
    if metadata:
        extra_meta.update(metadata)

    event: dict[str, Any] = {
        "provider": str(provider)[:64],
        "model": str(resolved_model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": float(latency_ms),
        "success": success,
        "request_kind": request_kind,
        "schema_version": "1.0",
    }
    if error_type:
        event["error_type"] = error_type
    event["metadata"] = _truncate_metadata(extra_meta)
    return event


def adapt_http_error(
    exc: Exception,
    *,
    workflow: str,
    provider: str,
    model: str,
    latency_ms: float = 0.0,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a failed event from an HTTP exception (connection error, timeout, etc.)."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        error_type = "timeout"
    elif "connection" in name:
        error_type = "connection"
    else:
        error_type = "http_error"

    extra_meta: dict[str, str] = {"exception_type": type(exc).__name__}
    if metadata:
        extra_meta.update(metadata)

    return {
        "provider": str(provider)[:64],
        "model": str(model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "latency_ms": float(latency_ms),
        "success": False,
        "request_kind": "completion",
        "error_type": error_type,
        "schema_version": "1.0",
        "metadata": _truncate_metadata(extra_meta),
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _extract_tokens(response_json: dict[str, Any]) -> tuple[int, int]:
    """Extract prompt/completion token counts from common response shapes."""
    usage = _safe_get(response_json, "usage")
    if usage is None:
        return 0, 0

    # OpenAI-compatible
    pt = _safe_get(usage, "prompt_tokens") or _safe_get(usage, "input_tokens") or 0
    ct = _safe_get(usage, "completion_tokens") or _safe_get(usage, "output_tokens") or 0
    return int(pt), int(ct)


def _classify_http_error(status_code: int) -> str:
    if status_code == 401:
        return "authentication"
    if status_code == 403:
        return "permission"
    if status_code == 404:
        return "not_found"
    if status_code == 429:
        return "rate_limit"
    if status_code == 400:
        return "invalid_request"
    if status_code == 413:
        return "context_length"
    if status_code >= 500:
        return "server_error"
    return "http_error"


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        val = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
        return val if val is not None else default
    except Exception:
        return default


def _truncate_metadata(meta: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for k, v in meta.items():
        if len(result) >= 10:
            break
        result[str(k)] = str(v)[:256]
    return result
