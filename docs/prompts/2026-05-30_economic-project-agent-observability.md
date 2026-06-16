# Prompt — Economic + Project + Agent Observability

- **Date:** 2026-05-30
- **TASK_LOG:** #192
- **Commit:** 658714e
- **Outcome:** Phases A/B/C shipped — economic (spend/burn/runaway), project (git activity/burst/rebuild/deploy), agent (activity/cost/burst/runtime). Docs: docs/OBSERVABILITY_ECONOMIC_PROJECT_AGENT.md

---

## Verbatim prompt

Execute the next major phase:

ECONOMIC + PROJECT + AGENT OBSERVABILITY

Mission:

Close the two production-proven blind spots:

1. Economic activity
2. Engineering/project activity

The system must be able to answer:

- What changed?
- Who changed it?
- How much did it cost?
- Which agent caused it?
- Was the activity expected?
- Was the spend expected?
- Was the engineering effort significant?

==================================================
PHASE A — ECONOMIC OBSERVABILITY
==================================================

Implement:

- spend tracking
- model usage tracking
- token usage tracking
- API usage tracking
- burn-rate tracking

Support:

- Claude
- Gemini
- OpenAI

Create finding types:

- economic_anomaly
- spend_spike
- abnormal_burn_rate
- runaway_agent_cost

Requirements:

- deterministic
- explainable
- evidence-based

==================================================
PHASE B — PROJECT ACTIVITY OBSERVABILITY
==================================================

Detect:

- commits
- deployments
- file changes
- subsystem rebuilds
- engineering bursts

Create finding types:

- project_activity
- deployment_event
- engineering_burst
- subsystem_rebuild

Examples:

"34 files modified across 12 commits"

"Major engineering activity detected"

"SEO subsystem rebuilt"

Requirements:

- git-based
- deterministic
- evidence-linked

==================================================
PHASE C — AGENT OBSERVABILITY
==================================================

Track:

- Lesia activity
- automation executions
- workflow runs
- model routing
- task volume

Create:

- agent_activity
- agent_cost
- agent_burst
- agent_runtime

Requirements:

- historical
- explainable
- queryable

==================================================
REPORTING
==================================================

Daily reports must answer:

1. Infrastructure activity
2. Project activity
3. Agent activity
4. Economic activity

Not only:

- services
- ports
- drift

==================================================
VALIDATION
==================================================

Prove using recent evidence:

- Lesia rebuild activity appears
- recent commits appear
- API spend appears
- economic anomaly appears
- reports surface all of them

==================================================
OUTPUT
==================================================

Provide:

- modified files
- schema changes
- migrations
- validation evidence
- example reports
- operational impact
- rollback strategy

Maintain:

- bounded architecture
- deterministic behavior
- explainability
- operational trust
