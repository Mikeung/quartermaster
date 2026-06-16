# Incident Reporting Enforcement Phase

_Verbatim operator prompt, archived for traceability. TASK_LOG #197._

---

Execute Incident Reporting Enforcement Phase

Use:

- PM Operating Rules
- TASK_LOG.md
- DECISION_LOG.md

## STEP 0 — GOVERNANCE

Create `docs/INCIDENT_REPORTING_SPEC.md`. Update TASK_LOG.md and DECISION_LOG.md.
Commit governance changes first.

## MISSION

Telegram is an alert channel. Git repository is the system of record. Every P0
and P1 event must produce a full markdown incident report. Alerts without
reports are incomplete.

## REQUIREMENTS

For every P0 / P1 notification create `reports/incidents/YYYY-MM-DD/<incident_name>.md`.

## INCIDENT REPORT FORMAT

`# Executive Summary` / `# WHAT` / `# WHERE` / `# WHEN` / `# WHICH` / `# WHO` /
`# COST` / `# Evidence` / `# Timeline` / `# Impact` / `# Recommendations` /
`# Open Questions` / `# Validation`.

## TELEGRAM CHANGES

Telegram becomes: short alert + link/path to full report. Example:

```
🚨 Runaway Agent Cost
Agent: Lesia
Cost: $67
Full report:
reports/incidents/2026-05-30/runaway_agent_cost.md
```

## VALIDATION

Replay: Gemini spend incident, OOM incident, subsystem rebuild. Prove: report
created, report committed, report pushed, Telegram references report.

## COMPLETION

Update TASK_LOG.md, DECISION_LOG.md; commit; push. Output modified files,
example incident reports, validation evidence, commit hash.
