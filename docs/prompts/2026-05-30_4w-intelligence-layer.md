# Prompt — 4W Intelligence Layer (WHAT / WHERE / WHEN / WHICH)

- **Date:** 2026-05-30
- **TASK_LOG:** #194
- **Commit:** 6eba5eb
- **Outcome:** 4W first-class on every finding (cognition/four_w.py, additive findings.four_w column); threaded through reports (§0/§3/§8), notifications, recommendations. Docs: docs/FOUR_W_INTELLIGENCE.md

---

## Verbatim prompt

Execute the next major phase:

4W INTELLIGENCE LAYER

Mission:

Make the system answer the four operational questions at every scan, notification, and report.

WHAT
WHERE
WHEN
WHICH

These answers become first-class operational data.

==================================================
OBJECTIVE
==================================================

For every meaningful activity:

- engineering activity
- agent activity
- LLM activity
- economic activity

the system must determine:

WHAT happened
WHERE it happened
WHEN it happened
WHICH resources were involved

==================================================
PHASE 1 — 4W MODEL
==================================================

Create canonical fields:

what
where
when
which

Requirements:

WHAT
- task
- workflow
- activity type

WHERE
- repository
- subsystem
- service
- component

WHEN
- start
- end
- duration
- first_seen
- last_seen

WHICH
- agent
- provider
- model
- workflow
- service

==================================================
PHASE 2 — LLM INTELLIGENCE
==================================================

For every LLM activity determine:

WHAT
- queue processing
- audit
- generation
- classification
- ingestion
- unknown

WHERE
- repo
- subsystem

WHEN
- execution window

WHICH
- model
- provider
- agent

==================================================
PHASE 3 — REPORT EVOLUTION
==================================================

Every report must begin with:

WHAT
WHERE
WHEN
WHICH

before:

- spend
- drift
- findings
- recommendations

==================================================
PHASE 4 — NOTIFICATIONS
==================================================

Every notification must contain:

WHAT
WHERE
WHEN
WHICH

Example:

🚨 Spend Spike

WHAT:
Drain queue

WHERE:
Lesia/backend/services

WHEN:
22:00–03:00 UTC

WHICH:
Gemini Pro
Claude Sonnet

Cost:
$67

==================================================
PHASE 5 — RECOMMENDATIONS
==================================================

Recommendations must derive from 4W.

Format:

Observed:
WHAT
WHERE
WHEN
WHICH

Evidence:
...

Recommendation:
...

Expected impact:
...

No recommendation without 4W context.

==================================================
VALIDATION
==================================================

Use real Lesia audit data.

Prove:

- 4W extracted
- reports show 4W
- notifications show 4W
- recommendations derive from 4W
- cost/day visible
- model/day visible
- agent/day visible

==================================================
OUTPUT
==================================================

Provide:

- modified files
- schema changes
- validation evidence
- example reports
- example notifications
- example recommendations
- operational impact
- rollback plan

Maintain:

- deterministic behavior
- explainability
- bounded architecture
- operational usefulness
