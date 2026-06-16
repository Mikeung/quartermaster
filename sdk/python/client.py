"""
OperationalMemoryClient — lightweight sync HTTP client for event ingestion.

Design rules:
- No heavy dependencies (requests or httpx only)
- Sync-first; no async
- Retry-safe with exponential backoff (no jitter complexity)
- Project-scoped: every client is bound to one project_id
- Privacy-safe: client rejects obviously forbidden fields before sending
- Bounded: batch size enforced at client level

Usage:
    client = OperationalMemoryClient(base_url="http://localhost:8000", project_id="my-app")
    client.send_event(build_event(provider="anthropic", model="claude-sonnet-4-6", ...))
    client.send_batch([event1, event2, ...])
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 1.0
_DEFAULT_MAX_BATCH_SIZE = 50

# Fields that must never be sent (privacy gate)
_FORBIDDEN_FIELDS = frozenset({
    "prompt", "response", "content", "message", "messages", "text",
    "system_prompt", "user_message", "assistant_message", "completion",
    "choices", "input", "output", "body", "payload", "conversation",
    "context", "instruction", "query", "answer", "raw", "request",
    "transcript", "dialogue", "chat", "history", "thread",
})


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SendResult:
    """Result of a single event send."""
    success: bool
    status_code: int | None = None
    event_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status_code": self.status_code,
            "event_id": self.event_id,
            "warnings": self.warnings,
            "rejection_reason": self.rejection_reason,
            "error": self.error,
        }


@dataclass
class BatchResult:
    """Result of a batch send."""
    total: int
    accepted: int
    rejected: int
    errors: int
    results: list[SendResult] = field(default_factory=list)

    @property
    def all_accepted(self) -> bool:
        return self.accepted == self.total

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "errors": self.errors,
            "all_accepted": self.all_accepted,
        }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OperationalMemoryClient:
    """
    Sync HTTP client for the quartermaster ingestion API.

    Binds to a single project_id. All events sent through this client
    are tagged with that project.

    Args:
        base_url: Base URL of the operational memory service (no trailing slash).
        project_id: Project namespace for all events sent through this client.
        timeout: HTTP timeout in seconds.
        max_retries: Number of retry attempts on transient failures (5xx, timeout).
        retry_delay: Base delay in seconds between retries (doubles each attempt).
        max_batch_size: Maximum events per batch call.
    """

    def __init__(
        self,
        base_url: str,
        project_id: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_RETRY_DELAY,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_id = project_id
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_batch_size = max_batch_size
        self._http = _make_http_client(timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_event(self, event: dict[str, Any]) -> SendResult:
        """
        Send a single LLM event.

        Performs a client-side privacy check before sending.
        Retries on transient server errors (5xx) and connection failures.
        """
        rejection = _check_forbidden_fields(event)
        if rejection:
            logger.warning("Client privacy check rejected event", extra={"reason": rejection})
            return SendResult(success=False, rejection_reason=rejection)

        payload = dict(event)
        payload["project_id"] = self.project_id

        return self._post_with_retry("/llm/events", payload)

    def send_batch(self, events: list[dict[str, Any]]) -> BatchResult:
        """
        Send multiple events in sequence (no server-side batch endpoint required).

        Splits into chunks of max_batch_size. Each event is privacy-checked
        before sending. Failed events do not abort the remaining batch.
        """
        total = len(events)
        accepted = rejected = errors = 0
        results: list[SendResult] = []

        for i in range(0, total, self.max_batch_size):
            chunk = events[i : i + self.max_batch_size]
            for event in chunk:
                result = self.send_event(event)
                results.append(result)
                if result.success:
                    accepted += 1
                elif result.error:
                    errors += 1
                else:
                    rejected += 1

        batch_result = BatchResult(
            total=total,
            accepted=accepted,
            rejected=rejected,
            errors=errors,
            results=results,
        )
        logger.info(
            "Batch send complete",
            extra={
                "project_id": self.project_id,
                "total": total,
                "accepted": accepted,
                "rejected": rejected,
                "errors": errors,
            },
        )
        return batch_result

    def health(self) -> dict[str, Any]:
        """Check service health. Returns parsed JSON or error dict."""
        try:
            resp = self._http.get(f"{self.base_url}/health", timeout=self.timeout)
            return resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def project_summary(self) -> dict[str, Any]:
        """Fetch summary for this client's project_id."""
        try:
            resp = self._http.get(
                f"{self.base_url}/projects/{self.project_id}/summary",
                timeout=self.timeout,
            )
            return resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def ingestion_pressure(self) -> dict[str, Any]:
        """Fetch ingestion pressure status for the full fleet."""
        try:
            resp = self._http.get(f"{self.base_url}/projects/pressure", timeout=self.timeout)
            return resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    def llm_summary(self) -> dict[str, Any]:
        """Fetch LLM usage summary."""
        try:
            resp = self._http.get(f"{self.base_url}/llm/summary", timeout=self.timeout)
            return resp.json() if resp.status_code == 200 else {"error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post_with_retry(self, path: str, payload: dict[str, Any]) -> SendResult:
        url = f"{self.base_url}{path}"
        delay = self.retry_delay

        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.post(url, json=payload, timeout=self.timeout)

                if resp.status_code == 200:
                    data = resp.json()
                    return SendResult(
                        success=True,
                        status_code=200,
                        event_id=data.get("event_id"),
                        warnings=data.get("warnings", []),
                    )
                if resp.status_code == 422:
                    data = resp.json()
                    reason = _extract_rejection_reason(data)
                    return SendResult(
                        success=False,
                        status_code=422,
                        rejection_reason=reason,
                    )
                if resp.status_code == 429:
                    return SendResult(
                        success=False,
                        status_code=429,
                        rejection_reason="rate_limited",
                    )
                if resp.status_code >= 500 and attempt < self.max_retries:
                    logger.warning(
                        "Transient server error, retrying",
                        extra={"attempt": attempt + 1, "status": resp.status_code},
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                return SendResult(
                    success=False,
                    status_code=resp.status_code,
                    error=f"HTTP {resp.status_code}",
                )

            except Exception as exc:
                if attempt < self.max_retries:
                    logger.warning(
                        "Send failed, retrying",
                        extra={"attempt": attempt + 1, "error": str(exc)},
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                return SendResult(success=False, error=str(exc))

        return SendResult(success=False, error="max_retries_exceeded")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_client(timeout: float) -> Any:
    """Return an httpx.Client if available, else a requests.Session wrapper."""
    try:
        import httpx  # type: ignore[import-untyped]
        return httpx.Client(timeout=timeout)
    except ImportError:
        pass
    try:
        import requests  # type: ignore[import-untyped]
        return _RequestsWrapper(requests.Session(), timeout)
    except ImportError:
        pass
    raise ImportError(
        "No HTTP library available. Install httpx or requests: "
        "pip install httpx  OR  pip install requests"
    )


class _RequestsWrapper:
    """Thin adapter so requests.Session matches the httpx interface used above."""

    def __init__(self, session: Any, timeout: float) -> None:
        self._session = session
        self._timeout = timeout

    def get(self, url: str, *, timeout: float | None = None) -> Any:
        return self._session.get(url, timeout=timeout or self._timeout)

    def post(self, url: str, *, json: Any, timeout: float | None = None) -> Any:
        return self._session.post(url, json=json, timeout=timeout or self._timeout)


def _check_forbidden_fields(event: dict[str, Any]) -> str | None:
    """Return a rejection reason string if forbidden fields are found, else None."""
    found = [k for k in event if k.lower() in _FORBIDDEN_FIELDS]
    if found:
        return f"forbidden_fields: {', '.join(found)}"
    # Check metadata values
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        forbidden_meta = [k for k in metadata if k.lower() in _FORBIDDEN_FIELDS]
        if forbidden_meta:
            return f"forbidden_metadata_keys: {', '.join(forbidden_meta)}"
    return None


def _extract_rejection_reason(data: dict[str, Any]) -> str:
    """Extract a human-readable rejection reason from a 422 response body."""
    if isinstance(data, dict):
        if "rejection_reason" in data:
            return str(data["rejection_reason"])
        if "detail" in data:
            detail = data["detail"]
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list) and detail:
                return str(detail[0].get("msg", "validation_error"))
    return "validation_error"
