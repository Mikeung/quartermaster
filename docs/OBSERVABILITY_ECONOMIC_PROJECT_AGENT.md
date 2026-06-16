# Economic + Project + Agent Observability

Status: implemented 2026-05-30. Advisory-only. Deterministic. Evidence-based.

Closes two production-proven blind spots — **economic activity** and
**engineering/agent activity** — so the daily report answers:

> What changed? · Who changed it? · How much did it cost? · Which agent caused
> it? · Was the activity expected? · Was the spend expected? · Was the
> engineering effort significant?

This layer **observes only**. It never starts/stops an agent, throttles spend,
touches a provider account, or modifies any scanned repository.

---

## Architecture (reuses existing primitives)

```
                 collect (read-only)        analyze (deterministic)      persist            surface
Phase B  scanners/git_activity_scanner ─▶ cognition/project_activity ─┐
Phase A  data/spend/*.jsonl ─▶ import ──▶ observability/economic     ─┼▶ FindingStore ─▶ scripts/daily_report
Phase C  git authorship + spend ───────▶ observability/agent_activity ┘   (findings)      (§3 Economic,
                                                                          + snapshots      §4 Project,
                                                                          (history)        §5 Agent)
```

- **No new database.** Findings use the existing `findings`/`finding_events`
  tables (12 new finding types registered in `memory/finding_store.py`). Spend
  uses the existing `llm_events` table. State history uses `snapshots`
  (`project_activity_state`, `economic_state`). All thresholds live in one file:
  `config/observability_config.py`.
- **One wiring point:** `scripts/scheduled_scan.run_activity_observability()`,
  invoked each scan cycle (every 6h) after the VPS snapshot.

---

## Phase A — Economic

Source: `llm_events.estimated_cost` (USD). Detection (all constants documented in
config):

| Finding | Fires when |
|---|---|
| `spend_spike` | window spend ≥ `DAILY_SPEND_WARN_USD`, or ≥ `SPEND_SPIKE_FACTOR`× trailing median day |
| `abnormal_burn_rate` | USD/active-hour ≥ `BURN_RATE_WARN_USD_PER_HR` (HIGH ≥ `BURN_RATE_HIGH_USD_PER_HR`) |
| `runaway_agent_cost` | one workflow ≥ `RUNAWAY_MIN_USD`, ≥ `RUNAWAY_SINGLE_WORKFLOW_SHARE` of spend, sustained ≥ `RUNAWAY_MIN_HOURS` |
| `economic_anomaly` | a provider absent from the baseline starts spending; or first-ever baseline |

Providers supported: **Claude (anthropic), Gemini/Google, OpenAI**.

### Spend-ledger contract (observe-only)

quartermaster **reads** spend records that producers drop into `data/spend/*.jsonl`
(one JSON object per line). It never writes back into producer projects. The
importer (`scripts/import_spend.py`) is **idempotent** — every line is hashed and
recorded in `data/spend_import_state.json`, so re-runs never double-count.

```json
{"timestamp":"2026-05-29T10:00:00+00:00","provider":"anthropic","model":"claude-sonnet-4-20250514",
 "workflow":"procurement_intel.drain_queue","project_id":"lesia","estimated_cost":6.55,
 "calls":126,"success":true,"source":"PM/P7-COST-AUDIT-RESULTS.md"}
```

Required: `timestamp`, `estimated_cost`. Recommended: `provider`, `project_id`,
`workflow`, `source` (provenance). See `docs/examples/lesia_p7_audit.jsonl`.

> **Data-source note (see DECISION_LOG 2026-05-30):** no project currently emits
> a live structured cost feed. Until one does, economic observability runs on
> imported ledgers (e.g. periodic cost audits). Imported records carry their
> `source` file in metadata so provenance is always visible. This keeps the
> system observe-only and avoids instrumenting other repos.

---

## Phase B — Project (git-based)

Source: `git log` over `WINDOW_HOURS` per scan target. Pure facts → findings:

| Finding | Fires when |
|---|---|
| `project_activity` | ≥ `PROJECT_ACTIVITY_MIN_COMMITS` commits (informational summary) |
| `engineering_burst` | commits ≥ `ENGINEERING_BURST_COMMITS` or files ≥ `ENGINEERING_BURST_FILES` |
| `subsystem_rebuild` | one subsystem ≥ `SUBSYSTEM_REBUILD_FILE_SHARE` of changed files (≥ min) |
| `deployment_event` | a commit touches deploy infra (`deploy*`, Dockerfile, CI…) or says release |

Evidence on every finding: raw commit/file counts, +/- lines, authors, and the
commit shortlog.

---

## Phase C — Agent

An *agent* is a non-interactive actor (AI coding agent, bot, scheduled job).
Two deterministic signals are fused per agent (= repo/project name):

- **git authorship** — author identity or commit message matches a configured
  pattern (`AGENT_AUTHOR_PATTERNS` / `AGENT_MESSAGE_PATTERNS`); the matched
  pattern is the evidence.
- **spend attribution** — per-project spend from `llm_events`.

| Finding | Fires when |
|---|---|
| `agent_activity` | agent produced ≥1 commit or any spend (summary) |
| `agent_burst` | agent commits ≥ `AGENT_BURST_COMMITS` |
| `agent_cost` | attributed spend ≥ `AGENT_COST_NOTABLE_USD` |
| `agent_runtime` | continuous activity span ≥ `AGENT_RUNTIME_NOTABLE_HOURS` |

---

## Validation (real evidence, 2026-05-30)

Run against live repos + the imported real Lesia P7 cost audit:

- **Lesia rebuild appears** → `subsystem_rebuild: backend/services (28 of 52 files)`, `engineering_burst: 27 commits`
- **Recent commits appear** → `project_activity` for lesia (27c/52f) and quartermaster (15c/16f)
- **API spend appears** → `$100.21` (google $69.70 / anthropic $30.50 / openai $0.01)
- **Economic anomaly appears** → `runaway_agent_cost` (drain_queue 100% over 15.3h), `abnormal_burn_rate` ($6.55/hr), `spend_spike`, two new-spender `economic_anomaly`
- **Reports surface all** → daily report §3/§4/§5 (see `docs/EXAMPLE_DAILY_REPORT_observability.md`)

---

## Operational impact

- Scan cycle does one extra pass: N `git log` calls (bounded, ~20s timeout each)
  + spend import + a few SQLite aggregates. Negligible on this VPS.
- Daily report gains 3 sections. Telegram summary unchanged.
- Storage: findings + 2 snapshot types per cycle (subject to existing retention).

## Rollback

Fully reversible, no destructive migration:

1. Remove the `run_activity_observability(...)` call in `scripts/scheduled_scan.py`
   (one line) → collection stops; everything else keeps working.
2. Remove the 3 new sections in `scripts/daily_report.py` → report reverts.
3. Optional: `DELETE FROM llm_events WHERE metadata LIKE '%P7-COST-AUDIT%'` to
   drop imported audit rows; delete `data/spend/` and `data/spend_import_state.json`.
4. New finding types are additive map entries — harmless to leave; existing
   findings auto-resolve on the next cycle once collection stops.

No schema was dropped or altered destructively; `llm_events` and the new snapshot
types are created with `CREATE TABLE IF NOT EXISTS` / additive inserts.
