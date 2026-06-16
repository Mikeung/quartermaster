"""
LLM Event Schema — lightweight, privacy-safe operational event record.

Design rules:
- Never store prompt text, response text, or raw conversation content.
- All fields are operational metadata only (tokens, latency, provider, workflow).
- Bounded metadata dict prevents unbounded payload growth.
- Schema version is embedded for forward-compatibility.

This schema is intentionally minimal. It answers:
  "What happened operationally?" — not "What was said?"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0"

_VALID_REQUEST_KINDS = frozenset({
    "completion",
    "chat",
    "embedding",
    "classification",
    "rerank",
    "transcription",
    "image",
    "moderation",
    "other",
})

_MAX_METADATA_KEYS = 10
_MAX_METADATA_VALUE_LENGTH = 256
_MAX_PROVIDER_LENGTH = 64
_MAX_MODEL_LENGTH = 128
_MAX_WORKFLOW_LENGTH = 128
_MAX_ERROR_TYPE_LENGTH = 128


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class LLMEvent:
    """A single LLM operational event. Contains no prompt or response content."""

    timestamp: str                       # ISO 8601
    provider: str                        # e.g. "anthropic", "openai", "ollama"
    model: str                           # e.g. "claude-sonnet-4-6", "gpt-4o-mini"
    workflow: str                        # caller-defined workflow label
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    success: bool
    request_kind: str = "completion"     # one of _VALID_REQUEST_KINDS
    estimated_cost: float | None = None  # USD, best-effort
    error_type: str | None = None        # e.g. "rate_limit", "timeout", "context_length"
    metadata: dict[str, str] = field(default_factory=dict)  # bounded k/v operational tags
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "provider": self.provider,
            "model": self.model,
            "workflow": self.workflow,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "request_kind": self.request_kind,
            "estimated_cost": self.estimated_cost,
            "error_type": self.error_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMEvent:
        return cls(
            timestamp=str(data.get("timestamp", "")),
            provider=str(data.get("provider", "unknown")),
            model=str(data.get("model", "unknown")),
            workflow=str(data.get("workflow", "unknown")),
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            latency_ms=float(data.get("latency_ms", 0.0)),
            success=bool(data.get("success", True)),
            request_kind=str(data.get("request_kind", "completion")),
            estimated_cost=_parse_optional_float(data.get("estimated_cost")),
            error_type=_parse_optional_str(data.get("error_type")),
            metadata=_coerce_metadata(data.get("metadata", {})),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class EventValidationResult:
    valid: bool
    violations: list[str] = field(default_factory=list)
    normalized_event: LLMEvent | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "violations": self.violations,
            "schema_version": SCHEMA_VERSION,
        }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class LLMEventValidator:
    """
    Validates and normalizes LLM event payloads.

    Rejects events that:
    - contain prompt or response text fields
    - exceed payload size limits
    - have invalid token counts
    - use unknown request kinds
    """

    def validate(self, data: dict[str, Any]) -> EventValidationResult:
        violations: list[str] = []

        violations.extend(_check_forbidden_fields(data))
        violations.extend(_check_required_fields(data))
        violations.extend(_check_token_sanity(data))
        violations.extend(_check_latency_sanity(data))
        violations.extend(_check_request_kind(data))
        violations.extend(_check_field_lengths(data))
        violations.extend(_check_metadata_bounds(data.get("metadata", {})))

        if violations:
            return EventValidationResult(valid=False, violations=violations)

        normalized = _normalize(data)
        return EventValidationResult(valid=True, violations=[], normalized_event=normalized)

    def validate_and_raise(self, data: dict[str, Any]) -> LLMEvent:
        result = self.validate(data)
        if not result.valid:
            raise ValueError(f"LLM event validation failed: {result.violations}")
        assert result.normalized_event is not None
        return result.normalized_event


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_FORBIDDEN_FIELDS = frozenset({
    "prompt", "response", "content", "message", "messages", "text",
    "system_prompt", "user_message", "assistant_message", "completion",
    "choices", "input", "output", "body", "payload", "conversation",
    "context", "instruction", "query", "answer", "raw",
})

_REQUIRED_FIELDS = frozenset({
    "timestamp", "provider", "model", "workflow",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "latency_ms", "success",
})


def _check_forbidden_fields(data: dict[str, Any]) -> list[str]:
    violations = []
    for key in data:
        if key.lower() in _FORBIDDEN_FIELDS:
            violations.append(
                f"Forbidden field '{key}' — prompt/response content must never be stored."
            )
    return violations


def _check_required_fields(data: dict[str, Any]) -> list[str]:
    violations = []
    for field_name in _REQUIRED_FIELDS:
        if field_name not in data:
            violations.append(f"Missing required field: '{field_name}'")
    return violations


def _check_token_sanity(data: dict[str, Any]) -> list[str]:
    violations = []
    for field_name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = data.get(field_name)
        if val is not None:
            try:
                n = int(val)
                if n < 0:
                    violations.append(f"'{field_name}' must be >= 0, got {n}")
                if n > 2_000_000:
                    violations.append(
                        f"'{field_name}' value {n} is implausibly large (> 2M). "
                        "Check for unit errors."
                    )
            except (TypeError, ValueError):
                violations.append(f"'{field_name}' must be an integer, got {type(val).__name__}")
    return violations


def _check_latency_sanity(data: dict[str, Any]) -> list[str]:
    violations = []
    val = data.get("latency_ms")
    if val is not None:
        try:
            ms = float(val)
            if ms < 0:
                violations.append(f"'latency_ms' must be >= 0, got {ms}")
            if ms > 600_000:
                violations.append(
                    f"'latency_ms' value {ms} exceeds 10 minutes — likely a unit error."
                )
        except (TypeError, ValueError):
            violations.append(f"'latency_ms' must be numeric, got {type(val).__name__}")
    return violations


def _check_request_kind(data: dict[str, Any]) -> list[str]:
    kind = str(data.get("request_kind", "completion"))
    if kind not in _VALID_REQUEST_KINDS:
        return [
            f"Invalid request_kind '{kind}'. "
            f"Valid values: {sorted(_VALID_REQUEST_KINDS)}"
        ]
    return []


def _check_field_lengths(data: dict[str, Any]) -> list[str]:
    violations = []
    checks = [
        ("provider", _MAX_PROVIDER_LENGTH),
        ("model", _MAX_MODEL_LENGTH),
        ("workflow", _MAX_WORKFLOW_LENGTH),
        ("error_type", _MAX_ERROR_TYPE_LENGTH),
    ]
    for field_name, max_len in checks:
        val = data.get(field_name)
        if val is not None and len(str(val)) > max_len:
            violations.append(
                f"Field '{field_name}' exceeds max length {max_len} "
                f"(got {len(str(val))} chars)"
            )
    return violations


def _check_metadata_bounds(metadata: Any) -> list[str]:
    if not isinstance(metadata, dict):
        return ["'metadata' must be a dict"]
    violations = []
    if len(metadata) > _MAX_METADATA_KEYS:
        violations.append(
            f"metadata has {len(metadata)} keys — max allowed is {_MAX_METADATA_KEYS}"
        )
    for k, v in metadata.items():
        if not isinstance(k, str):
            violations.append(f"metadata key '{k}' must be a string")
        if not isinstance(v, str):
            violations.append(f"metadata value for '{k}' must be a string")
        elif len(v) > _MAX_METADATA_VALUE_LENGTH:
            violations.append(
                f"metadata value for '{k}' exceeds {_MAX_METADATA_VALUE_LENGTH} chars"
            )
    return violations


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize(data: dict[str, Any]) -> LLMEvent:
    ts = str(data.get("timestamp", ""))
    if not ts:
        ts = datetime.now(UTC).isoformat()

    provider = _sanitize_label(str(data.get("provider", "unknown")))
    model = _sanitize_label(str(data.get("model", "unknown")))
    workflow = _sanitize_label(str(data.get("workflow", "unknown")))

    prompt_tokens = max(0, int(data.get("prompt_tokens", 0)))
    completion_tokens = max(0, int(data.get("completion_tokens", 0)))
    total_tokens = int(data.get("total_tokens", prompt_tokens + completion_tokens))

    # Ensure total_tokens is at least the sum of prompt + completion
    if total_tokens < prompt_tokens + completion_tokens:
        total_tokens = prompt_tokens + completion_tokens

    return LLMEvent(
        timestamp=ts,
        provider=provider,
        model=model,
        workflow=workflow,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=max(0.0, float(data.get("latency_ms", 0.0))),
        success=bool(data.get("success", True)),
        request_kind=str(data.get("request_kind", "completion")),
        estimated_cost=_parse_optional_float(data.get("estimated_cost")),
        error_type=_parse_optional_str(data.get("error_type")),
        metadata=_coerce_metadata(data.get("metadata", {})),
        schema_version=SCHEMA_VERSION,
    )


def _sanitize_label(s: str) -> str:
    """Lowercase, strip whitespace, collapse internal spaces to dashes."""
    s = s.strip().lower()
    s = re.sub(r"\s+", "-", s)
    return s or "unknown"


def _coerce_metadata(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    result = {}
    for k, v in list(raw.items())[:_MAX_METADATA_KEYS]:
        if isinstance(k, str) and isinstance(v, str):
            result[k] = v[:_MAX_METADATA_VALUE_LENGTH]
    return result


def _parse_optional_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_optional_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s[:_MAX_ERROR_TYPE_LENGTH] if s else None
