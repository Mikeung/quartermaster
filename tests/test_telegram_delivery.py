"""
Tests for delivery/telegram.py — Phase 14 Task 1.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from delivery.health import DeliveryHealthTracker
from delivery.telegram import (
    DeliveryResult,
    TelegramDeliveryClient,
    _escape_html,
    _truncate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(tracker: DeliveryHealthTracker | None = None) -> TelegramDeliveryClient:
    t = tracker or DeliveryHealthTracker()
    return TelegramDeliveryClient(token="fake_token", chat_id="123456", tracker=t)


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"ok":true}'
    return resp


def _error_response(status: int = 500, body: str = "Internal Error") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = {}
    return resp


# ---------------------------------------------------------------------------
# DeliveryResult
# ---------------------------------------------------------------------------

class TestDeliveryResult:
    def test_success_fields(self):
        r = DeliveryResult(success=True, status_code=200)
        assert r.success is True
        assert r.error is None

    def test_failure_fields(self):
        r = DeliveryResult(success=False, error="timeout", status_code=None)
        assert r.success is False
        assert r.error == "timeout"

    def test_to_dict(self):
        r = DeliveryResult(success=True, status_code=200, attempt_count=1)
        d = r.to_dict()
        assert d["success"] is True
        assert d["status_code"] == 200


# ---------------------------------------------------------------------------
# _escape_html
# ---------------------------------------------------------------------------

class TestEscapeHtml:
    def test_no_specials(self):
        assert _escape_html("hello world") == "hello world"

    def test_amp(self):
        assert _escape_html("a & b") == "a &amp; b"

    def test_lt_gt(self):
        assert _escape_html("<tag>") == "&lt;tag&gt;"

    def test_combined(self):
        assert _escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"

    def test_empty(self):
        assert _escape_html("") == ""


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_message_unchanged(self):
        text = "hello"
        assert _truncate(text, "HTML") == text

    def test_long_message_truncated(self):
        text = "x" * 5000
        result = _truncate(text, "HTML")
        assert len(result) <= 4096
        assert "truncated" in result

    def test_truncation_suffix_html(self):
        text = "x" * 5000
        result = _truncate(text, "HTML")
        assert "<i>" in result

    def test_truncation_suffix_plain(self):
        text = "x" * 5000
        result = _truncate(text, "")
        assert "truncated" in result
        assert "<i>" not in result

    def test_exact_limit_unchanged(self):
        text = "x" * 4096
        result = _truncate(text, "HTML")
        assert result == text


# ---------------------------------------------------------------------------
# TelegramDeliveryClient — send_message
# ---------------------------------------------------------------------------

class TestSendMessage:
    @patch("delivery.telegram.requests.post")
    def test_success_returns_true(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        result = client.send_message("test")
        assert result.success is True
        assert result.status_code == 200

    @patch("delivery.telegram.requests.post")
    def test_payload_has_chat_id(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_message("hello")
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
        assert payload["chat_id"] == "123456"

    @patch("delivery.telegram.requests.post")
    def test_failure_returns_false_no_raise(self, mock_post):
        mock_post.return_value = _error_response(500)
        client = _client()
        result = client.send_message("test")
        assert result.success is False

    @patch("delivery.telegram.requests.post")
    def test_token_not_in_result(self, mock_post):
        mock_post.return_value = _error_response(401, "Unauthorized")
        client = _client()
        result = client.send_message("test")
        assert "fake_token" not in (result.error or "")

    @patch("delivery.telegram.requests.post", side_effect=Exception("boom"))
    def test_exception_does_not_raise(self, _mock_post):
        client = _client()
        result = client.send_message("test")
        assert result.success is False
        assert result.error is not None

    @patch("delivery.telegram.requests.post")
    def test_records_success_in_tracker(self, mock_post):
        mock_post.return_value = _ok_response()
        tracker = DeliveryHealthTracker()
        client = _client(tracker)
        client.send_message("hi")
        summary = tracker.get_summary()
        assert summary.success_count == 1

    @patch("delivery.telegram.requests.post")
    def test_records_failure_in_tracker(self, mock_post):
        mock_post.return_value = _error_response(400)
        tracker = DeliveryHealthTracker()
        client = _client(tracker)
        client.send_message("hi")
        summary = tracker.get_summary()
        assert summary.failure_count == 1


# ---------------------------------------------------------------------------
# TelegramDeliveryClient — send_alert
# ---------------------------------------------------------------------------

class TestSendAlert:
    @patch("delivery.telegram.requests.post")
    def test_critical_alert_has_icon(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_alert("critical", "System down")
        payload = mock_post.call_args.kwargs["json"]
        assert "🚨" in payload["text"]

    @patch("delivery.telegram.requests.post")
    def test_warning_alert_has_icon(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_alert("warning", "Elevated storage")
        payload = mock_post.call_args.kwargs["json"]
        assert "⚠️" in payload["text"]

    @patch("delivery.telegram.requests.post")
    def test_alert_severity_in_text(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_alert("critical", "Test message")
        payload = mock_post.call_args.kwargs["json"]
        assert "CRITICAL" in payload["text"]


# ---------------------------------------------------------------------------
# TelegramDeliveryClient — send_markdown_report
# ---------------------------------------------------------------------------

class TestSendMarkdownReport:
    @patch("delivery.telegram.requests.post")
    def test_title_in_message(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_markdown_report("My Report", "Report body here")
        payload = mock_post.call_args.kwargs["json"]
        assert "My Report" in payload["text"]

    @patch("delivery.telegram.requests.post")
    def test_html_parse_mode(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_markdown_report("Title", "Body")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"

    @patch("delivery.telegram.requests.post")
    def test_long_report_truncated(self, mock_post):
        mock_post.return_value = _ok_response()
        client = _client()
        client.send_markdown_report("Title", "x" * 5000)
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["text"]) <= 4096


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestRetries:
    @patch("delivery.telegram.time.sleep")
    @patch("delivery.telegram.requests.post")
    def test_retries_on_500(self, mock_post, mock_sleep):
        mock_post.side_effect = [_error_response(500), _ok_response()]
        client = _client()
        result = client.send_message("test")
        assert result.success is True
        assert result.attempt_count == 2
        mock_sleep.assert_called_once()

    @patch("delivery.telegram.time.sleep")
    @patch("delivery.telegram.requests.post")
    def test_max_retries_then_failure(self, mock_post, mock_sleep):
        mock_post.return_value = _error_response(500)
        client = _client()
        result = client.send_message("test")
        assert result.success is False
        # 2 retries allowed — total 3 calls
        assert mock_post.call_count <= 3

    @patch("delivery.telegram.time.sleep")
    @patch("delivery.telegram.requests.post")
    def test_no_retry_on_401(self, mock_post, mock_sleep):
        mock_post.return_value = _error_response(401)
        client = _client()
        result = client.send_message("test")
        assert result.success is False
        # 4xx client error — should not retry
        assert mock_post.call_count == 1

    @patch("delivery.telegram.time.sleep")
    @patch("delivery.telegram.requests.post", side_effect=ConnectionError("refused"))
    def test_connection_error_retries(self, mock_post, mock_sleep):
        import requests as req
        mock_post.side_effect = req.exceptions.ConnectionError("refused")
        client = _client()
        result = client.send_message("test")
        assert result.success is False
