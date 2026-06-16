"""Tests for memory/llm_store.py — LLM event store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory.llm_store import LLMEventStore
from schemas.llm_event_schema import LLMEvent


def _recent_ts(hours_ago: float = 1.0) -> str:
    """A timestamp inside the default aggregation windows (now-relative).

    Aggregation queries filter on `datetime('now', '-N hours')`, so fixtures must
    be dated relative to now — a fixed past date silently ages out of the window.
    """
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()


def _make_event(**overrides) -> LLMEvent:
    base = LLMEvent(
        timestamp=_recent_ts(),
        provider="anthropic",
        model="claude-sonnet-4-6",
        workflow="doc-processing",
        prompt_tokens=1000,
        completion_tokens=400,
        total_tokens=1400,
        latency_ms=2200.0,
        success=True,
        request_kind="completion",
        estimated_cost=0.004,
        metadata={"env": "prod"},
    )
    for k, v in overrides.items():
        object.__setattr__(base, k, v)
    return base


@pytest.fixture
def store(tmp_path):
    s = LLMEventStore(str(tmp_path / "test.db"))
    s.connect()
    yield s
    s.disconnect()


class TestAppendAndQuery:
    def test_append_returns_id(self, store):
        event_id = store.append(_make_event())
        assert isinstance(event_id, int)
        assert event_id > 0

    def test_query_returns_appended_event(self, store):
        store.append(_make_event())
        rows = store.query(limit=10)
        assert len(rows) == 1
        assert rows[0]["provider"] == "anthropic"
        assert rows[0]["workflow"] == "doc-processing"

    def test_query_by_provider(self, store):
        store.append(_make_event(provider="openai"))
        store.append(_make_event(provider="anthropic"))
        rows = store.query(provider="openai")
        assert len(rows) == 1
        assert rows[0]["provider"] == "openai"

    def test_query_by_workflow(self, store):
        store.append(_make_event(workflow="ocr"))
        store.append(_make_event(workflow="chat"))
        rows = store.query(workflow="ocr")
        assert len(rows) == 1
        assert rows[0]["workflow"] == "ocr"

    def test_query_success_only(self, store):
        store.append(_make_event(success=True))
        store.append(_make_event(success=False))
        rows = store.query(success_only=True)
        assert all(r["success"] is True for r in rows)

    def test_query_failures_only(self, store):
        store.append(_make_event(success=True))
        store.append(_make_event(success=False))
        rows = store.query(success_only=False)
        assert all(r["success"] is False for r in rows)

    def test_query_limit_respected(self, store):
        for _ in range(20):
            store.append(_make_event())
        rows = store.query(limit=5)
        assert len(rows) == 5

    def test_metadata_deserialized(self, store):
        store.append(_make_event(metadata={"stage": "extraction"}))
        rows = store.query(limit=1)
        assert rows[0]["metadata"]["stage"] == "extraction"

    def test_success_is_bool(self, store):
        store.append(_make_event(success=True))
        rows = store.query(limit=1)
        assert isinstance(rows[0]["success"], bool)
        assert rows[0]["success"] is True


class TestCount:
    def test_count_empty_store(self, store):
        assert store.count_events() == 0

    def test_count_after_appends(self, store):
        store.append(_make_event())
        store.append(_make_event())
        assert store.count_events() == 2

    def test_count_by_provider(self, store):
        store.append(_make_event(provider="openai"))
        store.append(_make_event(provider="anthropic"))
        assert store.count_events(provider="openai") == 1

    def test_count_by_workflow(self, store):
        store.append(_make_event(workflow="ocr"))
        store.append(_make_event(workflow="chat"))
        assert store.count_events(workflow="ocr") == 1


class TestAggregation:
    def test_aggregate_by_provider_returns_rows(self, store):
        store.append(_make_event(provider="anthropic"))
        store.append(_make_event(provider="openai"))
        rows = store.aggregate_by_provider()
        providers = [r["provider"] for r in rows]
        assert "anthropic" in providers
        assert "openai" in providers

    def test_aggregate_by_workflow_returns_rows(self, store):
        store.append(_make_event(workflow="ocr"))
        store.append(_make_event(workflow="chat"))
        rows = store.aggregate_by_workflow()
        workflows = [r["workflow"] for r in rows]
        assert "ocr" in workflows
        assert "chat" in workflows

    def test_aggregate_token_sum(self, store):
        store.append(_make_event(total_tokens=1000))
        store.append(_make_event(total_tokens=500))
        rows = store.aggregate_by_provider()
        assert rows[0]["total_tokens"] == 1500

    def test_aggregate_error_count(self, store):
        store.append(_make_event(success=True))
        store.append(_make_event(success=False))
        rows = store.aggregate_by_provider()
        assert rows[0]["error_count"] == 1

    def test_aggregate_error_trend_empty(self, store):
        store.append(_make_event(success=True))
        rows = store.aggregate_error_trend()
        assert rows == []

    def test_aggregate_error_trend_with_errors(self, store):
        store.append(_make_event(success=False, error_type="rate_limit"))
        rows = store.aggregate_error_trend()
        assert len(rows) >= 1
        assert rows[0]["error_type"] == "rate_limit"

    def test_aggregate_daily_totals(self, store):
        store.append(_make_event(timestamp=_recent_ts(hours_ago=2), total_tokens=100))
        store.append(_make_event(timestamp=_recent_ts(hours_ago=1), total_tokens=200))
        rows = store.aggregate_daily_totals(window_days=7)
        assert len(rows) >= 1
        total = sum(r["total_tokens"] for r in rows)
        assert total == 300


class TestRetention:
    def test_delete_by_age(self, store):
        store.append(_make_event(timestamp="2020-01-01T00:00:00Z"))
        store.append(_make_event(timestamp="2026-05-17T00:00:00Z"))
        deleted = store.delete_events_older_than(retention_days=30)
        assert deleted == 1
        assert store.count_events() == 1

    def test_delete_by_count(self, store):
        for _ in range(10):
            store.append(_make_event())
        deleted = store.delete_events_exceeding_count(max_count=5, min_keep=3)
        assert deleted == 5
        assert store.count_events() == 5

    def test_delete_by_count_respects_floor(self, store):
        for _ in range(5):
            store.append(_make_event())
        deleted = store.delete_events_exceeding_count(max_count=2, min_keep=5)
        assert deleted == 0
        assert store.count_events() == 5


class TestStorageEstimate:
    def test_storage_estimate_returns_dict(self, store):
        store.append(_make_event())
        est = store.get_storage_estimate()
        assert "total_events" in est
        assert "db_size_bytes" in est
        assert est["total_events"] == 1

    def test_list_providers(self, store):
        store.append(_make_event(provider="openai"))
        store.append(_make_event(provider="anthropic"))
        providers = store.list_providers()
        assert "openai" in providers
        assert "anthropic" in providers

    def test_list_workflows(self, store):
        store.append(_make_event(workflow="ocr"))
        workflows = store.list_workflows()
        assert "ocr" in workflows
