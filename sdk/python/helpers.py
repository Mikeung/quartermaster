"""
Typed event builder helpers.

These helpers produce valid LLMEvent-compatible dicts ready for
OperationalMemoryClient.send_event() or send_batch().

They do NOT import the full schema module — the SDK is designed to be
copy-pastable into any project without requiring the operational-memory
package to be installed.

Design rules:
- All fields are keyword-explicit (no positional ambiguity)
- Timestamps default to now (UTC ISO 8601)
- No forbidden fields are ever generated
- Metadata is bounded (max 10 keys, max 256 chars per value)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_MAX_METADATA_KEYS = 10
_MAX_METADATA_VALUE_LENGTH = 256
_VALID_REQUEST_KINDS = frozenset({
    "completion", "chat", "embedding", "classification",
    "rerank", "transcription", "image", "moderation", "other",
})


def build_event(
    *,
    provider: str,
    model: str,
    workflow: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    success: bool = True,
    request_kind: str = "completion",
    estimated_cost: float | None = None,
    error_type: str | None = None,
    metadata: dict[str, str] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """
    Build a valid LLM event dict for ingestion.

    Args:
        provider: LLM provider name (e.g. "anthropic", "openai", "ollama").
        model: Model identifier (e.g. "claude-sonnet-4-6", "gpt-4o-mini").
        workflow: Caller-defined workflow label (e.g. "document-summarizer").
        prompt_tokens: Number of tokens in the prompt/input.
        completion_tokens: Number of tokens in the response/output.
        latency_ms: End-to-end latency in milliseconds.
        success: Whether the request succeeded.
        request_kind: One of completion/chat/embedding/classification/etc.
        estimated_cost: Estimated USD cost, if known.
        error_type: Error category if success=False (e.g. "rate_limit").
        metadata: Optional dict of bounded operational tags.
        timestamp: ISO 8601 timestamp. Defaults to now (UTC).

    Returns:
        Dict suitable for OperationalMemoryClient.send_event().
    """
    if request_kind not in _VALID_REQUEST_KINDS:
        request_kind = "other"

    event: dict[str, Any] = {
        "timestamp": timestamp or _now_iso(),
        "provider": str(provider)[:64],
        "model": str(model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": max(0, int(prompt_tokens)),
        "completion_tokens": max(0, int(completion_tokens)),
        "total_tokens": max(0, int(prompt_tokens)) + max(0, int(completion_tokens)),
        "latency_ms": float(latency_ms),
        "success": bool(success),
        "request_kind": request_kind,
        "schema_version": "1.0",
    }

    if estimated_cost is not None:
        event["estimated_cost"] = float(estimated_cost)

    if error_type is not None:
        event["error_type"] = str(error_type)[:128]

    if metadata:
        event["metadata"] = _sanitize_metadata(metadata)

    return event


def build_batch(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Return a list of events as-is (pass-through for ergonomic use).

    Useful when building a list incrementally and wanting to pass to send_batch()
    with clear intent.
    """
    return list(events)


def build_error_event(
    *,
    provider: str,
    model: str,
    workflow: str,
    error_type: str,
    prompt_tokens: int = 0,
    latency_ms: float = 0.0,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Build a failed event record.

    Convenience wrapper for build_event with success=False
    and required error_type.
    """
    return build_event(
        provider=provider,
        model=model,
        workflow=workflow,
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        latency_ms=latency_ms,
        success=False,
        error_type=error_type,
        metadata=metadata,
    )


def build_embedding_event(
    *,
    provider: str,
    model: str,
    workflow: str,
    input_tokens: int,
    latency_ms: float,
    estimated_cost: float | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an embedding-specific event."""
    return build_event(
        provider=provider,
        model=model,
        workflow=workflow,
        prompt_tokens=input_tokens,
        completion_tokens=0,
        latency_ms=latency_ms,
        request_kind="embedding",
        estimated_cost=estimated_cost,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitize_metadata(raw: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for k, v in raw.items():
        if len(result) >= _MAX_METADATA_KEYS:
            break
        safe_v = str(v)[:_MAX_METADATA_VALUE_LENGTH]
        result[str(k)] = safe_v
    return result
