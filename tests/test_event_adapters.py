"""Tests for integrations/adapters/ — event adapter modules."""

from __future__ import annotations

from integrations.adapters.anthropic_adapter import (
    adapt_anthropic_error,
    adapt_anthropic_response,
)
from integrations.adapters.celery_adapter import CeleryTaskEventHelper
from integrations.adapters.http_adapter import (
    _classify_http_error,
    _extract_tokens,
    adapt_http_error,
    adapt_http_response,
)
from integrations.adapters.langchain_adapter import (
    LangChainCallbackAdapter,
    _classify_langchain_error,
    _extract_langchain_tokens,
)
from integrations.adapters.openai_adapter import (
    _classify_openai_error,
    adapt_openai_error,
    adapt_openai_response,
)

# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

class _MockUsage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion

class _MockChoice:
    def __init__(self, finish_reason="stop"):
        self.finish_reason = finish_reason

class _MockOpenAIResponse:
    def __init__(self, model="gpt-4o-mini", pt=100, ct=50, finish_reason="stop"):
        self.model = model
        self.usage = _MockUsage(pt, ct)
        self.choices = [_MockChoice(finish_reason)]


class TestOpenAIAdapter:
    def test_builds_valid_event(self):
        resp = _MockOpenAIResponse()
        event = adapt_openai_response(resp, workflow="test-wf", latency_ms=800.0)
        assert event["provider"] == "openai"
        assert event["model"] == "gpt-4o-mini"
        assert event["workflow"] == "test-wf"
        assert event["prompt_tokens"] == 100
        assert event["completion_tokens"] == 50
        assert event["total_tokens"] == 150
        assert event["success"] is True
        assert abs(event["latency_ms"] - 800.0) < 0.01

    def test_never_reads_content(self):
        resp = _MockOpenAIResponse()
        resp.choices[0].message = type("M", (), {"content": "SECRET TEXT"})()
        event = adapt_openai_response(resp, workflow="test", latency_ms=100.0)
        # Verify no content in event
        forbidden = {"prompt", "response", "content", "message", "messages", "text"}
        assert not any(k in event for k in forbidden)

    def test_finish_reason_in_metadata(self):
        resp = _MockOpenAIResponse(finish_reason="stop")
        event = adapt_openai_response(resp, workflow="test", latency_ms=100.0)
        assert event.get("metadata", {}).get("finish_reason") == "stop"

    def test_custom_provider_override(self):
        resp = _MockOpenAIResponse()
        event = adapt_openai_response(resp, workflow="test", latency_ms=100.0, provider="together")
        assert event["provider"] == "together"

    def test_error_event_success_false(self):
        class RateLimitError(Exception):
            pass
        exc = RateLimitError("rate limit exceeded")
        event = adapt_openai_error(exc, workflow="test", model="gpt-4o", latency_ms=200.0)
        assert event["success"] is False
        assert event["error_type"] == "rate_limit"

    def test_classify_rate_limit(self):
        class RateLimitError(Exception):
            pass
        assert _classify_openai_error(RateLimitError()) == "rate_limit"

    def test_classify_timeout(self):
        class TimeoutError(Exception):
            pass
        assert _classify_openai_error(TimeoutError()) == "timeout"

    def test_classify_generic_returns_api_error(self):
        assert _classify_openai_error(ValueError("generic")) == "api_error"


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------

