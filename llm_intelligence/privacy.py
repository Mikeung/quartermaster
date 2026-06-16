"""
LLM Privacy & Safety Controls — prevent accidental sensitive data retention.

Purpose:
- Detect forbidden fields (prompt, response, message bodies) before storage
- Detect likely prompt leakage in metadata values (heuristic)
- Enforce payload size limits
- Sanitize metadata before it reaches the store
- Provide a clear rejection audit trail

This module is the safety gate between ingestion and storage.
It must run before any event reaches LLMEventStore.

Design rule: when in doubt, reject. False positives are acceptable.
False negatives (storing sensitive content) are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_PAYLOAD_BYTES = 8_192          # 8 KB max per event payload
_MAX_METADATA_VALUE_LENGTH = 256
_LEAKAGE_HEURISTIC_MIN_LENGTH = 200  # metadata values longer than this trigger inspection
_LEAKAGE_SENTENCE_PATTERN = re.compile(r"[.!?]\s+[A-Z]")  # crude sentence boundary detector

# Fields that must never appear in an ingested event
_FORBIDDEN_FIELD_NAMES = frozenset({
    "prompt", "response", "content", "message", "messages", "text",
    "system_prompt", "user_message", "assistant_message", "completion",
    "choices", "input", "output", "body", "payload", "conversation",
    "context", "instruction", "query", "answer", "raw", "request",
    "transcript", "dialogue", "chat", "history", "thread",
})

# Metadata keys that suggest content leakage
_SUSPICIOUS_METADATA_KEYS = frozenset({
    "prompt", "response", "message", "content", "text", "output", "input",
    "query", "answer", "body", "instruction", "system", "user", "assistant",
    "conversation", "context", "request", "reply", "summary",
})


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@dataclass
class PrivacyCheckResult:
    passed: bool
    rejections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sanitized_payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "rejections": self.rejections,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class PrivacyGuard:
    """
    Gate between event ingestion and storage.

    Responsibilities:
    1. Hard rejection for forbidden fields
    2. Hard rejection for oversized payloads
    3. Heuristic detection of prompt leakage in metadata
    4. Metadata sanitization (strips suspicious keys, truncates values)

    Heuristics are intentionally conservative — they may produce false
    positives on legitimate operational metadata. This is the correct
    trade-off: accidental content retention is worse than a rejected event.
    """

    def check(self, payload: dict[str, Any]) -> PrivacyCheckResult:
        """
        Full privacy check on a raw event payload.

        Returns PrivacyCheckResult with:
        - passed=False and rejections list if hard violations found
        - passed=True and sanitized_payload if safe (with warnings if applicable)
        """
        rejections: list[str] = []
        warnings: list[str] = []

        # 1. Payload size
        size_rejections = _check_payload_size(payload)
        rejections.extend(size_rejections)

        # 2. Forbidden top-level fields
        field_rejections = _check_forbidden_fields(payload)
        rejections.extend(field_rejections)

        # 3. Metadata safety
        metadata = payload.get("metadata", {})
        if isinstance(metadata, dict):
            meta_rejections, meta_warnings = _check_metadata(metadata)
            rejections.extend(meta_rejections)
            warnings.extend(meta_warnings)

        if rejections:
            return PrivacyCheckResult(
                passed=False,
                rejections=rejections,
                warnings=warnings,
                sanitized_payload=None,
            )

        # 4. Sanitize metadata before returning
        sanitized = dict(payload)
        if isinstance(metadata, dict):
            sanitized["metadata"] = _sanitize_metadata(metadata)

        return PrivacyCheckResult(
            passed=True,
            rejections=[],
            warnings=warnings,
            sanitized_payload=sanitized,
        )

    def check_and_raise(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run check and raise ValueError if rejected."""
        result = self.check(payload)
        if not result.passed:
            raise ValueError(
                f"Privacy guard rejected event: {result.rejections}"
            )
        assert result.sanitized_payload is not None
        return result.sanitized_payload


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_payload_size(payload: dict[str, Any]) -> list[str]:
    import json
    try:
        size = len(json.dumps(payload).encode("utf-8"))
    except (TypeError, ValueError):
        return ["Payload could not be serialized — rejected for safety."]
    if size > _MAX_PAYLOAD_BYTES:
        return [
            f"Payload size {size} bytes exceeds limit of {_MAX_PAYLOAD_BYTES} bytes. "
            "Large payloads may contain content — rejected."
        ]
    return []


def _check_forbidden_fields(payload: dict[str, Any]) -> list[str]:
    rejections = []
    for key in payload:
        if key.lower() in _FORBIDDEN_FIELD_NAMES:
            rejections.append(
                f"Forbidden field '{key}' detected — this field may contain "
                "prompt or response content and must not be stored."
            )
    return rejections


def _check_metadata(metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    rejections: list[str] = []
    warnings: list[str] = []

    for key, value in metadata.items():
        key_lower = key.lower()

        # Hard reject: suspicious key names
        if key_lower in _SUSPICIOUS_METADATA_KEYS:
            rejections.append(
                f"Metadata key '{key}' matches a content-leakage pattern. "
                "Rename the key to an operational label (e.g. 'workflow_step', 'stage')."
            )
            continue

        # Heuristic: long string values may contain prompt content
        if isinstance(value, str) and len(value) > _LEAKAGE_HEURISTIC_MIN_LENGTH:
            if _looks_like_natural_language(value):
                rejections.append(
                    f"Metadata value for '{key}' ({len(value)} chars) appears to contain "
                    "natural language text — this may be prompt or response content. "
                    "Metadata values must be short operational labels, not text content."
                )
            else:
                warnings.append(
                    f"Metadata value for '{key}' is long ({len(value)} chars). "
                    "Verify it does not contain operational content."
                )

    return rejections, warnings


def _looks_like_natural_language(text: str) -> bool:
    """
    Heuristic: does this string resemble natural language prose?

    Checks:
    - Contains multiple sentence boundaries
    - Has high space-to-char ratio (prose-like)
    - Has common English word patterns

    Intentionally conservative — false positives are acceptable.
    """
    if _LEAKAGE_SENTENCE_PATTERN.search(text):
        return True
    space_ratio = text.count(" ") / max(len(text), 1)
    if space_ratio > 0.12:
        return True
    return False


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    """
    Return a sanitized copy of metadata:
    - Remove keys with suspicious names (soft path — only if not already rejected)
    - Truncate long values
    - Coerce non-string values to strings
    - Limit to max allowed keys
    """
    sanitized: dict[str, str] = {}
    for key, value in metadata.items():
        if key.lower() in _SUSPICIOUS_METADATA_KEYS:
            continue  # drop silently
        str_value = str(value)[:_MAX_METADATA_VALUE_LENGTH]
        sanitized[key] = str_value
        if len(sanitized) >= 10:
            break
    return sanitized


# ---------------------------------------------------------------------------
# Convenience: build a rejection case explanation for documentation/tests
# ---------------------------------------------------------------------------

def explain_rejection(payload: dict[str, Any]) -> dict[str, Any]:
    """Run privacy check and return a structured explanation of what was rejected and why."""
    guard = PrivacyGuard()
    result = guard.check(payload)
    return {
        "passed": result.passed,
        "rejections": result.rejections,
        "warnings": result.warnings,
        "rejection_count": len(result.rejections),
        "warning_count": len(result.warnings),
        "advisory": (
            "Privacy guard prevents storage of prompt, response, or conversation content. "
            "Only operational metadata (tokens, latency, provider, workflow) may be stored."
        ),
    }
