# Incident Reporting Enforcement

Status: In Progress → Completed (see TASK_LOG.md)
Owner: Implementation engineer (Claude Code)
Date: 2026-05-30

---

## 1. Mission

Telegram is an **alert channel**. The git repository is the **system of record**.

Every P0 and P1 notification must produce a full markdown incident report,
committed and pushed to git. An alert without a report is incomplete. Telegram
becomes a short alert plus a path/link to the full report.

## 2. What changes

For every finding that the notification pipeline **sends** at priority P0 or P1:

1. A markdown incident report is written to
   `reports/incidents/YYYY-MM-DD/<incident_slug>.md`.
2. The report is committed and pushed (git is the record).
3. The Telegram alert is shortened and references the report path.

P2 findings (daily-report-only) do not generate incident reports — they are not
paged and are covered by the daily report.

## 3. Incident report format (fixed section order)

```
# Executive Summary
# WHAT
# WHERE
# WHEN
# WHICH
# WHO
# COST
# Evidence
# Timeline
# Impact
# Recommendations
# Open Questions
# Validation
```

All six accountability dimensions (WHAT/WHERE/WHEN/WHICH/WHO/COST) are sourced
deterministically from the finding's 4W blob via `cognition.four_w.get_4w()`.
Undeterminable values render as `UNKNOWN` (never blank) — consistent with the
Cost Accountability hotfix.

## 4. Telegram format

Before (full 4W inline):

```
🚨 P0 · RUNAWAY AGENT COST [HIGH]
Runaway cost: ... (full WHO/WHAT/WHERE/WHEN/WHICH/COST block)
```

After (short alert + report path):

```
🚨 P0 · RUNAWAY AGENT COST [HIGH]
Runaway cost: procurement_intel.drain_queue = $100.21 (100%) over 24h

WHO: lesia · Lesia
COST: $100.21 · burn $4.18/hr

📄 Full report: reports/incidents/2026-05-30/runaway_agent_cost__lesia.md
why: new
```

The compact alert keeps the two most operationally urgent dimensions inline
(WHO + COST for economic events; WHERE + WHEN for infrastructure events) and
defers the complete 6-dimension picture, evidence, timeline and recommendations
to the committed report.

## 5. Architecture

```
finding (P0/P1)
  │
  ├─ reports/incident_report.py
  │     incident_slug()            deterministic filename stem
  │     incident_relpath()         pure path (no I/O) — used in the alert
  │     generate_incident_report() the 13-section markdown
  │     write_incident_report()    writes the file (real runs only)
  │     commit_and_push_incidents() race-safe git add/commit/rebase/push
  │
  └─ delivery/notifications.py
        NotificationPipeline computes the path for every sent P0/P1, writes +
        git-syncs the report (when persist=True), and references the path in the
        short Telegram alert. Dry-run/test (persist=False) compute the path but
        write nothing.
```

Determinism: same finding + same day → same path and same report body (modulo
the generation timestamp line). No LLM, no probabilistic content.

## 6. Git discipline (supersedes part of the notify.py no-commit rule)

The 2026-05-30 decision "scripts/notify.py never git-commits" exists to protect
`occurrence_count` integrity and avoid report-cron push races. Incident-report
sync is compatible with both concerns and is therefore now permitted from
notify.py:

- It stages **only** `reports/incidents/` — never the findings DB, scan state,
  or `notification_state.json`. `occurrence_count` is untouched.
- Each incident file has a unique per-incident-per-day path, so concurrent
  writers never conflict on content. The push uses `git pull --rebase
  --autostash` first to absorb interleaved report-cron commits.
- All git operations are best-effort: failure is logged, never raised, and the
  next run re-pushes any unpushed commit (`git add` + push are idempotent).

## 7. Validation plan

Replay three representative incidents through the pipeline and assert the full
chain (report created → committed → pushed → Telegram references it):

- **Gemini spend** (economic, P0): `runaway_agent_cost` from the real Lesia P7
  ledger.
- **OOM** (infrastructure, P0): `kernel_oom_kill`.
- **Subsystem rebuild** (engineering, P0): `subsystem_rebuild`.

See `tests/test_incident_reports.py` and `scripts/replay_incidents.py`.

## 8. Rollback plan

- Additive: a new module + an optional, off-by-default-in-tests write/sync step
  in the pipeline. The previous full-4W Telegram format is preserved as the
  report body; only the alert text was shortened.
- To roll back: revert the hotfix commit. Incident files already in git remain
  as historical record (append-only); no schema or data migration occurred.
- To neutralise without reverting: construct `NotificationPipeline(...,
  write_incidents=False)` — the pipeline then behaves exactly as before.

## 9. Risks

- Git push from the 15-min notify cron can transiently fail (network / race);
  handled by rebase-autostash + best-effort retry on the next run. Worst case is
  a short delay before a report appears on GitHub, not a lost report (the file is
  written locally first and committed on the next pass).
- Incident files accumulate over time; they are small markdown and live under a
  dated directory, so retention/pruning can be added later if needed (out of
  scope here).
