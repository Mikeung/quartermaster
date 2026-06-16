# Prompt — PRIORITY ZERO: Real-Time Operational Notification Layer

- **Date:** 2026-05-30
- **TASK_LOG:** #193
- **Commit:** 3189657
- **Outcome:** Notification pipeline (classify→dedup→Telegram), P0 immediate (quiet-hours bypass) / P1 batched / P2 daily; notify.py 15-min cron (installed + primed). Docs: docs/NOTIFICATION_LAYER.md

---

## Verbatim prompt

Execute PRIORITY ZERO phase:

REAL-TIME OPERATIONAL NOTIFICATION LAYER

Mission:

Reduce awareness latency from hours to minutes.

The system must notify operators immediately when important operational events occur.

Current problem:

Daily reports correctly summarize history but fail to surface critical events in time.

Examples already observed:

- $100 overnight API spend
- major Lesia engineering activity
- subsystem rebuilds

These events must generate notifications immediately instead of waiting for daily reports.

==================================================
IMPLEMENT

1. Event Notification Pipeline

Event
→ Classification
→ Deduplication
→ Telegram notification

==================================================
2. Notification Priorities

P0 Immediate:
- spend spike
- economic anomaly
- runaway agent cost
- OOM kill
- dependency failure
- public exposure
- deployment event
- subsystem rebuild
- engineering burst

P1 Batched:
- restart bursts
- unusual activity
- recurring findings

P2 Daily:
- summaries
- trends

==================================================
3. Economic Notifications

Alert on:

- spend threshold exceeded
- abnormal burn rate
- provider spike
- agent cost spike

Support:
- Claude
- Gemini
- OpenAI

==================================================
4. Engineering Notifications

Alert on:

- deployment detected
- commit burst
- large file change count
- subsystem rebuild
- significant project activity

==================================================
5. Agent Notifications

Alert on:

- Lesia burst activity
- automation burst
- workflow spike
- unusual model usage

==================================================
6. Deduplication

Prevent:
- notification storms
- repeated alerts
- noisy repetition

Maintain:
- finding identity semantics
- recurrence semantics

==================================================
7. Validation

Prove using recent evidence:

- $100 spend scenario would have alerted
- Lesia rebuild scenario would have alerted
- duplicate notifications suppressed
- notification latency reduced

==================================================
8. Output

Provide:

- modified files
- schema changes
- validation evidence
- example notifications
- operational impact
- rollback strategy

Maintain:

- deterministic behavior
- explainability
- bounded architecture
- operational trust
