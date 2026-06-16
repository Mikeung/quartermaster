# Emergency Phase: COST ACCOUNTABILITY + 4W INTELLIGENCE HOTFIX

_Verbatim operator prompt, archived for traceability. TASK_LOG #196._

---

Execute Emergency Phase: COST ACCOUNTABILITY + 4W INTELLIGENCE HOTFIX

Use:

- PM Operating Rules
- MASTER_EXECUTION_PROMPT_TEMPLATE.md
- TASK_LOG.md
- DECISION_LOG.md

as mandatory governance.

## STEP 0 — GOVERNANCE (MANDATORY)

Before implementation:

1. Create `docs/COST_ACCOUNTABILITY_SPEC.md` documenting: incident summary, root
   cause, scope, architecture, data model, report changes, notification changes,
   validation plan, rollback plan.
2. Update TASK_LOG.md — Phase: Cost Accountability + 4W Hotfix; Status: In
   Progress; Reason: Production spend occurred without actionable attribution.
3. Update DECISION_LOG.md — Decision: Cost without ownership is a P0
   observability failure. Reason: the system detected spend but failed to answer
   WHO/WHAT/WHERE/WHEN/WHICH. Impact: all future economic findings,
   notifications, reports and recommendations must include attribution.

Commit governance changes first.

## MISSION

A real production failure occurred. The operator observed Gemini spend before
the system could explain it. Fix immediately. The system must answer WHO / WHAT
/ WHERE / WHEN / WHICH / COST for every paid LLM activity.

## PHASE 1 — COST ACCOUNTABILITY MODEL

First-class fields: who / what / where / when / which / cost.
WHO = agent / workflow owner / automation. WHAT = workflow / task / activity.
WHERE = repository / subsystem / service. WHEN = start / end / duration.
WHICH = model / provider. COST = spend / burn_rate / cumulative_cost.
Unknown values must remain explicit. Never silently omit.

## PHASE 2 — ECONOMIC FINDINGS HOTFIX

Update spend_spike / economic_anomaly / abnormal_burn_rate / runaway_agent_cost
/ agent_cost. Every finding must contain WHO/WHAT/WHERE/WHEN/WHICH/COST. If any
field cannot be determined, populate UNKNOWN and include reasoning.

## PHASE 3 — UNKNOWN COST OWNER

Create finding unknown_cost_owner, severity HIGH, trigger: spend exists but
ownership cannot be determined. The operator must never discover paid resource
consumption before the system can explain ownership.

## PHASE 4 — NOTIFICATION HOTFIX

Every economic notification must contain WHO/WHAT/WHERE/WHEN/WHICH/COST.
If attribution fails: UNKNOWN COST OWNER alert with COST and reason.

## PHASE 5 — REPORT HOTFIX

Add section at top of economic report: WHO spent money today? WHAT was executed?
WHERE? WHEN? WHICH models/providers? COST by agent/workflow/provider/model.

## PHASE 6 — 4W INTELLIGENCE VALIDATION

Use real Lesia spend data. Validate WHO/WHAT/WHERE/WHEN/WHICH/COST extraction.
Explicitly prove the Gemini spend incident can now be explained.

## PHASE 7 — RECOMMENDATION GATE

No economic recommendation unless WHO/WHAT/WHERE/WHEN/WHICH/COST are available.
Otherwise suppress recommendation and generate insufficient_context.

## COMPLETION REQUIREMENTS

Update TASK_LOG.md, DECISION_LOG.md, implementation status; commit; push. Output
modified/new files, schema changes, validation evidence, example notifications,
example reports, rollback plan, commit hash. Maintain deterministic behavior,
explainability, bounded architecture, operational usefulness.
