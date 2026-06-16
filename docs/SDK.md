# SDK Reference

The `sdk/python/` module provides a lightweight sync HTTP client for ingesting
LLM operational events into the operational memory service.

**Design constraints:**
- No heavy dependencies — uses `httpx` if installed, falls back to `requests`, then stdlib `urllib`
- Sync-first — no async, no threads, no queues
- Privacy-safe — client rejects forbidden fields before sending
- Project-scoped — each client instance is bound to one `project_id`

---

## Installation

No separate installation needed within this repo. The SDK lives at `sdk/python/`.

For use in external projects, copy `sdk/python/client.py` and `sdk/python/helpers.py`
alongside your application code. Only `httpx` or `requests` is required as a transport.

```bash
pip install httpx   # recommended
# OR
pip install requests
```

---

## Quick Start

```python
from sdk.python.client import OperationalMemoryClient
from sdk.python.helpers import build_event

client = OperationalMemoryClient(
    base_url="http://localhost:8000",
    project_id="my-rag-app",
)

event = build_event(
    provider="anthropic",
    model="claude-sonnet-4-6",
    workflow="document-summarizer",
    prompt_tokens=1200,
    completion_tokens=350,
    latency_ms=2800.0,
    success=True,
)

result = client.send_event(event)
print(result.success)       # True
print(result.event_id)      # server-assigned ID if returned
print(result.warnings)      # any non-fatal server warnings
```

---

## OperationalMemoryClient

```python
OperationalMemoryClient(
    base_url: str,
    project_id: str,
    *,
    timeout: float = 10.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    max_batch_size: int = 50,
)
```

| Parameter | Default | Description |
|---|---|---|
| `base_url` | — | Service URL (no trailing slash) |
| `project_id` | — | Project namespace for all events |
| `timeout` | 10.0 | HTTP timeout in seconds |
| `max_retries` | 3 | Retries on 5xx and connection errors |
| `retry_delay` | 1.0 | Base delay between retries (doubles each attempt) |
| `max_batch_size` | 50 | Max events per `send_batch()` chunk |

### Methods

#### `send_event(event: dict) → SendResult`

Send a single event. Performs client-side privacy check before sending.
Retries on transient 5xx errors and connection failures.

Returns `SendResult`:
- `success: bool`
- `status_code: int | None`
- `event_id: str | None`
- `warnings: list[str]`
- `rejection_reason: str | None`
- `error: str | None`

#### `send_batch(events: list[dict]) → BatchResult`

Send multiple events in sequence. Each event is privacy-checked individually.
Failed events do not abort remaining events.

Returns `BatchResult`:
- `total: int`
- `accepted: int`
- `rejected: int`
- `errors: int`
- `all_accepted: bool`

#### `health() → dict`

Check service health. Returns parsed JSON or `{"error": "..."}`.

#### `project_summary() → dict`

Fetch summary for this client's project_id.

#### `llm_summary() → dict`

Fetch LLM usage summary for the service.

---

## build_event()

```python
from sdk.python.helpers import build_event

event = build_event(
    provider="anthropic",         # required: provider name
    model="claude-sonnet-4-6",    # required: model identifier
    workflow="my-workflow",        # required: logical workflow label
    prompt_tokens=1200,           # required: tokens in prompt/input
    completion_tokens=350,        # required: tokens in response
    latency_ms=2800.0,            # required: end-to-end latency ms
    success=True,                  # optional (default: True)
    request_kind="chat",           # optional (default: "completion")
    estimated_cost=0.003,         # optional: USD, if known
    error_type=None,               # optional: error category if failed
    metadata={"env": "prod"},     # optional: bounded operational tags
    timestamp=None,                # optional: ISO 8601, defaults to now
)
```

### build_error_event()

```python
from sdk.python.helpers import build_error_event

event = build_error_event(
    provider="openai",
    model="gpt-4o-mini",
    workflow="my-workflow",
    error_type="rate_limit",       # required for error events
    prompt_tokens=0,               # optional
    latency_ms=500.0,              # optional
)
```

### build_embedding_event()

```python
from sdk.python.helpers import build_embedding_event

event = build_embedding_event(
    provider="openai",
    model="text-embedding-3-small",
    workflow="document-indexer",
    input_tokens=2000,
    latency_ms=450.0,
    estimated_cost=0.0001,
)
```

---

## Error + Retry Pattern

```python
import time
from sdk.python.client import OperationalMemoryClient
from sdk.python.helpers import build_event, build_error_event

client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")

t0 = time.monotonic()
try:
    response = my_llm_client.call(...)
    latency_ms = (time.monotonic() - t0) * 1000
    event = build_event(
        provider="openai", model="gpt-4o-mini",
        workflow="my-feature/summarize",
        prompt_tokens=response.usage.prompt_tokens,
        completion_tokens=response.usage.completion_tokens,
        latency_ms=latency_ms,
    )
except Exception as exc:
    latency_ms = (time.monotonic() - t0) * 1000
    event = build_error_event(
        provider="openai", model="gpt-4o-mini",
        workflow="my-feature/summarize",
        error_type="api_error",
        latency_ms=latency_ms,
    )
    raise  # re-raise after capturing event
finally:
    client.send_event(event)   # always sends, even on error
```

---

## Batch Example (Celery, n8n, high-volume)

```python
events = []
for item in batch:
    event = build_event(...)
    events.append(event)

result = client.send_batch(events)
print(f"Accepted {result.accepted}/{result.total}")
```

---

## Privacy Constraints

The following field names must never appear in an event payload or metadata:

```
prompt, response, content, message, messages, text,
system_prompt, user_message, assistant_message, completion,
choices, input, output, body, payload, conversation,
context, instruction, query, answer, raw, request,
transcript, dialogue, chat, history, thread
```

The client checks for these fields before sending. The server privacy gate
also rejects them. **False positives are acceptable. Content leakage is not.**

---

## Operational Limits

| Limit | Value |
|---|---|
| Max events per hour (default) | 1,000 |
| Max metadata keys per event | 10 |
| Max metadata value length | 256 characters |
| Max batch size (client) | 50 events |
| Max payload size (server) | 8 KB |
| HTTP timeout (default) | 10 seconds |
| Retry attempts (default) | 3 |
