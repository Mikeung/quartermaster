# 4W Intelligence Layer (WHAT / WHERE / WHEN / WHICH)

Status: implemented 2026-05-30. Deterministic. Explainable. Bounded.

Every meaningful activity now answers four operational questions as **first-class,
stored data**, threaded through findings → reports → notifications → recommendations:

| | answers |
|---|---|
| **WHAT** | task · workflow · activity type |
| **WHERE** | repository · subsystem · service · component |
| **WHEN** | start · end · duration · first_seen · last_seen |
| **WHICH** | agent · provider · model · workflow · service |

## Architecture

`cognition/four_w.py` is the single source of truth:
- `make_4w(...)` — canonical, fully-keyed structure.
- `classify_llm_activity(workflow)` — deterministic WHAT for LLM work
  (queue processing / audit / ingestion / classification / generation / unknown).
- `build_4w(finding)` — deterministic fallback derivation from a finding's identity.
- `get_4w(finding)` — prefer the detector-attached 4W, else derive.
- `render_4w_markdown` / `render_4w_telegram` / `four_w_pairs` — rendering.
- `summarize_4w(findings)` — roll-up for the report header.
- `format_recommendation_markdown(finding)` — Observed(4W)/Evidence/Recommendation/Impact.

**Detectors attach rich 4W** (they hold the raw provider/model/window/cost data):
`observability/economic.py`, `observability/agent_activity.py`,
`cognition/project_activity.py`. Findings without one (survivability, security,
drift) get a deterministic derived 4W at render time. No heuristics — same finding
in, same 4W out.

## Storage (schema change)

One additive column, matching the existing `ALTER TABLE ADD COLUMN` pattern:

```
findings.four_w TEXT NOT NULL DEFAULT '{}'   -- JSON-serialised 4W
```

`FindingStore.upsert(..., four_w=...)` stores it; `get_active_findings()`
deserialises it. Backward compatible: pre-existing rows default to `'{}'` and
derive their 4W at render. No other schema changes.

`llm_store` gained read-only aggregates for the report's cost/model/agent-per-day:
`aggregate_cost_by_model`, `aggregate_daily_by_model`, `aggregate_daily_by_agent`.

## Where 4W appears

- **Reports** (`scripts/daily_report.py`): a new `## 0. Operational Snapshot (4W)`
  leads every report (before drift/risks/spend); `## 3. Economic Activity` shows
  **cost/day, by model, agent/day**; `## 8. Recommendations` is fully 4W-derived.
- **Notifications** (`delivery/notifications.py`): every alert renders the
  WHAT/WHERE/WHEN/WHICH block under the headline.
- **Recommendations**: Observed (4W) → Evidence → Recommendation → Expected impact.
  No recommendation is emitted without 4W context.

## Validation (real Lesia audit data, 2026-05-30)

- **4W extracted** — runaway finding: WHAT `queue processing (procurement_intel.drain_queue)`,
  WHERE `lesia/procurement_intel`, WHEN `2026-05-29 09:46–2026-05-30 01:04 (15.3h)`,
  WHICH `lesia · gemini-2.5-flash+grounding, claude-sonnet-4 · anthropic, google, openai`.
- **Reports show 4W** — see `docs/examples/EXAMPLE_REPORT_4w.md` (§0 + §3).
- **Notifications show 4W** — `docs/examples/EXAMPLE_NOTIFICATIONS_4w.md`.
- **Recommendations derive from 4W** — `docs/examples/EXAMPLE_RECOMMENDATIONS_4w.md`.
- **cost/day** `2026-05-29 $87.69 · 2026-05-30 $12.53`; **model/day** gemini $69.70 /
  claude $30.50 / gpt-4o-mini $0.01; **agent/day** `lesia` per day.

Tests: `tests/test_four_w.py` (17). Full suite 1584 passed.

## Operational impact

- Detection cost unchanged (4W built from data already gathered).
- Findings table grows by one JSON column (small).
- Reports/notifications are slightly longer but far more actionable.

## Rollback

1. Stop rendering: revert the §0 / §3 / §8 edits in `scripts/daily_report.py` and
   the 4W block in `delivery/notifications.py:format_notification`.
2. Detectors can keep attaching `four_w` harmlessly, or revert the analyzer edits.
3. The `four_w` column is additive — leave it (ignored) or
   `ALTER TABLE findings DROP COLUMN four_w` (SQLite ≥ 3.35). No data migration.
