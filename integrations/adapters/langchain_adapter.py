"""
LangChain callback adapter — captures LLM events via LangChain's callback system.

This adapter implements BaseCallbackHandler (if langchain is installed) or
provides a duck-typed standalone class that LangChain will accept.

IMPORTANT:
- Never reads llm_output text, response content, or generated tokens
- Only reads token usage metadata from LLMResult.llm_output["token_usage"]
- All content fields are explicitly ignored
- No auto-instrumentation; must be passed explicitly to LangChain chains/agents

Usage:
    from integrations.adapters.langchain_adapter import LangChainCallbackAdapter
    from sdk.python.client import OperationalMemoryClient

    mem_client = OperationalMemoryClient(base_url="...", project_id="my-app")
    callback = LangChainCallbackAdapter(
        mem_client=mem_client,
        workflow="langchain/rag-qa",
        provider="openai",
        model="gpt-4o-mini",
    )

    chain = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(callbacks=[callback]),
        ...
    )
"""

from __future__ import annotations

import time
from typing import Any


class LangChainCallbackAdapter:
    """
    LangChain-compatible callback handler that captures LLM operational events.

    Works as a drop-in LangChain callback without importing langchain at
    adapter definition time — uses duck-typing.

    Reads from LangChain callback arguments:
    - on_llm_start: records start time
    - on_llm_end: extracts token_usage from llm_output (safe, no text content)
    - on_llm_error: records failure

    Never reads: response text, generated content, tool call arguments,
    retrieved documents, or any user-facing output.
    """

    def __init__(
        self,
        mem_client: Any,
        workflow: str,
        provider: str,
        model: str,
        extra_metadata: dict[str, str] | None = None,
        batch: bool = False,
        batch_size: int = 10,
    ) -> None:
        self._client = mem_client
        self._workflow = workflow
        self._provider = provider
        self._model = model
        self._extra_metadata = extra_metadata or {}
        self._batch = batch
        self._batch_size = batch_size
        self._pending: list[dict[str, Any]] = []
        self._start_time: float | None = None

    # ------------------------------------------------------------------
    # LangChain callback interface (duck-typed, no langchain import needed)
    # ------------------------------------------------------------------

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any
    ) -> None:
        """Record start timestamp. Do not read prompts."""
        self._start_time = time.monotonic()

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Extract token usage from LLM result. Do not read generated text."""
        latency_ms = 0.0
        if self._start_time is not None:
            latency_ms = (time.monotonic() - self._start_time) * 1000
            self._start_time = None

        prompt_tokens, completion_tokens = _extract_langchain_tokens(response)
        event = _build_event(
            provider=self._provider,
            model=self._model,
            workflow=self._workflow,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=True,
            extra_metadata=self._extra_metadata,
        )
        self._emit(event)

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        """Record a failed LLM call."""
        latency_ms = 0.0
        if self._start_time is not None:
            latency_ms = (time.monotonic() - self._start_time) * 1000
            self._start_time = None

        event = _build_event(
            provider=self._provider,
            model=self._model,
            workflow=self._workflow,
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=latency_ms,
            success=False,
            error_type=_classify_langchain_error(error),
            extra_metadata=self._extra_metadata,
        )
        self._emit(event)

    def on_chain_start(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_chain_end(self, *args: Any, **kwargs: Any) -> None:
        if self._batch and self._pending:
            self.flush()

    def on_chain_error(self, *args: Any, **kwargs: Any) -> None:
        if self._pending:
            self.flush()

    def on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_tool_end(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_tool_error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_agent_action(self, *args: Any, **kwargs: Any) -> None:
        pass

    def on_agent_finish(self, *args: Any, **kwargs: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # Batch management
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Send all pending batched events immediately."""
        if self._pending:
            self._client.send_batch(list(self._pending))
            self._pending.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        if self._batch:
            self._pending.append(event)
            if len(self._pending) >= self._batch_size:
                self.flush()
        else:
            self._client.send_event(event)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_langchain_tokens(response: Any) -> tuple[int, int]:
    """Extract token counts from a LangChain LLMResult without reading content."""
    if response is None:
        return 0, 0

    # LLMResult.llm_output["token_usage"] — safe, contains only counts
    llm_output = getattr(response, "llm_output", None)
    if llm_output and isinstance(llm_output, dict):
        token_usage = llm_output.get("token_usage", {})
        if token_usage:
            pt = int(token_usage.get("prompt_tokens", 0) or 0)
            ct = int(token_usage.get("completion_tokens", 0) or 0)
            return pt, ct

    # generations[0][0].generation_info["usage"] — alternative shape
    generations = getattr(response, "generations", None)
    if generations and isinstance(generations, (list, tuple)) and len(generations) > 0:
        first_gen_list = generations[0]
        if isinstance(first_gen_list, (list, tuple)) and len(first_gen_list) > 0:
            gen = first_gen_list[0]
            gen_info = getattr(gen, "generation_info", None)
            if gen_info and isinstance(gen_info, dict):
                usage = gen_info.get("usage") or {}
                pt = int(usage.get("prompt_tokens", 0) or 0)
                ct = int(usage.get("completion_tokens", 0) or 0)
                if pt or ct:
                    return pt, ct

    return 0, 0


def _classify_langchain_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "rate" in msg:
        return "rate_limit"
    if "timeout" in name:
        return "timeout"
    if "context" in msg or "too long" in msg:
        return "context_length"
    if "authen" in msg:
        return "authentication"
    return "llm_error"


def _build_event(
    *,
    provider: str,
    model: str,
    workflow: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    success: bool,
    error_type: str | None = None,
    extra_metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": str(provider)[:64],
        "model": str(model)[:128],
        "workflow": str(workflow)[:128],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_ms": float(latency_ms),
        "success": success,
        "request_kind": "chat",
        "schema_version": "1.0",
    }
    if error_type:
        event["error_type"] = error_type
    if extra_metadata:
        truncated: dict[str, str] = {}
        for k, v in extra_metadata.items():
            if len(truncated) >= 10:
                break
            truncated[str(k)] = str(v)[:256]
        if truncated:
            event["metadata"] = truncated
    return event
