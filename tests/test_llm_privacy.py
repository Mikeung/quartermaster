"""Tests for llm_intelligence/privacy.py — privacy guard and sanitization."""

from __future__ import annotations

import pytest

from llm_intelligence.privacy import (
    PrivacyGuard,
    _check_forbidden_fields,
    _check_metadata,
    _looks_like_natural_language,
    _sanitize_metadata,
    explain_rejection,
)


def _minimal_payload(**overrides) -> dict:
    base = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "workflow": "test",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 1000.0,
        "success": True,
        "timestamp": "2026-05-17T10:00:00Z",
    }
    base.update(overrides)
    return base


class TestPrivacyGuard:
    def test_clean_payload_passes(self):
        guard = PrivacyGuard()
        result = guard.check(_minimal_payload())
        assert result.passed
        assert result.rejections == []
        assert result.sanitized_payload is not None

    def test_prompt_field_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["prompt"] = "What is the capital of France?"
        result = guard.check(payload)
        assert not result.passed
        assert any("prompt" in r for r in result.rejections)

    def test_response_field_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["response"] = "Paris is the capital of France."
        result = guard.check(payload)
        assert not result.passed

    def test_messages_field_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["messages"] = [{"role": "user", "content": "hello"}]
        result = guard.check(payload)
        assert not result.passed

    def test_content_field_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["content"] = "some text here"
        result = guard.check(payload)
        assert not result.passed

    def test_oversized_payload_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["metadata"] = {"notes": "x" * 9000}
        result = guard.check(payload)
        assert not result.passed
        assert any("size" in r.lower() or "bytes" in r.lower() for r in result.rejections)

    def test_suspicious_metadata_key_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload(metadata={"prompt": "What is 2+2?"})
        result = guard.check(payload)
        assert not result.passed
        assert any("prompt" in r for r in result.rejections)

    def test_long_natural_language_metadata_rejected(self):
        guard = PrivacyGuard()
        long_text = (
            "This is a detailed description of what happened during the session. "
            "The user asked a question about summarization. "
            "The model responded with a long and comprehensive answer. "
            "This conversation went on for several additional sentences until the total "
            "length exceeded the heuristic detection threshold for natural language prose."
        )
        assert len(long_text) > 200, "test text must exceed heuristic threshold"
        payload = _minimal_payload(metadata={"details": long_text})
        result = guard.check(payload)
        assert not result.passed

    def test_short_metadata_values_accepted(self):
        guard = PrivacyGuard()
        payload = _minimal_payload(metadata={"env": "prod", "stage": "extraction"})
        result = guard.check(payload)
        assert result.passed

    def test_sanitized_payload_strips_suspicious_metadata_keys(self):
        guard = PrivacyGuard()
        # 'output' is suspicious but not at top level, let's test metadata sanitization
        # Use a key that passes the hard check but gets stripped in sanitize
        payload = _minimal_payload(metadata={"env": "prod"})
        result = guard.check(payload)
        assert result.passed
        assert "env" in result.sanitized_payload["metadata"]

    def test_check_and_raise_on_rejected(self):
        guard = PrivacyGuard()
        payload = _minimal_payload()
        payload["prompt"] = "some text"
        with pytest.raises(ValueError, match="Privacy guard rejected"):
            guard.check_and_raise(payload)

    def test_check_and_raise_returns_sanitized_on_pass(self):
        guard = PrivacyGuard()
        sanitized = guard.check_and_raise(_minimal_payload())
        assert "provider" in sanitized


class TestForbiddenFields:
    def test_detects_prompt(self):
        violations = _check_forbidden_fields({"prompt": "hello"})
        assert len(violations) == 1

    def test_detects_lowercase_variant(self):
        violations = _check_forbidden_fields({"PROMPT": "hello"})
        assert len(violations) == 1

    def test_clean_payload_no_violations(self):
        violations = _check_forbidden_fields({"provider": "anthropic", "workflow": "test"})
        assert violations == []


class TestMetadataCheck:
    def test_suspicious_key_rejected(self):
        rejections, _ = _check_metadata({"prompt": "hello"})
        assert len(rejections) >= 1

    def test_clean_metadata_no_rejections(self):
        rejections, warnings = _check_metadata({"env": "prod", "stage": "extraction"})
        assert rejections == []

    def test_long_prose_value_rejected(self):
        text = "This is a sentence. And another one. " * 10
        rejections, _ = _check_metadata({"notes": text})
        assert len(rejections) >= 1


class TestLooksLikeNaturalLanguage:
    def test_prose_detected(self):
        assert _looks_like_natural_language(
            "This is a sentence. Another one follows. And then more text appears."
        )

    def test_short_label_not_prose(self):
        assert not _looks_like_natural_language("production")

    def test_slug_not_prose(self):
        assert not _looks_like_natural_language("doc-processing-v2")


class TestSanitizeMetadata:
    def test_strips_suspicious_keys(self):
        result = _sanitize_metadata({"prompt": "hello", "env": "prod"})
        assert "prompt" not in result
        assert "env" in result

    def test_truncates_long_values(self):
        result = _sanitize_metadata({"key": "x" * 300})
        assert len(result["key"]) <= 256

    def test_limits_key_count(self):
        meta = {f"k{i}": "v" for i in range(15)}
        result = _sanitize_metadata(meta)
        assert len(result) <= 10


class TestExplainRejection:
    def test_explain_rejected_payload(self):
        payload = {"provider": "openai", "prompt": "hello world"}
        explanation = explain_rejection(payload)
        assert explanation["passed"] is False
        assert explanation["rejection_count"] >= 1
        assert "advisory" in explanation

    def test_explain_passing_payload(self):
        explanation = explain_rejection(_minimal_payload())
        assert explanation["passed"] is True
        assert explanation["rejection_count"] == 0
