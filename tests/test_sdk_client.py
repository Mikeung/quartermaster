"""Tests for sdk/python/client.py and sdk/python/helpers.py."""

from __future__ import annotations

from sdk.python.client import (
    BatchResult,
    SendResult,
    _check_forbidden_fields,
    _extract_rejection_reason,
)
from sdk.python.helpers import (
    _sanitize_metadata,
    build_batch,
    build_embedding_event,
    build_error_event,
    build_event,
)

# ---------------------------------------------------------------------------
# build_event
# ---------------------------------------------------------------------------

class TestBuildEvent:
    def test_required_fields_present(self):
        event = build_event(
            provider="anthropic",
            model="claude-sonnet-4-6",
            workflow="test-workflow",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=1200.0,
        )
        assert event["provider"] == "anthropic"
        assert event["model"] == "claude-sonnet-4-6"
        assert event["workflow"] == "test-workflow"
        assert event["prompt_tokens"] == 100
        assert event["completion_tokens"] == 50
        assert event["total_tokens"] == 150
        assert event["latency_ms"] == 1200.0
        assert event["success"] is True

    def test_total_tokens_computed(self):
        event = build_event(
            provider="openai", model="gpt-4o-mini", workflow="test",
            prompt_tokens=300, completion_tokens=100, latency_ms=500.0,
        )
        assert event["total_tokens"] == 400

    def test_default_request_kind_completion(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
        )
        assert event["request_kind"] == "completion"

    def test_invalid_request_kind_falls_to_other(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
            request_kind="invalid-kind",
        )
        assert event["request_kind"] == "other"

    def test_estimated_cost_included_when_provided(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
            estimated_cost=0.005,
        )
        assert abs(event["estimated_cost"] - 0.005) < 0.0001

    def test_no_estimated_cost_when_not_provided(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
        )
        assert "estimated_cost" not in event

    def test_metadata_sanitized(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
            metadata={"env": "prod", "version": "1.0"},
        )
        assert event["metadata"]["env"] == "prod"

    def test_schema_version_present(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
        )
        assert event["schema_version"] == "1.0"

    def test_error_type_included_when_provided(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=10, completion_tokens=5, latency_ms=100.0,
            success=False, error_type="rate_limit",
        )
        assert event["error_type"] == "rate_limit"
        assert event["success"] is False

    def test_provider_truncated_at_64(self):
        long_provider = "x" * 100
        event = build_event(
            provider=long_provider, model="m", workflow="w",
            prompt_tokens=1, completion_tokens=1, latency_ms=1.0,
        )
        assert len(event["provider"]) <= 64

    def test_negative_tokens_floored_to_zero(self):
        event = build_event(
            provider="openai", model="gpt-4", workflow="test",
            prompt_tokens=-5, completion_tokens=-3, latency_ms=100.0,
        )
        assert event["prompt_tokens"] == 0
        assert event["completion_tokens"] == 0


class TestBuildErrorEvent:
    def test_success_false(self):
        event = build_error_event(
            provider="openai", model="gpt-4", workflow="test",
            error_type="timeout",
        )
        assert event["success"] is False
        assert event["error_type"] == "timeout"
        assert event["completion_tokens"] == 0

    def test_no_forbidden_fields(self):
        event = build_error_event(
            provider="openai", model="gpt-4", workflow="test",
            error_type="rate_limit",
        )
        forbidden = {"prompt", "response", "content", "messages"}
        assert not any(k in event for k in forbidden)


class TestBuildEmbeddingEvent:
    def test_request_kind_embedding(self):
        event = build_embedding_event(
            provider="openai", model="text-embedding-3-small", workflow="indexer",
            input_tokens=500, latency_ms=200.0,
        )
        assert event["request_kind"] == "embedding"
        assert event["prompt_tokens"] == 500
        assert event["completion_tokens"] == 0


class TestBuildBatch:
    def test_returns_list(self):
        events = [
            build_event(provider="a", model="m", workflow="w", prompt_tokens=1, completion_tokens=1, latency_ms=1.0),
            build_event(provider="b", model="m", workflow="w", prompt_tokens=1, completion_tokens=1, latency_ms=1.0),
        ]
        result = build_batch(events)
        assert len(result) == 2


class TestSanitizeMetadata:
    def test_truncates_long_values(self):
        meta = {"key": "x" * 300}
        result = _sanitize_metadata(meta)
        assert len(result["key"]) == 256

    def test_limits_to_10_keys(self):
        meta = {f"k{i}": "v" for i in range(15)}
        result = _sanitize_metadata(meta)
        assert len(result) == 10


# ---------------------------------------------------------------------------
# Privacy check
# ---------------------------------------------------------------------------

class TestCheckForbiddenFields:
    def test_no_forbidden_returns_none(self):
        event = {"provider": "openai", "model": "gpt-4", "workflow": "test"}
        assert _check_forbidden_fields(event) is None

    def test_prompt_field_rejected(self):
        event = {"provider": "openai", "prompt": "Hello, world"}
        result = _check_forbidden_fields(event)
        assert result is not None
        assert "prompt" in result

    def test_content_field_rejected(self):
        event = {"content": "some text"}
        result = _check_forbidden_fields(event)
        assert result is not None

    def test_forbidden_metadata_key_rejected(self):
        event = {"metadata": {"prompt": "test"}}
        result = _check_forbidden_fields(event)
        assert result is not None
        assert "prompt" in result

    def test_safe_metadata_passes(self):
        event = {"metadata": {"env": "prod", "version": "1"}}
        assert _check_forbidden_fields(event) is None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class TestSendResult:
    def test_to_dict(self):
        r = SendResult(success=True, status_code=200, event_id="abc-123")
        d = r.to_dict()
        assert d["success"] is True
        assert d["event_id"] == "abc-123"

    def test_failed_result(self):
        r = SendResult(success=False, rejection_reason="forbidden_fields: prompt")
        assert r.success is False
        assert "prompt" in r.rejection_reason


class TestBatchResult:
    def test_all_accepted_true_when_all_pass(self):
        r = BatchResult(total=3, accepted=3, rejected=0, errors=0)
        assert r.all_accepted is True

    def test_all_accepted_false_when_some_fail(self):
        r = BatchResult(total=3, accepted=2, rejected=1, errors=0)
        assert r.all_accepted is False

    def test_to_dict(self):
        r = BatchResult(total=5, accepted=4, rejected=1, errors=0)
        d = r.to_dict()
        assert d["total"] == 5
        assert d["all_accepted"] is False


class TestExtractRejectionReason:
    def test_extracts_rejection_reason_field(self):
        data = {"rejection_reason": "forbidden_fields: prompt"}
        assert _extract_rejection_reason(data) == "forbidden_fields: prompt"

    def test_extracts_detail_string(self):
        data = {"detail": "validation error"}
        assert _extract_rejection_reason(data) == "validation error"

    def test_fallback_on_unknown_shape(self):
        assert _extract_rejection_reason({}) == "validation_error"
        assert _extract_rejection_reason("not-a-dict") == "validation_error"
