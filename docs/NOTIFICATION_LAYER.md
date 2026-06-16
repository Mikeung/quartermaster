# Real-Time Operational Notification Layer (PRIORITY ZERO)

Status: implemented 2026-05-30. Advisory-only. Deterministic. Bounded.

Reduces operator awareness latency from **hours** (the 02:00 daily report) to
**minutes**. The daily report still exists for history/trends; this layer surfaces
important events the moment they are detected.

```
finding → classify (P0/P1/P2) → deduplicate (by finding_id) → Telegram
```

## Why it was needed

Real events already observed but surfaced too late by daily-only reporting:
$100 overnight API spend, major Lesia engineering activity, subsystem rebuilds.
These now page immediately.

## Two arms, shared dedup

| Arm | Cadence | Detects | Writes findings? | Git? |
|---|---|---|---|---|
| `scripts/notify.py` | **every 15 min** (cron) | economic/project/agent (read-only) + reads persisted survivability/security | no | no |
| `scheduled_scan.run_notifications` | every 6h (in scan) | all persisted findings (with occurrence_count) | n/a (already persisted) | no |

Both route through the same `delivery.notifications.NotificationPipeline` and share
`data/notification_state.json`, so a finding never double-fires. `notify.py` is
read-only by design: it computes the *same* deterministic `finding_id` the scan
persists, so it never inflates `occurrence_count` (recurrence semantics stay clean).

## Priorities (deterministic `finding_type` → priority, in config)

- **P0 — immediate, bypasses quiet hours:** spend_spike, economic_anomaly,
  runaway_agent_cost, abnormal_burn_rate, kernel_oom_kill, dependency_unreachable,
  port_exposed_publicly, deployment_event, subsystem_rebuild, engineering_burst,
  agent_cost, agent_burst.
- **P1 — batched digest, respects quiet hours:** repeated_service_restart,
  monitor_stale, agent_runtime, credential_in_unit_file, world_readable_env_file,
  stable_listener_disappeared, service_disappeared.
- **P2 — daily report only (never pushed):** project_activity, agent_activity,
  coverage_gap, **and every unmapped type** (push is an explicit allowlist).

The config priority is the *starting intent*; the push policy below is the authority.

## Push policy — silence over impact-free activity (`cognition/push_policy.py`)

A finding earns a push / P0 / incident **only** if it carries a real owner-facing
**consequence** OR is **intrinsically critical** (security, OOM/resource, money, a
declared dependency down). Everything else is silent — at most a quiet daily line.
The gate runs in the pipeline after dedup and is the single authority that prevents
impact-free P0 pushes. Evaluation order (deterministic, narrow suppression):

1. **Self dev/git activity** — the tool's own development on `quartermaster`
   (deploys, rebuilds, commit bursts about itself) is **never** an operational
   incident → suppressed (`self_activity`). Breaks the self-feedback loop. The tool's
   operational *health* (monitor_stale, scan failures) is a different finding type and
   still pushes.
2. **Intrinsically critical** (`INTRINSIC_CRITICAL_TYPES`: kernel_oom_kill, the three
   security types, dependency_unreachable, and the economic set) → always push. The
   policy can never suppress these — the hard line.
3. **Owner-facing consequence** — the consequence walk proved an owner-facing
   capability is lost → push (`owner_facing_consequence`).
4. **Pure activity/change** (`ACTIVITY_TYPES`: deployment_event, subsystem_rebuild,
   engineering_burst, agent_burst, agent_runtime, project_activity, agent_activity)
   with no owner-facing consequence → demoted (`no_consequence`): no push, no incident.
5. **Everything else** (service_disappeared, repeated_service_restart, …) is not gated
   — it keeps its existing classification.

**Severity coherence:** because medium-severity activity with no consequence is demoted
(not pushed), a "P0 · [MEDIUM]" push can no longer occur. Activity that *does* carry an
owner-facing consequence pushes with the consequence-escalated badge ([MEDIUM → HIGH]).

## Deduplication (storm prevention)

Keyed on the deterministic `finding_id` (preserves finding identity). A finding
is (re)sent only when:
- **new** — never notified before, or
- **escalated** — severity higher than last notification (bypasses cooldown), or
- **reactivated** — recurred after resolving (occurrence_count reset), or
- **cooldown_elapsed** — `NOTIFY_COOLDOWN_HOURS_{P0=12,P1=24}` since last alert.

These reason codes are **internal/audit only**. Internal dedup-timing artifacts
(`new`, `cooldown_elapsed`, `rate_capped`, `duplicate`) are **never user-facing** — the
Telegram alert and the incident report show only operationally meaningful triggers
(`escalated` → "severity escalated", `reactivated` → "returned after resolving"). The
headline / impact line already answers "why does this matter."

Otherwise suppressed as `duplicate`. Additional guards:
- **P0 rate cap** (`NOTIFY_MAX_P0_PER_RUN=6`): excess P0 collapse into one
  aggregate "+N more events" line; all are recorded so they don't re-fire.
- **P1 digest**: all P1 sends collapse into a single message.
- **Quiet hours** (22:00–08:00 UTC): P1 deferred; **P0 always sends**.

Audit trail: every decision is appended to `data/notification_log.jsonl`; sent
alerts also emit a `notified` event into `finding_events` (scan arm).

## Validation (real evidence, 2026-05-30)

Run against live findings with a capturing sender (no real Telegram):

- **$100 spend would have alerted** → P0 `spend_spike`, `runaway_agent_cost`
  ($100.21, drain_queue 100% / 15.3h), `abnormal_burn_rate` ($6.55/hr), `agent_cost` — **all fire even at 03:00** (quiet hours bypassed).
- **Lesia rebuild would have alerted** → P0 `subsystem_rebuild` (backend/services),
  `engineering_burst`, `agent_burst` (27 commits, author "Your Name").
- **Duplicates suppressed** → re-run 1h later: `sent=0`, all `duplicate`. No storm.
- **Latency reduced** → ≤15 min vs up to ~24h.

See `docs/examples/example_notifications.md` for the exact messages. Tests:
`tests/test_notifications.py` (incl. push-policy gate) and `tests/test_push_policy.py`.

## Operational impact

- New cron: `*/15 * * * * … scripts/notify.py` → `/var/log/ai-quartermaster-notify.log`.
  Each run: a few `git log` calls + idempotent spend import + SQLite reads (~seconds).
- No git commits from the notifier (avoids the push-race seen with report crons).
- Telegram volume is bounded by dedup + cooldown + rate cap.
- Primed on install (`notify.py --prime`) so the pre-existing backlog did **not**
  blast the operator — only genuinely new events alert from here on.

## Rollback

1. Remove the cron line: `crontab -e` → delete the `scripts/notify.py` line.
2. Remove the `run_notifications(finding_store)` call in `scripts/scheduled_scan.py`.
3. Optional: `rm data/notification_state.json data/notification_log.jsonl`.

No schema changes (the `notified` value is a new string in the existing
`finding_events.event_type` TEXT column). Findings, reports, and scans are
unaffected if the layer is removed.
