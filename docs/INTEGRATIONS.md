# Integrations Guide

This guide covers integrating the operational memory system with common AI stacks.

**What integrations do:**
- Capture LLM operational metadata (tokens, latency, provider, workflow)
- Feed data into the operational intelligence layer
- Enable visibility into LLM usage patterns and costs

**What integrations do NOT do:**
- Store prompt text, response text, or conversation content
- Modify, patch, or intercept SDK internals
- Auto-instrument or replace your existing LLM clients
- Require changes to your LLM routing logic

---

## Integration Profiles

Integration profiles provide stack-specific guidance. View all profiles:

```bash
python -c "from integrations.profiles import list_profiles; [print(p.stack, '-', p.display_name) for p in list_profiles()]"
```

Available profiles: `fastapi`, `n8n`, `langchain`, `openai_sdk`, `anthropic_sdk`, `celery`, `ocr_pipeline`

Each profile documents:
- Recommended workflow naming conventions
- Safe metadata keys
- Batching guidance
- Retention recommendations
- Privacy cautions specific to the stack

---

## Event Adapters

Adapters convert SDK response objects into valid event dicts. All adapters are
**explicit** — you call them after your LLM call. No monkey-patching, no signals.

### OpenAI SDK

```python
import time
import openai
from integrations.adapters.openai_adapter import adapt_openai_response, adapt_openai_error
from sdk.python.client import OperationalMemoryClient

mem_client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")
llm_client = openai.OpenAI()

t0 = time.monotonic()
try:
    response = llm_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_openai_response(response, workflow="my-feature", latency_ms=latency_ms)
except Exception as exc:
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_openai_error(exc, workflow="my-feature", model="gpt-4o-mini", latency_ms=latency_ms)
    raise
finally:
    mem_client.send_event(event)
```

### Anthropic SDK

```python
import time
import anthropic
from integrations.adapters.anthropic_adapter import adapt_anthropic_response, adapt_anthropic_error
from sdk.python.client import OperationalMemoryClient

mem_client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")
llm_client = anthropic.Anthropic()

t0 = time.monotonic()
try:
    message = llm_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}],
    )
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_anthropic_response(message, workflow="my-feature", latency_ms=latency_ms)
except Exception as exc:
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_anthropic_error(exc, workflow="my-feature", model="claude-haiku-4-5-20251001", latency_ms=latency_ms)
    raise
finally:
    mem_client.send_event(event)
```

### Generic HTTP (self-hosted, proxied, or custom providers)

```python
import time, httpx
from integrations.adapters.http_adapter import adapt_http_response, adapt_http_error
from sdk.python.client import OperationalMemoryClient

mem_client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")

t0 = time.monotonic()
try:
    resp = httpx.post("https://my-llm-proxy.internal/v1/chat", json=payload)
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_http_response(
        resp.json(), workflow="my-feature", provider="my-provider",
        model="my-model", latency_ms=latency_ms, status_code=resp.status_code,
    )
except Exception as exc:
    latency_ms = (time.monotonic() - t0) * 1000
    event = adapt_http_error(exc, workflow="my-feature", provider="my-provider", model="my-model")
    raise
finally:
    mem_client.send_event(event)
```

### LangChain Callback

```python
from integrations.adapters.langchain_adapter import LangChainCallbackAdapter
from sdk.python.client import OperationalMemoryClient
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA

mem_client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")
callback = LangChainCallbackAdapter(
    mem_client=mem_client,
    workflow="langchain/rag-qa",
    provider="openai",
    model="gpt-4o-mini",
    batch=True,         # batch events, flush on chain end
    batch_size=10,
)

llm = ChatOpenAI(model="gpt-4o-mini", callbacks=[callback])
chain = RetrievalQA.from_chain_type(llm=llm, ...)
result = chain.run(query)
callback.flush()        # ensure any buffered events are sent
```

### Celery Task Helper

```python
import time
from integrations.adapters.celery_adapter import CeleryTaskEventHelper
from sdk.python.client import OperationalMemoryClient

mem_client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")

@app.task(bind=True)
def process_document(self, doc_id: str):
    helper = CeleryTaskEventHelper(
        task_name=self.name,
        workflow="celery/tasks.processing/process-document",
        queue="processing",
    )
    t0 = time.monotonic()
    event = None
    try:
        response = call_llm(...)
        latency_ms = (time.monotonic() - t0) * 1000
        event = helper.success_event(
            provider="anthropic", model="claude-haiku-4-5-20251001",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            retry_count=self.request.retries,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        event = helper.error_event(
            provider="anthropic", model="claude-haiku-4-5-20251001",
            exc=exc, latency_ms=latency_ms, retry_count=self.request.retries,
        )
        raise
    finally:
        if event:
            mem_client.send_event(event)
```

---

## Workflow Naming

Workflow names are the primary way to trace LLM activity. Good naming:

| Good | Avoid |
|---|---|
| `api/summarize-document` | `POST /api/summarize` (HTTP method) |
| `langchain/rag-qa` | `langchain_chain_run` |
| `celery/tasks.ocr/extract` | `task_abc123` (IDs) |
| `n8n/email-triage/classify` | user-specific values |
| `anthropic/document-extractor` | `messages_create` (API method name) |

**Rules:**
- Use `/` as a namespace separator
- Lowercase, dashes-ok
- No user IDs, session tokens, or data values
- Describe the logical operation, not the SDK method

---

## Batching Recommendations

| Stack | Recommended | Batch Size |
|---|---|---|
| FastAPI endpoint | No (1 per request) | 1 |
| n8n workflow node | No | 1 |
| LangChain agent | Yes (agent loop) | 10 |
| Celery workers | Yes (high volume) | 20 |
| OCR pipeline | Yes | 10 |

---

## Privacy Constraints

**Never include these in any event payload or metadata:**

```
prompt, response, content, messages, text, system_prompt,
user_message, assistant_message, completion, choices,
input, output, body, payload, conversation, context,
instruction, query, answer, raw, request, transcript,
dialogue, chat, history, thread
```

**Safe to capture:**
- Token counts (prompt_tokens, completion_tokens)
- Latency in milliseconds
- Provider and model name
- Stop reason, finish reason
- Cache token counts (Anthropic)
- Error type classification
- HTTP status codes
- Task names, queue names
- Environment labels (prod/staging)

---

## Troubleshooting

**Event rejected with `forbidden_fields`:**
- Remove the flagged field from the payload
- Check metadata keys — they are also checked

**Event rejected with `payload_too_large`:**
- Trim metadata values (max 256 chars each)
- Reduce number of metadata keys (max 10)

**Project not found (404 on /projects/{id}):**
- Register the project first: `POST /projects` or `aom register <project-id>`

**High error rate on events:**
- Check that `error_type` is set when `success=False`
- Verify the LLM client error classification

**Zero token counts:**
- For OpenAI: ensure you're reading `response.usage.prompt_tokens`
- For Anthropic: ensure you're reading `message.usage.input_tokens`
- For streaming: capture tokens from the final chunk only

---

## Operational Limits

| Limit | Value |
|---|---|
| Max events per hour (per project, default) | 1,000 |
| Burst threshold (5 min window) | 200 events |
| Max metadata keys | 10 |
| Max metadata value | 256 characters |
| Max payload size | 8 KB |
| Minimum retention (safety floor) | 10 most recent events |
