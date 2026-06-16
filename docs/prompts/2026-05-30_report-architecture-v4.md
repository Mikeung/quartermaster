# Prompt — Operational Memory Report Architecture V4

- **Date:** 2026-05-30
- **TASK_LOG:** #199 (governance) + #200 (implementation)
- **Governance commit:** 2a9bdf6
- **Outcome:** Incident reports become self-reconstructing operational memory. Added 5 sections — PROJECT CONTEXT, WHY DID THIS HAPPEN?, SO WHAT?, WHICH LLMS WERE INVOLVED?, INCIDENT CORRELATION — plus a machine-readable metadata header, an operator-editable project-context registry (config/project_context.py), incident index.md + open_incidents.md (reports/incident_index.py), and a V4 daily-report §7 (day-level SO WHAT + Created Today + index/open links). Validated against the 3 real incidents; OOM 5-question test passes. Docs: docs/OPERATIONAL_MEMORY_REPORT_ARCHITECTURE_V4.md

---

## Verbatim prompt

Execute Major Refactor: OPERATIONAL MEMORY REPORT ARCHITECTURE V4

Use:

- PM Operating Rules
- MASTER_EXECUTION_PROMPT_TEMPLATE.md
- TASK_LOG.md
- DECISION_LOG.md

==================================================
STEP 0 — GOVERNANCE
==================================================

Before implementation:

1. Create:

docs/OPERATIONAL_MEMORY_REPORT_ARCHITECTURE_V4.md

2. Update:

- TASK_LOG.md
- DECISION_LOG.md

3. Commit governance changes first.

==================================================
MISSION
==================================================

The goal is NOT to generate reports.

The goal is to preserve operational memory.

A report must remain understandable by an operator who:

- has forgotten the project
- has forgotten the architecture
- has forgotten the workflows
- has forgotten previous incidents
- returns after 6 months

The report must reconstruct the necessary context.

==================================================
CORE PRINCIPLE
==================================================

Reports are the primary product.

Everything else exists to support reports.

Priority order:

1. Incident Reports
2. Daily Reports
3. Notifications
4. Findings
5. Recommendations

Recommendations are NOT the current goal.

Understanding is the current goal.

==================================================
REPORT STORAGE MODEL
==================================================

Incident reports:

reports/incidents/YYYY-MM-DD/<incident_id>.md

Daily reports:

reports/history/YYYY-MM-DD/daily_report.md

Incident index:

reports/incidents/index.md

Open incidents:

reports/incidents/open_incidents.md

Incident reports MUST be committed and pushed.

Daily reports MUST reference incidents.

Incident reports become permanent operational memory artifacts.

==================================================
REPORT LOADING MODEL
==================================================

Daily reports must automatically load and reference:

- related incidents
- previous occurrences
- related findings
- related projects
- related cost audits

An operator reading a daily report must be able to navigate directly to all relevant incident reports.

==================================================
REQUIRED REPORT QUESTIONS
==================================================

Every report must answer:

WHO
WHAT
WHERE
WHEN
WHICH
WHY

and additionally:

SO WHAT

Meaning:

Why should the operator care?

==================================================
MANDATORY CONTEXT SECTION
==================================================

Every incident report must contain:

# PROJECT CONTEXT

This section is mandatory.

Explain:

- project name
- project purpose
- subsystem purpose
- service purpose

Example:

Project:
SEO Agent

Purpose:
Automated SEO research and content generation system.

Subsystem:
seo-agent-worker

Purpose:
Background worker responsible for queue processing and content generation tasks.

Without this section the report is invalid.

==================================================
MANDATORY ROOT CAUSE SECTION
==================================================

Every incident report must contain:

# WHY DID THIS HAPPEN?

Not:

What happened.

But:

Why it happened.

Required:

Immediate cause

Contributing factors

Missing safeguards

Unknown factors

Confidence level

Example:

Immediate cause:
Linux OOM killer terminated seo-agent-worker.

Contributing factor:
Memory usage exceeded available RAM.

Missing safeguard:
No memory limit or restart policy.

Unknown:
Exact workload at termination time.

Confidence:
High

==================================================
MANDATORY SO WHAT SECTION
==================================================

Every incident report must contain:

# SO WHAT?

Explain:

Operational impact

Financial impact

Project impact

User impact

Operator action required

Example:

seo-agent queue processing stopped.

Pending jobs delayed.

No data loss observed.

Manual review recommended.

==================================================
LLM SECTION
==================================================

Every report must contain:

# WHICH LLMS WERE INVOLVED?

Models

Providers

Agents

Costs

Links:

- cost audits
- spend reports

Example:

Gemini 2.5 Pro
Claude Sonnet

Total spend:
$100.21

See:
reports/costs/2026-05-30_cost_audit.md

==================================================
INCIDENT CORRELATION
==================================================

Every incident report must answer:

Is this related to:

- previous incidents?
- spend spikes?
- deployments?
- agent activity?
- subsystem rebuilds?

If yes:

link reports.

==================================================
DAILY REPORT REFACTOR
==================================================

Daily reports become:

Daily Operational Memory

Not:

Daily finding dump.

Not:

Daily drift dump.

Daily report must summarize:

WHO

WHAT

WHERE

WHEN

WHICH

WHY

SO WHAT

for the entire day.

Then list:

Incident Reports Created Today

with paths.

==================================================
VALIDATION
==================================================

Use real incidents:

1. OOM kill
2. Gemini spend event
3. Lesia rebuild activity

For the OOM report specifically prove that a reader can answer:

- What is seo-agent-worker?
- Which project owns it?
- Why does it exist?
- Why was it killed?
- Why should I care?

without asking additional questions.

If any of these questions cannot be answered, the report architecture fails validation.

==================================================
COMPLETION
==================================================

Update:

- TASK_LOG.md
- DECISION_LOG.md

Commit

Push

Provide:

- modified files
- example incident reports
- example daily reports
- validation evidence
- commit hashes
- rollback plan
