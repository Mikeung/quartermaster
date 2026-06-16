# Cost Accountability + 4W Intelligence Hotfix

Status: In Progress → Completed (see TASK_LOG.md)
Owner: Implementation engineer (Claude Code)
Date: 2026-05-30

---

## 1. Incident Summary

A real production failure occurred. The operator **observed Gemini spend
before the system could explain it**. The economic observability layer detected
that money was being spent (spend_spike / runaway_agent_cost fired), but the
findings, notifications and reports did not present, as first-class structured
data, the answer to the only question that matters at 3am:

> "Who spent this money, on what, where, when, with which model — and how much?"

The 4W intelligence layer (`cognition/four_w.py`) already answered
WHAT / WHERE / WHEN / WHICH. It did **not** carry:

- **WHO** — the accountable actor (agent / workflow owner / automation), and
- **COST** — spend / burn_rate / cumulative_cost as structured fields.

Cost lived only inside free-text titles and evidence strings. It could be read
by a human but not rolled up, gated on, or guaranteed present. That is the
defect.

## 2. Root Cause

1. **No WHO dimension.** The accountable actor was implicit (buried inside the
   WHICH `agent` field or the finding `target_id`), never surfaced as an
   answer to "who is responsible for this spend".
2. **No COST dimension.** Spend numbers were rendered into prose, not held as
   `spend` / `burn_rate` / `cumulative_cost`. Reports could not produce a
   "cost by agent / workflow / provider / model" header deterministically.
3. **Silent omission.** When attribution could not be determined, the gap was
   invisible — the operator saw a cost with no owner and no signal that the
   *system itself* could not explain it.

## 3. Scope

In scope (advisory-only, observational — no infrastructure mutation):

- A first-class accountability model: `who / what / where / when / which / cost`.
- Hotfix of every economic finding to carry the full model.
- A new `unknown_cost_owner` finding (HIGH) for un-attributable spend.
- Notification hotfix: every economic alert renders all six dimensions.
- Report hotfix: an accountability header answering the six questions.
- A recommendation gate: no economic recommendation without full
  accountability; otherwise an `insufficient_context` finding is emitted.
- Validation against the real Lesia Gemini spend incident.

Out of scope: changing spend, touching provider accounts, any autonomous action.

## 4. Architecture

```
llm_events store ──► observability/economic.py ──► findings (each carries 4w + who + cost)
                                │                         │
                                │                         ├─► cognition/cost_accountability.py
                                │                         │     - build_accountability(finding)
                                │                         │     - has_full_accountability()  [Phase 7 gate]
                                │                         │     - unknown_cost_owner_finding()
                                │                         │     - insufficient_context_finding()
                                │                         │
                                ├─► cognition/four_w.py   (WHO + COST are now first-class)
                                │     - make_4w(who=, cost=)
                                │     - make_who(), make_cost()
                                │     - four_w_pairs() renders WHO..COST
                                │
                                ├─► delivery/notifications.py  (all six in every economic alert)
                                └─► reports/economic_report.py (accountability header)
```

Determinism is preserved end-to-end: same spend in → same accountability out.
Nothing here is heuristic or probabilistic.

## 5. Data Model

Canonical accountability dict (extends the existing 4W):

```
{
  "who":   {"agent", "owner", "automation"},
  "what":  {"activity_type", "task", "workflow"},
  "where": {"repository", "subsystem", "service", "component"},
  "when":  {"start", "end", "duration", "first_seen", "last_seen"},
  "which": {"agent", "provider", "model", "workflow", "service"},
  "cost":  {"spend", "burn_rate", "cumulative_cost", "currency", "unknown_reason"},
}
```

- Unknown values are made **explicit** with the sentinel string `UNKNOWN`,
  never silently omitted. `cost.unknown_reason` carries the explanation.
- `who.owner` resolves from a configured owner map (project_id → owner); falls
  back to the agent name, then `UNKNOWN`.

## 6. Report Changes

`reports/economic_report.py::generate_economic_report(spend_summary, findings)`
emits, at the very top:

```
## Cost Accountability
- WHO spent money today?        (by agent/owner)
- WHAT was executed?            (activities)
- WHERE did it occur?           (repos/subsystems)
- WHEN did it run?              (earliest–latest span)
- WHICH models/providers?       (models, providers)
- COST by agent / workflow / provider / model
```

## 7. Notification Changes

Every economic notification renders WHO / WHAT / WHERE / WHEN / WHICH / COST.
On attribution failure it renders the `unknown_cost_owner` alert with COST and
an explicit reason. Implemented by making `four_w_pairs()` include WHO and COST
rows whenever populated; economic detectors always populate them.

## 8. Validation Plan

Replay the real Lesia P7 spend ledger (`data/spend/lesia_p7_audit.jsonl`,
Gemini 2.5 Flash, workflow `procurement_intel.drain_queue`, project `lesia`)
through the detectors and assert that WHO / WHAT / WHERE / WHEN / WHICH / COST
are all extracted and that the runaway/spike finding can be fully explained.
See `tests/test_cost_accountability.py`.

## 9. Rollback Plan

All changes are additive and behind deterministic code paths:

- `who` and `cost` are new optional sections; `make_4w()` defaults them, so any
  caller that ignores them is unaffected.
- `four_w_pairs()` only adds WHO/COST rows when populated — existing
  four-row rendering for non-economic findings is unchanged.
- To roll back: revert the hotfix commit. The previous 4W behaviour
  (WHAT/WHERE/WHEN/WHICH) is fully preserved; no schema migration occurred
  (findings persist their `four_w` blob as-is in the snapshot payload).
- New finding types (`unknown_cost_owner`, `insufficient_context`) can be
  neutralised by removing them from `NOTIFICATION_PRIORITY` (they then fall to
  P2 = daily report only) without code changes.

## 10. Risks

- Owner attribution depends on a configured map; unmapped projects surface as
  `UNKNOWN` owner (explicit, not silent) — acceptable and by design.
- Cost numbers remain estimates from ingested events, not authoritative billing.
  Reports continue to state this.
