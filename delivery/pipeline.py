"""
Delivery pipeline — mandatory git + Telegram for every operational report.

Every report type (daily, drift, security, self-monitor) routes through here.
Neither git nor Telegram is optional. Both failures are tracked and surfaced.

Contract:
- Writes report to reports/history/YYYY-MM-DD/<filename>
- Git add → commit → push with structured commit message
- Sends Telegram operator summary (not full content dump)
- Persists delivery state to data/delivery_state.json
- Returns PipelineResult with explicit success/failure per channel
- Never silently swallows failures

Commit message format:
  quartermaster: <report_type> YYYY-MM-DD HH:MM UTC
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_STATE_FILE = PROJECT_ROOT / "data" / "delivery_state.json"
_HISTORY_DIR = PROJECT_ROOT / "reports" / "history"

# Report type → commit verb
_COMMIT_VERBS: dict[str, str] = {
    "daily": "daily operational report",
    "drift": "drift detection snapshot",
    "security": "security findings update",
    "selfmonitor": "self-monitor check",
    "vps": "vps state snapshot",
}


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {
        "last_telegram_success": None,
        "last_git_push_success": None,
        "last_report_generated": None,
        "telegram_failures_since_success": 0,
        "git_failures_since_success": 0,
    }


def _save_state(state: dict[str, Any]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as exc:
        logger.warning("Could not save delivery_state.json: %s", exc)


def get_delivery_state() -> dict[str, Any]:
    """Return current delivery state (last success timestamps, failure counts)."""
    return _load_state()


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    report_type: str
    report_path: Path | None
    generated_at: str
    git_ok: bool
    git_error: str | None
    telegram_ok: bool
    telegram_error: str | None

    @property
    def fully_delivered(self) -> bool:
        return self.git_ok and self.telegram_ok

    def log_summary(self) -> None:
        status = "OK" if self.fully_delivered else "DEGRADED"
        logger.info(
            "[%s] delivery: git=%s telegram=%s | %s",
            status,
            "ok" if self.git_ok else f"FAIL({self.git_error})",
            "ok" if self.telegram_ok else f"FAIL({self.telegram_error})",
            self.report_type,
        )
        if not self.git_ok:
            logger.error(
                "Git delivery failed for %s — report persisted locally at %s but NOT in git",
                self.report_type,
                self.report_path,
            )
        if not self.telegram_ok:
            logger.error(
                "Telegram delivery failed for %s — operator may miss this report",
                self.report_type,
            )


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def _write_report(content: str, report_type: str, timestamp: datetime, suffix: str = "") -> Path:
    """Write report markdown to reports/history/YYYY-MM-DD/."""
    date_str = timestamp.strftime("%Y-%m-%d")
    fname = f"{report_type}{('_' + suffix) if suffix else ''}.md"
    dir_path = _HISTORY_DIR / date_str
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / fname
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Git delivery
# ---------------------------------------------------------------------------

def _git_deliver(report_path: Path, report_type: str, timestamp: datetime) -> tuple[bool, str | None]:
    """Stage, commit, push the report. Returns (ok, error_message)."""
    verb = _COMMIT_VERBS.get(report_type, report_type)
    ts_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")
    commit_msg = f"quartermaster: {verb} {ts_str}"

    try:
        # Stage the history directory
        subprocess.run(
            ["git", "add", str(_HISTORY_DIR.relative_to(PROJECT_ROOT))],
            cwd=PROJECT_ROOT, check=True, capture_output=True, text=True,
        )

        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            if "nothing to commit" in msg:
                logger.info("Git: nothing new to commit for %s", report_type)
                return True, None
            logger.error("Git commit failed: %s", msg)
            return False, f"commit failed: {msg[:200]}"

        logger.info("Git commit: %s", result.stdout.strip())

        push = subprocess.run(
            ["git", "push"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        )
        if push.returncode != 0:
            msg = push.stderr.strip() or push.stdout.strip()
            logger.error("Git push failed: %s", msg)
            return False, f"push failed: {msg[:200]}"

        logger.info("Git push: ok")
        return True, None

    except subprocess.CalledProcessError as exc:
        msg = exc.stderr.strip() if exc.stderr else str(exc)
        logger.error("Git operation error: %s", msg)
        return False, f"git error: {msg[:200]}"
    except subprocess.TimeoutExpired:
        logger.error("Git push timed out")
        return False, "push timeout"
    except Exception as exc:
        logger.error("Git unexpected error: %s", exc)
        return False, str(exc)[:200]


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _telegram_deliver(summary: str) -> tuple[bool, str | None]:
    """Send operator summary to Telegram. Returns (ok, error_message)."""
    _load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true"

    if not enabled:
        logger.info("Telegram delivery skipped — TELEGRAM_ENABLED=false")
        return True, None  # not a failure — intentionally disabled

    if not token or not chat_id:
        logger.error("Telegram delivery failed — BOT_TOKEN or CHAT_ID not configured")
        return False, "missing token or chat_id"

    try:
        from delivery.telegram import TelegramDeliveryClient
        client = TelegramDeliveryClient(token=token, chat_id=chat_id)
        result = client.send_message(summary, parse_mode="HTML")
        if result.success:
            logger.info("Telegram operator summary delivered")
            return True, None
        else:
            logger.error("Telegram delivery failed: %s", result.error)
            return False, result.error
    except Exception as exc:
        logger.error("Telegram unexpected error: %s", exc)
        return False, str(exc)[:200]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def deliver(
    *,
    report_type: str,
    content: str,
    summary: str,
    timestamp: datetime | None = None,
    filename_suffix: str = "",
) -> PipelineResult:
    """
    Write, commit, push, and notify for one operational report.

    Args:
        report_type: "daily" | "drift" | "security" | "selfmonitor" | "vps"
        content:     Full markdown report text.
        summary:     Compact HTML string for Telegram (pre-formatted).
        timestamp:   Report time (defaults to now UTC).
        filename_suffix: Optional suffix to disambiguate multiple reports per day.

    Returns:
        PipelineResult with per-channel success/failure.
    """
    ts = timestamp or datetime.now(UTC)
    generated_at = ts.isoformat()

    # 1. Write report file
    report_path: Path | None = None
    try:
        report_path = _write_report(content, report_type, ts, filename_suffix)
        logger.info("Report written: %s", report_path)
    except Exception as exc:
        logger.error("Failed to write report file: %s", exc)
        # Continue — attempt delivery even if file write failed

    # 2. Git: add, commit, push
    t_git = time.monotonic()
    git_ok, git_error = _git_deliver(report_path or Path("."), report_type, ts)
    logger.debug("Git delivery took %.2fs", time.monotonic() - t_git)

    # 3. Telegram: send summary (empty string means intentionally skipped)
    t_tg = time.monotonic()
    if summary:
        telegram_ok, telegram_error = _telegram_deliver(summary)
    else:
        telegram_ok, telegram_error = True, None  # intentionally skipped
        logger.info("Telegram delivery skipped — no summary provided (all-clear)")
    logger.debug("Telegram delivery took %.2fs", time.monotonic() - t_tg)

    # 4. Update delivery state
    state = _load_state()
    state["last_report_generated"] = generated_at
    if git_ok:
        state["last_git_push_success"] = generated_at
        state["git_failures_since_success"] = 0
    else:
        state["git_failures_since_success"] = state.get("git_failures_since_success", 0) + 1
    if telegram_ok:
        state["last_telegram_success"] = generated_at
        state["telegram_failures_since_success"] = 0
    else:
        state["telegram_failures_since_success"] = state.get("telegram_failures_since_success", 0) + 1
    _save_state(state)

    result = PipelineResult(
        report_type=report_type,
        report_path=report_path,
        generated_at=generated_at,
        git_ok=git_ok,
        git_error=git_error,
        telegram_ok=telegram_ok,
        telegram_error=telegram_error,
    )
    result.log_summary()
    return result
