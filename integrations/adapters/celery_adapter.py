"""
Celery task adapter — helper for capturing LLM events from Celery background tasks.

Usage (explicit, no signal patching):
    from integrations.adapters.celery_adapter import CeleryTaskEventHelper

    @app.task(bind=True)
    def process_document(self, doc_id: str) -> dict:
        helper = CeleryTaskEventHelper(
            task_name=self.name,
            workflow="celery/tasks.ocr/process-document",
        )
        t0 = time.monotonic()
        try:
            response = llm_client.call(...)
            latency_ms = (time.monotonic() - t0) * 1000
            event = helper.success_event(
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
                retry_count=self.request.retries,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            event = helper.error_event(
                provider="anthropic", model="claude-haiku-4-5-20251001",
                exc=exc, latency_ms=latency_ms,
            )
            raise
        finally:
            mem_client.send_event(event)
"""

from __future__ import annotations

from typing import Any


class CeleryTaskEventHelper:
    """
    Builds LLM event dicts in the context of a Celery task.

    Captures task_name, queue, and retry_count as safe metadata.
    Does not patch Celery signals or modify task behavior.
    """

    def __init__(
        self,
        task_name: str,
        workflow: str,
        queue: str = "default",
    ) -> None:
        self.task_name = task_name
        self.workflow = workflow
        self.queue = queue

    def success_event(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        request_kind: str = "completion",
        estimated_cost: float | None = None,
        retry_count: int = 0,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build a successful task LLM event."""
        meta = {
            "task_name": self.task_name,
            "queue": self.queue,
            "retries": str(retry_count),
        }
        if extra_metadata:
            meta.update(extra_metadata)

        event: dict[str, Any] = {
            "provider": str(provider)[:64],
            "model": str(model)[:128],
            "workflow": str(self.workflow)[:128],
            "prompt_tokens": max(0, int(prompt_tokens)),
            "completion_tokens": max(0, int(completion_tokens)),
            "total_tokens": max(0, int(prompt_tokens)) + max(0, int(completion_tokens)),
            "latency_ms": float(latency_ms),
            "success": True,
            "request_kind": request_kind,
            "schema_version": "1.0",
            "metadata": _truncate_metadata(meta),
        }
        if estimated_cost is not None:
            event["estimated_cost"] = float(estimated_cost)
        return event

    def error_event(
        self,
        *,
        provider: str,
        model: str,
        exc: Exception,
        latency_ms: float = 0.0,
        retry_count: int = 0,
        extra_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build a failed task LLM event."""
        meta = {
            "task_name": self.task_name,
            "queue": self.queue,
            "retries": str(retry_count),
            "exception_type": type(exc).__name__,
        }
        if extra_metadata:
            meta.update(extra_metadata)

        return {
            "provider": str(provider)[:64],
            "model": str(model)[:128],
            "workflow": str(self.workflow)[:128],
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": float(latency_ms),
            "success": False,
            "request_kind": "completion",
            "error_type": _classify_celery_error(exc),
            "schema_version": "1.0",
            "metadata": _truncate_metadata(meta),
        }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _classify_celery_error(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "rate" in name:
        return "rate_limit"
    if "timeout" in name:
        return "timeout"
    if "retry" in name:
        return "retry"
    if "context" in name:
        return "context_length"
    return "task_error"


def _truncate_metadata(meta: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for k, v in meta.items():
        if len(result) >= 10:
            break
        result[str(k)] = str(v)[:256]
    return result
