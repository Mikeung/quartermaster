"""Tests for schemas/llm_event_schema.py — LLM event schema validation and normalization."""

from __future__ import annotations

import pytest

from schemas.llm_event_schema import (
    SCHEMA_VERSION,
    LLMEvent,
    LLMEventValidator,
    _normalize,
    _sanitize_label,
)


def _valid_payload(**overrides) -> dict:
    base = {
        "timestamp": "2026-05-17T10:00:00Z",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "workflow": "document-processing",
        "prompt_tokens": 1200,
        "completion_tokens": 400,
        "total_tokens": 1600,
        "latency_ms": 2400.5,
        "success": True,
        "request_kind": "completion",
    }
    base.update(overrides)
    return base


class TestLLMEventValidator:
    def test_valid_event_passes(self):
        v = LLMEventValidator()
        result = v.validate(_valid_payload())
        assert result.valid
        assert result.violations == []
        assert result.normalized_event is not None

    def test_forbidden_field_prompt_rejected(self):
        v = LLMEventValidator()
        payload = _valid_payload()
        payload["prompt"] = "Summarize this document..."
        result = v.validate(payload)
        assert not result.valid
        assert any("prompt" in viol for viol in result.violations)

    def test_forbidden_field_response_rejected(self):
        v = LLMEventValidator()
        payload = _valid_payload()
        payload["response"] = "Here is a summary..."
        result = v.validate(payload)
        assert not result.valid

    def test_forbidden_field_content_rejected(self):
        v = LLMEventValidator()
        payload = _valid_payload()
        payload["content"] = "some text"
        result = v.validate(payload)
        assert not result.valid

    def test_forbidden_field_messages_rejected(self):
        v = LLMEventValidator()
        payload = _valid_payload()
        payload["messages"] = [{"role": "user", "content": "hello"}]
        result = v.validate(payload)
        assert not result.valid

    def test_missing_required_field(self):
        v = LLMEventValidator()
        payload = _valid_payload()
        del payload["provider"]
        result = v.validate(payload)
        assert not result.valid
        assert any("provider" in viol for viol in result.violations)

    def test_negative_token_count_rejected(self):
        result = LLMEventValidator().validate(_valid_payload(prompt_tokens=-1))
        assert not result.valid

    def test_implausibly_large_tokens_rejected(self):
        result = LLMEventValidator().validate(_valid_payload(total_tokens=3_000_000))
        assert not result.valid

    def test_negative_latency_rejected(self):
        result = LLMEventValidator().validate(_valid_payload(latency_ms=-100))
        assert not result.valid

    def test_invalid_request_kind_rejected(self):
        result = LLMEventValidator().validate(_valid_payload(request_kind="turbo"))
        assert not result.valid

    def test_valid_request_kinds_accepted(self):
        v = LLMEventValidator()
        for kind in ("completion", "chat", "embedding", "classification", "other"):
            result = v.validate(_valid_payload(request_kind=kind))
            assert result.valid, f"Expected {kind} to be valid"

    def test_metadata_too_many_keys_rejected(self):
        meta = {f"k{i}": "v" for i in range(15)}
        result = LLMEventValidator().validate(_valid_payload(metadata=meta))
        assert not result.valid

    def test_metadata_value_too_long_rejected(self):
        meta = {"stage": "x" * 300}
        result = LLMEventValidator().validate(_valid_payload(metadata=meta))
        assert not result.valid

    def test_optional_fields_accepted(self):
        v = LLMEventValidator()
        payload = _valid_payload(
            estimated_cost=0.0048,
            error_type="rate_limit",
            metadata={"environment": "prod", "stage": "extraction"},
        )
        result = v.validate(payload)
        assert result.valid

    def test_validate_and_raise_on_invalid(self):
        v = LLMEventValidator()
        with pytest.raises(ValueError, match="validation failed"):
            v.validate_and_raise(_valid_payload(prompt_tokens=-1))

    def test_validate_and_raise_returns_event_on_valid(self):
        v = LLMEventValidator()
        event = v.validate_and_raise(_valid_payload())
        assert isinstance(event, LLMEvent)
        assert event.provider == "anthropic"

    def test_schema_version_is_embedded(self):
        v = LLMEventValidator()
        result = v.validate(_valid_payload())
        assert result.valid
        assert result.normalized_event.schema_version == SCHEMA_VERSION


class TestNormalization:
    def test_provider_lowercased(self):
        event = _normalize(_valid_payload(provider="Anthropic"))
        assert event.provider == "anthropic"

    def test_provider_spaces_replaced_with_dashes(self):
        event = _normalize(_valid_payload(provider="my provider"))
        assert event.provider == "my-provider"

    def test_total_tokens_computed_if_too_low(self):
        event = _normalize(_valid_payload(prompt_tokens=1000, completion_tokens=500, total_tokens=100))
        assert event.total_tokens == 1500

    def test_negative_tokens_clamped_to_zero(self):
        event = _normalize(_valid_payload(prompt_tokens=0, completion_tokens=0, total_tokens=0))
        assert event.prompt_tokens == 0
        assert event.total_tokens == 0

    def test_schema_version_set(self):
        event = _normalize(_valid_payload())
        assert event.schema_version == SCHEMA_VERSION


class TestSanitizeLabel:
    def test_empty_string_returns_unknown(self):
        assert _sanitize_label("") == "unknown"

    def test_strips_whitespace(self):
        assert _sanitize_label("  openai  ") == "openai"

    def test_lowercases(self):
        assert _sanitize_label("OpenAI") == "openai"

    def test_collapses_spaces(self):
        assert _sanitize_label("my workflow") == "my-workflow"


class TestFromDict:
    def test_roundtrip(self):
        payload = _valid_payload(
            estimated_cost=0.01,
            error_type="timeout",
            metadata={"env": "prod"},
        )
        event = LLMEvent.from_dict(payload)
        d = event.to_dict()
        assert d["provider"] == "anthropic"
        assert d["estimated_cost"] == 0.01
        assert d["error_type"] == "timeout"
        assert d["metadata"]["env"] == "prod"
