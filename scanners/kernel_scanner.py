"""
Kernel event scanner.

Ingests journalctl -k output and parses:
  - OOM kills (Out of memory: Killed process, cgroup oom-kill)
  - Segfaults
  - IO errors (block device, filesystem)
  - Kernel errors (BUG:, panic, WARN: with stack trace)

Stateful: tracks last ingestion time via kernel_scan_state.json to avoid
re-ingesting events already processed in a previous scan cycle.

[UFW BLOCK] firewall log lines are explicitly excluded — they are not
kernel errors and generate extreme noise in the journal.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK_HOURS = 26  # fallback when no prior state exists
_OOM_CRITICAL_THRESHOLD = 3   # occurrence_count in FindingStore before CRITICAL

# ─── OOM patterns (most specific first) ──────────────────────────────────────

# Final kill confirmation: "Out of memory: Killed process PID (name)"
_P_OOM_KILLED = re.compile(
    r"Out of memory: Killed process (\d+) \(([^)]+)\)"
)
# Older format: "Out of memory: Kill process PID (name) score N"
_P_OOM_KILL = re.compile(
    r"Out of memory: Kill process (\d+) \(([^)]+)\).*?score"
)
# cgroup v1/v2: "oom-kill:constraint=...,task=NAME,pid=PID,..."
_P_OOM_CGROUP = re.compile(
    r"oom-kill:constraint=\S+.*?task=([^,]+),pid=(\d+)"
)
# Memory cgroup: "Memory cgroup out of memory: Kill process PID (name)"
_P_OOM_MEMCG = re.compile(
    r"Memory cgroup out of memory: Kill process (\d+) \(([^)]+)\)"
)
# OOM invoker (NOT the victim — record as context only)
_P_OOM_INVOKER = re.compile(r"^(\S+) invoked oom-killer:")
# RSS from OOM kill detail line
_P_OOM_ANON_RSS = re.compile(r"anon-rss:(\d+)kB")

# ─── Other event patterns ────────────────────────────────────────────────────

_P_SEGFAULT = re.compile(r"([a-zA-Z0-9_./-]+)\[(\d+)\]: segfault at")

_IO_PATTERNS = [
    re.compile(r"blk_update_request: I/O error", re.IGNORECASE),
    re.compile(r"end_request: I/O error", re.IGNORECASE),
    re.compile(r"Buffer I/O error on dev", re.IGNORECASE),
    re.compile(r"SCSI error.*result="),
    re.compile(r"EXT4-fs error"),
    re.compile(r"XFS.*I/O error"),
]

_KERNEL_ERROR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Kernel panic"), "panic"),
    (re.compile(r"\bBUG: "), "bug"),
    (re.compile(r"Oops:.*\bkernel\b"), "oops"),
    (re.compile(r"ACPI Error:"), "acpi_error"),
]

# Lines to unconditionally skip — not errors, just informational kernel output
_SKIP_PATTERNS = [
    re.compile(r"\[UFW BLOCK\]"),
    re.compile(r"\[UFW AUDIT\]"),
    re.compile(r"\[UFW ALLOW\]"),
    # OOM table header / stack frame lines — parsed in context, not as events
    re.compile(r"^\S.*kernel:.*\[  pid  \].*uid"),
    re.compile(r"^\S.*kernel:\s+\[\s*\d+\]"),  # pid table rows
    re.compile(r"^\S.*kernel:\s+oom_kill_process\+"),  # stack frames
    re.compile(r"^\S.*kernel:\s+\?? oom_"),
    re.compile(r"^\S.*kernel:\s+__alloc_pages"),
]


# ─── journalctl runner ───────────────────────────────────────────────────────

def _run_journalctl(since: str, until: str) -> str:
    try:
        result = subprocess.run(
            ["journalctl", "-k",
             f"--since={since}", f"--until={until}",
             "--no-pager", "--output=short-iso"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout or ""
    except Exception as exc:
        logger.warning("journalctl -k failed: %s", exc)
        return ""


# ─── Parser ─────────────────────────────────────────────────────────────────

def _extract_ts(line: str) -> str | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4})", line)
    return m.group(1) if m else None


def _parse_events(raw: str) -> dict[str, list[dict[str, Any]]]:
    oom_kills: list[dict[str, Any]] = []
    segfaults: list[dict[str, Any]] = []
    io_errors: list[dict[str, Any]] = []
    kernel_errors: list[dict[str, Any]] = []

    # Track OOM context: the line that said "X invoked oom-killer" gives invoker.
    # The actual killed process appears in subsequent lines.
    # Use a set to deduplicate by (process_name, pid) within this scan window.
    seen_oom: set[tuple[str, int]] = set()
    seen_segfault: set[tuple[str, int]] = set()

    for line in raw.splitlines():
        ts = _extract_ts(line)

        # Skip noisy / structural lines
        if any(p.search(line) for p in _SKIP_PATTERNS):
            continue

        # ── OOM kill (killed process — the victim) ─────────────────────────
        oom_match: re.Match | None = None
        pid_raw: str = ""
        name_raw: str = ""

        for pat in (_P_OOM_KILLED, _P_OOM_KILL, _P_OOM_MEMCG):
            m = pat.search(line)
            if m:
                pid_raw, name_raw = m.group(1), m.group(2)
                oom_match = m
                break

        if oom_match is None:
            m = _P_OOM_CGROUP.search(line)
            if m:
                name_raw, pid_raw = m.group(1), m.group(2)
                oom_match = m

        if oom_match:
            try:
                pid = int(pid_raw)
            except (ValueError, TypeError):
                pid = 0
            proc = name_raw.strip()
            key = (proc, pid)
            if key not in seen_oom:
                seen_oom.add(key)
                rss_m = _P_OOM_ANON_RSS.search(line)
                oom_kills.append({
                    "process_name": proc,
                    "pid": pid,
                    "memory_rss_kb": int(rss_m.group(1)) if rss_m else None,
                    "timestamp": ts,
                    "raw": line.strip()[:300],
                })
            continue

        # ── Segfault ───────────────────────────────────────────────────────
        m = _P_SEGFAULT.search(line)
        if m:
            proc = m.group(1).split("/")[-1]
            try:
                pid = int(m.group(2))
            except ValueError:
                pid = 0
            key = (proc, pid)
            if key not in seen_segfault:
                seen_segfault.add(key)
                segfaults.append({
                    "process_name": proc,
                    "pid": pid,
                    "timestamp": ts,
                    "raw": line.strip()[:300],
                })
            continue

        # ── IO errors ──────────────────────────────────────────────────────
        for pat in _IO_PATTERNS:
            if pat.search(line):
                io_errors.append({"timestamp": ts, "raw": line.strip()[:300]})
                break
        else:
            # ── Kernel errors ──────────────────────────────────────────────
            for pat, kind in _KERNEL_ERROR_PATTERNS:
                if pat.search(line):
                    kernel_errors.append({
                        "kind": kind,
                        "timestamp": ts,
                        "raw": line.strip()[:300],
                    })
                    break

    return {
        "oom_kills": oom_kills,
        "segfaults": segfaults,
        "io_errors": io_errors,
        "kernel_errors": kernel_errors,
    }


# ─── State management ────────────────────────────────────────────────────────

def _load_state(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:
        logger.warning("Cannot read kernel_scan_state: %s", exc)
    return {}


def _save_state(path: Path, last_scan_time: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_scan_time": last_scan_time}, indent=2))
    except Exception as exc:
        logger.warning("Cannot write kernel_scan_state: %s", exc)


# ─── Public API ─────────────────────────────────────────────────────────────

def scan_kernel_events(
    state_path: Path | str | None = None,
    max_lookback_hours: int = _DEFAULT_LOOKBACK_HOURS,
) -> dict[str, Any]:
    """Ingest kernel events since the last successful scan.

    Reads last_scan_time from state_path to define the lookback window.
    Falls back to max_lookback_hours if no state exists (first run).
    Updates state_path after successful ingestion.

    Returns dict with keys: oom_kills, segfaults, io_errors, kernel_errors,
    total_events, scan_window.
    """
    now = datetime.now(UTC)

    _state_path = Path(state_path) if state_path else None
    state = _load_state(_state_path) if _state_path else {}

    last_raw = state.get("last_scan_time")
    if last_raw:
        try:
            since_dt = datetime.fromisoformat(last_raw)
            logger.info("Kernel scan: since %s", since_dt.isoformat())
        except Exception:
            since_dt = now - timedelta(hours=max_lookback_hours)
            logger.warning("Kernel scan: invalid state timestamp, falling back to %dh", max_lookback_hours)
    else:
        since_dt = now - timedelta(hours=max_lookback_hours)
        logger.info("Kernel scan: no prior state, scanning last %dh", max_lookback_hours)

    # journalctl --since format: "YYYY-MM-DD HH:MM:SS UTC"
    since_str = since_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    until_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    raw = _run_journalctl(since=since_str, until=until_str)
    events = _parse_events(raw)
    total = sum(len(v) for v in events.values())

    logger.info(
        "Kernel scan complete: %d OOM kills, %d segfaults, %d IO errors, %d kernel errors",
        len(events["oom_kills"]),
        len(events["segfaults"]),
        len(events["io_errors"]),
        len(events["kernel_errors"]),
    )

    if _state_path:
        _save_state(_state_path, now.isoformat())

    return {
        "oom_kills": events["oom_kills"],
        "segfaults": events["segfaults"],
        "io_errors": events["io_errors"],
        "kernel_errors": events["kernel_errors"],
        "total_events": total,
        "scan_window": {"since": since_str, "until": until_str},
    }
