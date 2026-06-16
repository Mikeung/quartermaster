"""Real-time operational notification pipeline (PRIORITY ZERO).

    finding → classify (priority) → deduplicate (by finding_id) → Telegram

Reduces awareness latency from hours (the daily report) to minutes by alerting
the operator the moment an important finding is detected. Everything here is
deterministic and explainable:

- **Classification** is a fixed finding_type → P0/P1/P2 lookup (config).
- **Deduplication** is keyed on the deterministic finding_id, so the same
  finding never re-alerts within its cooldown; escalation/reactivation bypass
  cooldown. Finding identity and recurrence semantics are preserved.
- **Storm prevention**: per-run P0 rate cap with aggregation; P1 collapses into
  one digest; long cooldowns.
- **P0 bypasses quiet hours** (the motivating case is overnight $100 spend);
  P1 digests defer until quiet hours end.

Side effects are confined to: sending Telegram messages, writing the dedup state
file, appending to the audit log, and (optionally) emitting a 'notified'
finding_events row. It never mutates findings, repos, providers, or agents.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import observability_config as cfg

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SEV_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}
_PRIORITY_ICON = {"P0": "🚨", "P1": "⚠️", "P2": "ℹ️"}

# Sender contract: a callable taking the message text, returning True on success.
Sender = Callable[[str], bool]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(finding: dict[str, Any]) -> str:
    """Return the notification priority (P0/P1/P2) for a finding."""
    ftype = finding.get("finding_type", "")
    return cfg.NOTIFICATION_PRIORITY.get(ftype, cfg.NOTIFY_DEFAULT_PRIORITY)


def _sev_rank(sev: str | None) -> int:
    return _SEV_RANK.get((sev or "").upper(), 0)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    finding_id: str
    finding_type: str
    priority: str
    severity: str
    action: str          # "send" | "suppress"
    reason: str          # "new" | "escalated" | "reactivated" | "cooldown_elapsed"
                         # | "duplicate" | "quiet_hours_deferred" | "p2_daily_only" | "rate_capped"
                         # | "self_activity" | "no_consequence"  (push-policy demotions)
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id, "finding_type": self.finding_type,
            "priority": self.priority, "severity": self.severity,
            "action": self.action, "reason": self.reason,
        }


@dataclass
class NotificationResult:
    sent: list[Decision] = field(default_factory=list)
    suppressed: list[Decision] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)   # exact texts sent
    send_failures: int = 0
    incidents_committed: bool = False                    # incident reports pushed to git

    @property
    def p0_sent(self) -> int:
        return sum(1 for d in self.sent if d.priority == "P0")

    @property
    def p1_sent(self) -> int:
        return sum(1 for d in self.sent if d.priority == "P1")

    def summary(self) -> str:
        return (
            f"sent={len(self.sent)} (P0={self.p0_sent} P1={self.p1_sent}) "
            f"suppressed={len(self.suppressed)} failures={self.send_failures}"
        )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _evidence_line(finding: dict[str, Any]) -> str:
    ev = finding.get("evidence", []) or []
    shown = [e for e in ev if e][:2]
    return " · ".join(_escape(e) for e in shown)


def _compact_4w_lines(finding: dict[str, Any]) -> str:
    """Two most-urgent dimensions for the short alert.

    Economic events lead with WHO + COST; everything else with WHERE + WHEN.
    The full six-dimension picture lives in the committed incident report.
    """
    from cognition.four_w import four_w_pairs, get_4w

    pairs = dict(four_w_pairs(get_4w(finding)))
    if "COST" in pairs or "WHO" in pairs:
        wanted = ("WHO", "COST")
    else:
        wanted = ("WHERE", "WHEN")
    out = [f"<b>{label}:</b> {_escape(pairs[label])}"
           for label in wanted if pairs.get(label) and pairs[label] != "—"]
    return "\n".join(out)


# Reason codes that carry operational meaning worth surfacing to the operator.
# Internal dedup-timing artifacts ("cooldown_elapsed", "rate_capped", "new")
# are dropped when consequence framing already explains why this matters.
_MEANINGFUL_REASONS: dict[str, str] = {
    "escalated": "severity escalated",
    "reactivated": "returned after resolving",
}


def _effective_severity(base_sev: str, framing: dict | None) -> str:
    """Return consequence_severity when the framing escalated, else base severity."""
    if framing:
        return framing.get("consequence_severity") or base_sev
    return base_sev


def format_notification(
    finding: dict[str, Any],
    reason: str,
    report_path: str | None = None,
    *,
    consequence_framing: dict | None = None,
    check_steps: dict | None = None,
) -> str:
    """Short HTML alert — header, headline, consequence (if known), event details.

    Severity badge shows the consequence-adjusted severity when the walk escalated:
      No graph / no cascade:  [HIGH]           (finding-type severity, unchanged)
      Structural cascade:     [MEDIUM → HIGH]  (consequence raised the floor)
      Owner-facing loss:      [LOW → HIGH]     (same rule, higher signal)

    The reason line is shown ONLY for operationally meaningful reasons (escalated,
    reactivated), mapped to plain English. Internal dedup-timing artifacts
    (cooldown_elapsed, new, rate_capped, duplicate) are never user-facing — with or
    without framing. The headline / impact line already answers "why does this matter."
    """
    prio = classify(finding)
    icon = _PRIORITY_ICON.get(prio, "⚠️")
    ftype = finding.get("finding_type", "?").replace("_", " ").upper()
    sev = finding.get("severity", "")
    title = _escape(finding.get("title", finding.get("finding_type", "?")))

    # Build severity badge — show escalation when the walk raised the floor.
    if consequence_framing and consequence_framing.get("escalated"):
        base_sev = consequence_framing.get("base_severity", sev)
        eff_sev = consequence_framing.get("consequence_severity", sev)
        badge = f"{_escape(base_sev)} → {_escape(eff_sev)}"
    else:
        badge = _escape(sev) if sev else ""

    text = f"{icon} <b>{prio} · {_escape(ftype)}</b>"
    if badge:
        text += f" [{badge}]"
    text += f"\n{title}\n"

    # Graph-derived consequence: leads with owner-facing impact before event details.
    if consequence_framing:
        owner_lost = consequence_framing.get("owner_facing_lost", [])
        if owner_lost:
            item = owner_lost[0]  # most impactful (depth=0 first from walk)
            label = _escape(item["label"])
            c = item["consequence"]
            conf = item["confidence"]
            if c != "unknown":
                text += (
                    f"\n📍 <b>Impact:</b> {label} — "
                    f"{_escape(c)} <i>({conf})</i>"
                )
            else:
                text += (
                    f"\n📍 <b>Impact:</b> {label} goes dark "
                    f"<i>(consequence unknown)</i>"
                )
            if len(owner_lost) > 1:
                text += f" (+{len(owner_lost) - 1} more)"
            text += "\n"

    # 🔍 What to check — first diagnostic step, after the 📍 Impact block. Kept to
    # one line for the alert; the full checklist is in the committed incident report.
    if check_steps:
        steps = check_steps.get("steps", [])
        if steps:
            text += f"\n🔍 <b>What to check:</b> {_escape(steps[0]['check'])}"
            if len(steps) > 1:
                text += f" <i>(+{len(steps) - 1} more in report)</i>"
            text += "\n"

    compact = _compact_4w_lines(finding)
    if compact:
        text += f"\n{compact}\n"
    if report_path:
        text += f"\n📄 <b>Full report:</b> <code>{_escape(report_path)}</code>"

    # Reason line: only operationally meaningful reasons are EVER user-facing.
    # Internal dedup-timing artifacts (new, cooldown_elapsed, rate_capped, duplicate)
    # are never shown — unconditionally, with or without framing. The headline (and
    # the impact line when present) already answer "why does this matter"; a
    # "why: cooldown_elapsed" line is pure machinery leaking to the operator.
    display = _MEANINGFUL_REASONS.get(reason)
    if display:
        text += f"\n<i>{display}</i>"

    return text


def format_p0_aggregate(findings: list[dict[str, Any]]) -> str:
    """One line summarising P0 events that exceeded the per-run cap."""
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f.get("finding_type", "?")] = by_type.get(f.get("finding_type", "?"), 0) + 1
    parts = ", ".join(f"{_escape(t)}×{n}" for t, n in sorted(by_type.items()))
    return f"🚨 <b>P0 · +{len(findings)} MORE EVENTS</b>\n{parts}"


def format_p1_digest(
    findings: list[dict[str, Any]], paths: list[str | None] | None = None
) -> str:
    """Batched digest for P1 findings, each linking its committed incident report."""
    paths = paths or [None] * len(findings)
    lines = [f"⚠️ <b>P1 digest · {len(findings)} event(s)</b>"]
    shown = findings[: cfg.NOTIFY_P1_DIGEST_MAX]
    for f, rp in list(zip(findings, paths, strict=False))[: cfg.NOTIFY_P1_DIGEST_MAX]:
        sev = f.get("severity", "")
        title = _escape(f.get("title", f.get("finding_type", "?")))
        lines.append(f"• [{_escape(sev)}] {title}")
        if rp:
            lines.append(f"  📄 <code>{_escape(rp)}</code>")
    extra = len(findings) - len(shown)
    if extra > 0:
        lines.append(f"<i>(+{extra} more)</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Default Telegram sender (real)
# ---------------------------------------------------------------------------

def default_telegram_sender(text: str) -> bool:
    """Send via Telegram using env config. Returns True on success or when disabled."""
    _load_env()
    enabled = os.environ.get("TELEGRAM_ENABLED", "false").lower() == "true"
    if not enabled:
        logger.info("Notification skipped — TELEGRAM_ENABLED=false")
        return True
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.error("Notification failed — TELEGRAM token/chat_id not configured")
        return False
    try:
        from delivery.telegram import TelegramDeliveryClient
        client = TelegramDeliveryClient(token=token, chat_id=chat_id)
        return client.send_message(text, parse_mode="HTML").success
    except Exception as exc:
        logger.error("Notification send error: %s", type(exc).__name__)
        return False


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


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def _parse_hhmm(s: str) -> int | None:
    try:
        h, m = (int(p) for p in s.strip().split(":"))
        return h * 60 + m if 0 <= h <= 23 and 0 <= m <= 59 else None
    except (ValueError, AttributeError):
        return None


def is_quiet_hour(now: datetime) -> bool:
    if not cfg.NOTIFY_QUIET_HOURS_ENABLED:
        return False
    start = _parse_hhmm(cfg.NOTIFY_QUIET_HOURS_START)
    end = _parse_hhmm(cfg.NOTIFY_QUIET_HOURS_END)
    if start is None or end is None:
        return False
    cur = now.hour * 60 + now.minute
    return (start <= cur < end) if start < end else (cur >= start or cur < end)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class NotificationPipeline:
    """Classifies, deduplicates, and sends operational notifications.

    Dedup state persists across process runs (cron-safe) in a JSON file keyed by
    finding_id. An append-only JSONL audit log records every decision.
    """

    def __init__(
        self,
        *,
        send_fn: Sender | None = None,
        persist: bool = True,
        finding_store: Any = None,
        state_path: Path | None = None,
        log_path: Path | None = None,
        write_incidents: bool = True,
        git_sync: bool = False,
        incident_root: Path | None = None,
        graph_store: Any = None,
    ) -> None:
        self._send = send_fn or default_telegram_sender
        self._persist = persist
        self._finding_store = finding_store
        self._graph_store = graph_store
        data_dir = PROJECT_ROOT / "data"
        self._state_path = state_path or (data_dir / cfg.NOTIFY_STATE_FILE)
        self._log_path = log_path or (data_dir / cfg.NOTIFY_LOG_FILE)
        self._state = self._load_state()
        # Incident reports: P0/P1 sends produce a committed markdown report (the
        # system of record). The path is always computed (shown in the alert);
        # the file is written only on a persisted run, and committed/pushed only
        # when git_sync is explicitly enabled (off by default — production
        # callers opt in, so tests/dry-runs never touch git or the real repo).
        self._write_incidents = write_incidents
        self._git_sync = git_sync
        self._incident_root = incident_root
        self._written_incidents: list[str] = []

    # -- state --------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        try:
            if self._state_path.exists():
                return json.loads(self._state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_state(self) -> None:
        if not self._persist:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(self._state, indent=0, sort_keys=True))
        except OSError as exc:
            logger.warning("Could not save notification state: %s", exc)

    def _audit(self, decisions: list[Decision], now: datetime) -> None:
        if not self._persist:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a") as fh:
                for d in decisions:
                    rec = {"ts": now.isoformat(), **d.to_dict()}
                    fh.write(json.dumps(rec) + "\n")
        except OSError as exc:
            logger.warning("Could not append notification log: %s", exc)

    # -- identity -----------------------------------------------------------

    def _dedupe_inputs(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        out: list[dict[str, Any]] = []
        for f in findings:
            fid = self._finding_id(f)
            if not fid:
                out.append(f)
                continue
            if fid not in seen:
                seen[fid] = f
                out.append(f)
            elif _sev_rank(f.get("severity")) > _sev_rank(seen[fid].get("severity")):
                # replace the kept instance with the higher-severity one
                out[out.index(seen[fid])] = f
                seen[fid] = f
        return out

    @staticmethod
    def _finding_id(f: dict[str, Any]) -> str | None:
        if f.get("finding_id"):
            return f["finding_id"]
        # compute deterministically when identity fields are present
        if all(k in f for k in ("target_id", "finding_type", "resource", "scope", "collector_type")):
            from memory.finding_store import compute_finding_id
            return compute_finding_id(
                target_id=f["target_id"], finding_type=f["finding_type"],
                resource=f["resource"], scope=f["scope"], collector_type=f["collector_type"],
            )
        return None

    # -- decision -----------------------------------------------------------

    def _decide(self, f: dict[str, Any], now: datetime) -> Decision:
        fid = self._finding_id(f) or f"anon:{f.get('finding_type')}:{f.get('resource')}"
        prio = classify(f)
        sev = f.get("severity", "")
        base = {"finding_id": fid, "finding_type": f.get("finding_type", "?"),
                    "priority": prio, "severity": sev, "title": f.get("title", "")}

        if prio == "P2":
            return Decision(**base, action="suppress", reason="p2_daily_only")

        prev = self._state.get(fid)
        cooldown = cfg.NOTIFY_COOLDOWN_HOURS_P0 if prio == "P0" else cfg.NOTIFY_COOLDOWN_HOURS_P1

        if prev is None:
            return Decision(**base, action="send", reason="new")
        if _sev_rank(sev) > _sev_rank(prev.get("last_severity")):
            return Decision(**base, action="send", reason="escalated")
        # reactivation: occurrence reset to 1 after having recurred before
        occ = f.get("occurrence_count")
        if occ == 1 and prev.get("count", 1) > 1:
            return Decision(**base, action="send", reason="reactivated")
        if _hours_since(prev.get("last_notified_at"), now) >= cooldown:
            return Decision(**base, action="send", reason="cooldown_elapsed")
        return Decision(**base, action="suppress", reason="duplicate")

    # -- incident reports ---------------------------------------------------

    def _consequence_framing(self, f: dict[str, Any]) -> dict | None:
        """Get consequence framing for a finding, or None. Never raises."""
        if self._graph_store is None:
            return None
        try:
            from cognition.consequence_mapper import get_consequence_framing
            return get_consequence_framing(f, self._graph_store)
        except Exception as exc:
            logger.debug("consequence_framing error: %s", type(exc).__name__)
            return None

    def _check_steps(self, f: dict[str, Any]) -> dict | None:
        """Get the 'what to check' block for a finding, or None. Never raises."""
        if self._graph_store is None:
            return None
        try:
            from cognition.check_mapper import get_check_steps
            return get_check_steps(f, self._graph_store)
        except Exception as exc:
            logger.debug("check_steps error: %s", type(exc).__name__)
            return None

    def _incident_report(self, f: dict[str, Any], d: Decision, now: datetime) -> str | None:
        """Return the report's repo-relative path; write the file on a real run.

        The path is deterministic and pure (safe for dry-run/test). The file is
        written only when persisting; git commit/push happens once per run after
        all sends. P2 never reaches here.
        """
        if not self._write_incidents:
            return None
        from reports.incident_report import incident_relpath, write_incident_report

        relpath = incident_relpath(f, now)
        if not self._persist:
            return relpath  # show the path, write nothing (dry-run / test)
        events = None
        if self._finding_store is not None:
            fid = self._finding_id(f)
            if fid:
                try:
                    events = self._finding_store.get_finding_events(fid)
                except Exception as exc:
                    logger.debug("finding_events unavailable for %s: %s", fid, exc)
        try:
            write_incident_report(
                f, now=now, priority=d.priority, reason=d.reason,
                finding_events=events, root=self._incident_root,
                graph_store=self._graph_store,
            )
            self._written_incidents.append(relpath)
        except OSError as exc:
            logger.error("Could not write incident report %s: %s", relpath, exc)
        return relpath

    def _rebuild_index(self, now: datetime) -> None:
        """Regenerate index.md + open_incidents.md from the reports on disk.

        Runs on any persisted run that wrote incidents, independent of git_sync,
        so the local indexes always reflect the filed reports. The files live
        under reports/incidents/ and are staged by commit_and_push_incidents.
        """
        if not (self._persist and self._write_incidents and self._written_incidents):
            return
        try:
            from reports.incident_index import rebuild_index
            rebuild_index(root=self._incident_root, now=now)
        except Exception as exc:
            logger.error("Incident index rebuild failed: %s", type(exc).__name__)

    def _flush_incidents(self, now: datetime, result: NotificationResult) -> None:
        """Commit + push the incident reports written this run (system of record)."""
        if not (self._persist and self._git_sync and self._written_incidents):
            return
        from reports.incident_report import commit_and_push_incidents
        ok, err = commit_and_push_incidents(self._written_incidents, now=now, root=self._incident_root)
        result.incidents_committed = ok
        if not ok:
            logger.error("Incident reports written but not pushed: %s", err)

    # -- main ---------------------------------------------------------------

    def process(self, findings: list[dict[str, Any]], now: datetime | None = None) -> NotificationResult:
        now = now or datetime.now(UTC)
        result = NotificationResult()
        self._written_incidents = []

        # 0. Collapse duplicate finding_ids within this batch (callers may merge
        #    fresh + persisted sources). Keep the highest-severity instance so one
        #    finding is decided exactly once per run.
        findings = self._dedupe_inputs(findings)

        # 1. Decide for every finding, then apply the push policy gate.
        #    Framing is computed once per surviving finding and threaded through to
        #    both the gate and the P0 formatter (no second graph round-trip).
        from cognition.push_policy import evaluate as _evaluate_push

        p0_send: list[tuple[Decision, dict]] = []
        p1_send: list[tuple[Decision, dict]] = []
        framing_by_id: dict[str, dict | None] = {}
        for f in findings:
            d = self._decide(f, now)
            if d.action == "suppress":
                result.suppressed.append(d)
                continue

            # Push policy: a finding earns a push ONLY with an owner-facing
            # consequence OR intrinsic criticality (security/OOM/money/dependency).
            # Pure activity/change with no consequence — and the tool's own dev/git
            # activity — is silenced here (demoted to the daily report). This is the
            # single authority that prevents impact-free P0 pushes.
            framing = self._consequence_framing(f)
            verdict = _evaluate_push(f, framing)
            if verdict.suppressed:
                d.action = "suppress"
                d.reason = verdict.reason   # "self_activity" | "no_consequence"
                result.suppressed.append(d)
                continue
            framing_by_id[d.finding_id] = framing

            if d.priority == "P0":
                p0_send.append((d, f))
            elif d.priority == "P1":
                # P1 defers during quiet hours
                if is_quiet_hour(now):
                    d.action = "suppress"
                    d.reason = "quiet_hours_deferred"
                    result.suppressed.append(d)
                else:
                    p1_send.append((d, f))

        # 2. P0 — individual up to cap, sorted by effective (consequence-adjusted)
        #    severity, remainder aggregated. Framing was pre-computed in step 1.
        p0_with_framing: list[tuple[Decision, dict, dict | None]] = [
            (d, f, framing_by_id.get(d.finding_id)) for d, f in p0_send
        ]
        p0_with_framing.sort(key=lambda t: (
            -_sev_rank(_effective_severity(t[0].severity, t[2])),
            t[0].finding_type,
            t[0].finding_id,
        ))

        cap = cfg.NOTIFY_MAX_P0_PER_RUN
        for d, f, framing in p0_with_framing[:cap]:
            report_path = self._incident_report(f, d, now)
            if self._dispatch(
                format_notification(
                    f, d.reason, report_path,
                    consequence_framing=framing, check_steps=self._check_steps(f),
                ),
                d, now, result,
            ):
                pass
        overflow = p0_with_framing[cap:]
        if overflow:
            # Each overflow event still gets a committed report (the record must
            # exist); only the Telegram line is aggregated for storm prevention.
            for d, f, _fr in overflow:
                self._incident_report(f, d, now)
            agg_text = format_p0_aggregate([f for _, f, _ in overflow])
            ok = self._send_safe(agg_text, result)
            for d, f, _fr in overflow:
                d.reason = "rate_capped"
                if ok:
                    self._commit(d, f, now, result)
                else:
                    result.suppressed.append(d)

        # 3. P1 — single batched digest, each event linking its committed report.
        if p1_send:
            p1_paths = [self._incident_report(f, d, now) for d, f in p1_send]
            digest = format_p1_digest([f for _, f in p1_send], p1_paths)
            ok = self._send_safe(digest, result)
            for d, f in p1_send:
                if ok:
                    self._commit(d, f, now, result)
                else:
                    result.suppressed.append(d)

        # 4. Persist dedup state + audit trail; rebuild indexes; commit/push reports.
        self._save_state()
        self._audit(result.sent + result.suppressed, now)
        self._rebuild_index(now)
        self._flush_incidents(now, result)
        logger.info("Notifications: %s", result.summary())
        return result

    # -- send/record helpers ------------------------------------------------

    def _dispatch(self, text: str, d: Decision, now: datetime, result: NotificationResult) -> bool:
        ok = self._send_safe(text, result)
        if ok:
            self._commit(d, None, now, result)
        else:
            result.suppressed.append(Decision(
                finding_id=d.finding_id, finding_type=d.finding_type, priority=d.priority,
                severity=d.severity, action="suppress", reason="send_failed", title=d.title,
            ))
        return ok

    def _send_safe(self, text: str, result: NotificationResult) -> bool:
        """Send one message; record it and count failures. Single source for messages."""
        try:
            ok = bool(self._send(text))
        except Exception as exc:
            logger.error("Notification sender raised: %s", type(exc).__name__)
            ok = False
        if ok:
            result.messages.append(text)
        else:
            result.send_failures += 1
        return ok

    def _commit(self, d: Decision, text_or_finding, now: datetime, result: NotificationResult) -> None:
        """Record a successful send: dedup state, audit, optional finding_events."""
        self._state[d.finding_id] = {
            "last_notified_at": now.isoformat(),
            "last_severity": d.severity,
            "priority": d.priority,
            "title": d.title[:200],
            "count": (self._state.get(d.finding_id, {}).get("count", 0) + 1),
        }
        result.sent.append(d)
        if self._finding_store is not None and not str(d.finding_id).startswith("anon:"):
            try:
                self._finding_store.record_notification(
                    d.finding_id, f"{d.priority} {d.reason} sev={d.severity}"
                )
            except Exception as exc:
                logger.debug("record_notification skipped: %s", exc)

    def prime(self, findings: list[dict[str, Any]], now: datetime | None = None) -> int:
        """Mark current findings as already-notified WITHOUT sending.

        Used on first install so a backlog of pre-existing findings doesn't blast
        the operator — only genuinely new events alert afterwards.
        """
        now = now or datetime.now(UTC)
        primed = 0
        for f in findings:
            if classify(f) == "P2":
                continue
            fid = self._finding_id(f)
            if not fid:
                continue
            self._state[fid] = {
                "last_notified_at": now.isoformat(),
                "last_severity": f.get("severity", ""),
                "priority": classify(f),
                "title": f.get("title", "")[:200],
                "count": 1,
            }
            primed += 1
        self._save_state()
        logger.info("Notification state primed: %d findings marked as seen", primed)
        return primed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hours_since(iso_ts: str | None, now: datetime) -> float:
    if not iso_ts:
        return float("inf")
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        return (now - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return float("inf")
