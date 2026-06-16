"""
Telegram delivery adapter — push-only, failure-tolerant, non-blocking.

Contract:
- NEVER raises to caller: all exceptions are caught, logged, counted
- NEVER breaks scans, retention, report generation, or the scheduler
- NEVER logs the bot token or exposes it in error messages
- Bounded retries: max 2 with fixed 2s delay (no exponential storms)
- Timeout: 10s per HTTP call

All public methods return DeliveryResult(success, error).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from delivery.health import DeliveryHealthTracker, get_tracker

logger = logging.getLogger(__name__)

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_DEFAULT_TIMEOUT_S = 10
_MAX_RETRIES = 2
_RETRY_DELAY_S = 2.0
_MAX_MESSAGE_LEN = 4096
_TRUNCATION_SUFFIX = "\n\n<i>(message truncated — see full report)</i>"


@dataclass
class DeliveryResult:
    success: bool
    error: str | None = None
    status_code: int | None = None
    attempt_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "error": self.error,
            "status_code": self.status_code,
            "attempt_count": self.attempt_count,
        }


class TelegramDeliveryClient:
    """
    Sends messages to a Telegram chat via the Bot API.

    Failure is always graceful — never raises, always returns DeliveryResult.
    Token is stored privately and never logged.
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        tracker: DeliveryHealthTracker | None = None,
    ) -> None:
        self._token = token
        self._chat_id = str(chat_id)
        self._tracker = tracker or get_tracker()
        self._url = _TELEGRAM_API_BASE.format(token=token)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send_message(self, text: str, parse_mode: str = "HTML") -> DeliveryResult:
        """Send a plain or HTML text message. Truncates if over 4096 chars."""
        safe_text = _truncate(text, parse_mode)
        return self._post({"text": safe_text, "parse_mode": parse_mode})

    def send_markdown_report(self, title: str, content: str) -> DeliveryResult:
        """
        Send a report as a Telegram message.

        Converts the first ~4000 chars to HTML-safe content and prepends the title.
        Large reports are truncated with a notice.
        """
        header = f"<b>{_escape_html(title)}</b>\n\n"
        body = _escape_html(content)
        full = header + body
        safe = _truncate(full, "HTML")
        return self._post({"text": safe, "parse_mode": "HTML"})

    def send_digest(self, digest_text: str) -> DeliveryResult:
        """Send a pre-formatted digest message (HTML format expected)."""
        safe = _truncate(digest_text, "HTML")
        return self._post({"text": safe, "parse_mode": "HTML"})

    def send_alert(self, severity: str, message: str) -> DeliveryResult:
        """Send an operational alert. severity: 'critical' | 'warning' | 'info'"""
        icon = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity.lower(), "⚠️")
        text = f"{icon} <b>{severity.upper()}</b>\n\n{_escape_html(message)}"
        safe = _truncate(text, "HTML")
        return self._post({"text": safe, "parse_mode": "HTML"})

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> DeliveryResult:
        """HTTP POST to Telegram with bounded retries. Never raises."""
        payload["chat_id"] = self._chat_id

        last_error: str | None = None
        last_status: int | None = None
        t_start = time.perf_counter()

        for attempt in range(1, _MAX_RETRIES + 2):  # 1, 2, 3 → but cap at MAX_RETRIES+1 calls
            if attempt > _MAX_RETRIES + 1:
                break
            try:
                resp = requests.post(
                    self._url,
                    json=payload,
                    timeout=_DEFAULT_TIMEOUT_S,
                )
                last_status = resp.status_code
                if resp.status_code == 200:
                    latency_ms = (time.perf_counter() - t_start) * 1000.0
                    self._tracker.record_success(latency_ms)
                    logger.info(
                        "Telegram message delivered",
                        extra={
                            "chat_id": self._chat_id,
                            "status": resp.status_code,
                            "latency_ms": round(latency_ms, 1),
                            "attempt": attempt,
                        },
                    )
                    return DeliveryResult(
                        success=True,
                        status_code=resp.status_code,
                        attempt_count=attempt,
                    )
                # Non-200 — log without token, maybe retry
                error_body = resp.text[:300] if resp.text else "(empty)"
                last_error = f"HTTP {resp.status_code}: {error_body}"
                logger.warning(
                    "Telegram delivery non-200",
                    extra={
                        "status": resp.status_code,
                        "attempt": attempt,
                        "body_excerpt": error_body,
                    },
                )
                # 429 Too Many Requests — back off and retry
                if resp.status_code == 429 and attempt <= _MAX_RETRIES:
                    retry_after = _parse_retry_after(resp) or _RETRY_DELAY_S
                    time.sleep(min(retry_after, 10.0))
                    continue
                # 4xx client errors (bad token, chat not found) — no point retrying
                if 400 <= resp.status_code < 500:
                    break
            except requests.exceptions.Timeout:
                last_error = "Request timed out"
                logger.warning(
                    "Telegram delivery timed out",
                    extra={"attempt": attempt, "timeout_s": _DEFAULT_TIMEOUT_S},
                )
            except requests.exceptions.ConnectionError as exc:
                last_error = f"Connection error: {type(exc).__name__}"
                logger.warning(
                    "Telegram delivery connection error",
                    extra={"attempt": attempt, "error_type": type(exc).__name__},
                )
            except Exception as exc:
                last_error = f"Unexpected error: {type(exc).__name__}"
                logger.warning(
                    "Telegram delivery unexpected error",
                    extra={"attempt": attempt, "error_type": type(exc).__name__},
                )

            if attempt <= _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S)

        self._tracker.record_failure(last_error or "unknown")
        logger.error(
            "Telegram delivery failed after retries",
            extra={
                "attempts": min(attempt, _MAX_RETRIES + 1),
                "last_status": last_status,
                "error": last_error,
            },
        )
        return DeliveryResult(
            success=False,
            error=last_error,
            status_code=last_status,
            attempt_count=min(attempt, _MAX_RETRIES + 1),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, parse_mode: str) -> str:
    """Truncate text to Telegram's 4096-char limit."""
    if len(text) <= _MAX_MESSAGE_LEN:
        return text
    cut = _MAX_MESSAGE_LEN - len(_TRUNCATION_SUFFIX)
    if parse_mode == "HTML":
        return text[:cut] + _TRUNCATION_SUFFIX
    return text[:cut] + "\n\n(message truncated)"


def _escape_html(text: str) -> str:
    """Escape characters that have special meaning in Telegram HTML mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_retry_after(resp: requests.Response) -> float | None:
    """Parse Retry-After header from a 429 response."""
    try:
        return float(resp.headers.get("Retry-After", ""))
    except (ValueError, TypeError):
        return None


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