class _MockAnthropicUsage:
    def __init__(self, input_tokens, output_tokens, cache_creation=0, cache_read=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation
        self.cache_read_input_tokens = cache_read

class _MockAnthropicMessage:
    def __init__(self, model="claude-haiku-4-5-20251001", in_t=200, out_t=80, stop="end_turn"):
        self.model = model
        self.usage = _MockAnthropicUsage(in_t, out_t)
        self.stop_reason = stop
        # Intentionally no .content attribute to verify it's never read


class TestAnthropicAdapter:
    def test_builds_valid_event(self):
        msg = _MockAnthropicMessage()
        event = adapt_anthropic_response(msg, workflow="extractor", latency_ms=2000.0)
        assert event["provider"] == "anthropic"
        assert event["model"] == "claude-haiku-4-5-20251001"
        assert event["prompt_tokens"] == 200
        assert event["completion_tokens"] == 80
        assert event["total_tokens"] == 280
        assert event["success"] is True

    def test_stop_reason_in_metadata(self):
        msg = _MockAnthropicMessage(stop="max_tokens")
        event = adapt_anthropic_response(msg, workflow="test", latency_ms=500.0)
        assert event.get("metadata", {}).get("stop_reason") == "max_tokens"

    def test_cache_tokens_in_metadata(self):
        msg = _MockAnthropicMessage()
        msg.usage = _MockAnthropicUsage(200, 80, cache_creation=500, cache_read=1000)
        event = adapt_anthropic_response(msg, workflow="test", latency_ms=500.0)
        meta = event.get("metadata", {})
        assert meta.get("cache_creation_tokens") == "500"
        assert meta.get("cache_read_tokens") == "1000"

    def test_never_reads_content_blocks(self):
        msg = _MockAnthropicMessage()
        msg.content = [type("Block", (), {"text": "SECRET RESPONSE TEXT"})()]
        event = adapt_anthropic_response(msg, workflow="test", latency_ms=500.0)
        forbidden = {"prompt", "response", "content", "text", "messages"}
        assert not any(k in event for k in forbidden)

    def test_error_event_success_false(self):
        exc = Exception("service overloaded")
        event = adapt_anthropic_error(exc, workflow="test", model="claude-haiku-4-5-20251001")
        assert event["success"] is False
        assert event["error_type"] == "overloaded"


# ---------------------------------------------------------------------------
# HTTP adapter
# ---------------------------------------------------------------------------

class TestHttpAdapter:
    def test_openai_compatible_tokens(self):
        data = {"model": "gpt-4", "usage": {"prompt_tokens": 500, "completion_tokens": 200}}
        pt, ct = _extract_tokens(data)
        assert pt == 500
        assert ct == 200

    def test_anthropic_compatible_tokens(self):
        data = {"model": "claude-3", "usage": {"input_tokens": 300, "output_tokens": 100}}
        pt, ct = _extract_tokens(data)
        assert pt == 300
        assert ct == 100

    def test_no_usage_returns_zeros(self):
        pt, ct = _extract_tokens({})
        assert pt == 0
        assert ct == 0

    def test_success_on_200(self):
        event = adapt_http_response(
            {"usage": {"prompt_tokens": 100, "completion_tokens": 50}},
            workflow="test", provider="custom", model="my-model",
            latency_ms=400.0, status_code=200,
        )
        assert event["success"] is True

    def test_failure_on_429(self):
        event = adapt_http_response(
            {}, workflow="test", provider="custom", model="my-model",
            latency_ms=100.0, status_code=429,
        )
        assert event["success"] is False
        assert event["error_type"] == "rate_limit"

    def test_classify_http_errors(self):
        assert _classify_http_error(401) == "authentication"
        assert _classify_http_error(403) == "permission"
        assert _classify_http_error(429) == "rate_limit"
        assert _classify_http_error(500) == "server_error"

    def test_error_event_from_exception(self):
        exc = TimeoutError("timed out")
        event = adapt_http_error(exc, workflow="test", provider="custom", model="my-model")
        assert event["success"] is False
        assert event["error_type"] == "timeout"


# ---------------------------------------------------------------------------
# Celery adapter
# ---------------------------------------------------------------------------

class TestCeleryTaskEventHelper:
    def test_success_event(self):
        helper = CeleryTaskEventHelper(
            task_name="tasks.process", workflow="celery/tasks/process", queue="default"
        )
        event = helper.success_event(
            provider="openai", model="gpt-4o-mini",
            prompt_tokens=400, completion_tokens=100, latency_ms=1500.0,
        )
        assert event["success"] is True
        assert event["provider"] == "openai"
        assert event["metadata"]["task_name"] == "tasks.process"
        assert event["metadata"]["queue"] == "default"

    def test_error_event(self):
        helper = CeleryTaskEventHelper(
            task_name="tasks.process", workflow="celery/tasks/process"
        )
        exc = Exception("rate limit exceeded")
        event = helper.error_event(
            provider="openai", model="gpt-4o-mini", exc=exc, retry_count=2
        )
        assert event["success"] is False
        assert event["metadata"]["retries"] == "2"

    def test_retry_count_in_metadata(self):
        helper = CeleryTaskEventHelper("t", "w")
        event = helper.success_event(
            provider="a", model="m", prompt_tokens=1,
            completion_tokens=1, latency_ms=1.0, retry_count=3,
        )
        assert event["metadata"]["retries"] == "3"

    def test_no_forbidden_fields(self):
        helper = CeleryTaskEventHelper("t", "w")
        event = helper.success_event(provider="a", model="m", prompt_tokens=1, completion_tokens=1, latency_ms=1.0)
        forbidden = {"prompt", "response", "content", "messages"}
        assert not any(k in event for k in forbidden)


# ---------------------------------------------------------------------------
# LangChain callback adapter
# ---------------------------------------------------------------------------

class _MockMemClient:
    def __init__(self):
        self.sent: list[dict] = []
        self.batches: list[list[dict]] = []

    def send_event(self, event):
        self.sent.append(event)

    def send_batch(self, events):
        self.batches.append(events)
        self.sent.extend(events)


class _MockLLMResult:
    def __init__(self, pt=100, ct=50):
        self.llm_output = {"token_usage": {"prompt_tokens": pt, "completion_tokens": ct}}
        self.generations = []


class TestLangChainCallbackAdapter:
    def test_on_llm_end_sends_event(self):
        client = _MockMemClient()
        adapter = LangChainCallbackAdapter(
            mem_client=client, workflow="lc/test", provider="openai", model="gpt-4o-mini"
        )
        adapter.on_llm_start({}, [])
        adapter.on_llm_end(_MockLLMResult())
        assert len(client.sent) == 1
        event = client.sent[0]
        assert event["success"] is True
        assert event["prompt_tokens"] == 100
        assert event["completion_tokens"] == 50

    def test_on_llm_error_sends_failed_event(self):
        client = _MockMemClient()
        adapter = LangChainCallbackAdapter(
            mem_client=client, workflow="lc/test", provider="openai", model="gpt-4o-mini"
        )
        adapter.on_llm_start({}, [])
        adapter.on_llm_error(TimeoutError("connection timed out"))
        assert len(client.sent) == 1
        assert client.sent[0]["success"] is False
        assert client.sent[0]["error_type"] == "timeout"

    def test_batch_mode_flushes_on_chain_end(self):
        client = _MockMemClient()
        adapter = LangChainCallbackAdapter(
            mem_client=client, workflow="lc/test", provider="openai", model="gpt-4",
            batch=True, batch_size=5,
        )
        adapter.on_llm_start({}, [])
        adapter.on_llm_end(_MockLLMResult())
        # Not flushed yet
        assert len(client.sent) == 0
        adapter.on_chain_end()
        assert len(client.sent) == 1

    def test_extract_langchain_tokens_from_llm_output(self):
        result = _MockLLMResult(pt=300, ct=120)
        pt, ct = _extract_langchain_tokens(result)
        assert pt == 300
        assert ct == 120

    def test_extract_tokens_none_returns_zeros(self):
        pt, ct = _extract_langchain_tokens(None)
        assert pt == 0
        assert ct == 0

    def test_classify_langchain_timeout(self):
        class LCTimeoutError(Exception):
            pass
        assert _classify_langchain_error(LCTimeoutError()) == "timeout"

    def test_no_forbidden_fields_in_events(self):
        client = _MockMemClient()
        adapter = LangChainCallbackAdapter(
            mem_client=client, workflow="lc/test", provider="openai", model="gpt-4"
        )
        adapter.on_llm_start({}, [])
        adapter.on_llm_end(_MockLLMResult())
        event = client.sent[0]
        forbidden = {"prompt", "response", "content", "messages", "text"}
        assert not any(k in event for k in forbidden)
