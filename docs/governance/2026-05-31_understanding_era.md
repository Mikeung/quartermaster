# Governance Change Summary — The Understanding Era

Date: 2026-05-31
Trigger: PM directive — "Update Project Governance for Understanding Era"
Author of record: Mike Ung (PM) · executed by Claude Code

---

## What changed (in one sentence)

The product's stated purpose moved from *"monitor / observe / report on a VPS"* to
**"explain an unfamiliar VPS"** — understanding is now the goal; discovery is an input
and reports are an output.

## Why

The system already produces discovery, observation, incidents, and reports — but those
are *means*. The product realization is that the value is making an unfamiliar VPS
**explainable to a new operator without asking the original builders**. Governance was
still framed around the supporting capabilities, not the goal. This change realigns the
governance corpus with the actual product objective.

## The five new rules adopted

1. **New Product Definition** — Quartermaster exists to explain unfamiliar VPS
   environments. Monitoring/observability/reporting/incidents are supporting
   capabilities. Discovery is an input; reports are an output; understanding is the goal.
2. **New Core Principle** — Before approving any work: *"Does this improve
   understanding of an unfamiliar VPS?"* If no, it's probably not the highest priority.
3. **Understanding Framework** — Every project answers WHO / WHAT / WHY / WHERE / WHEN /
   WHAT IF; every answer carries **Answer + Confidence + Evidence**; Unknown is
   acceptable, hallucination is not.
4. **New PM Rule** — PM focuses on outputs, understanding, operator value, investor
   value, and decision usefulness; avoids implementation details, code structure,
   architecture rabbit holes, and framework discussions unless explicitly required.
5. **New Task Memory Rule** — Repository history is operational memory. A task/decision
   does not exist unless recorded: artifact → TASK_LOG → DECISION_LOG (on direction
   change) → commit → push.

## Documents created

| File | Role |
|------|------|
| `UNDERSTANDING_ERA.md` | **Canonical charter** for this era — wins on any conflict about purpose/priority. |
| `docs/governance/2026-05-31_understanding_era.md` | This change summary. |

## Documents updated

| File | Change |
|------|--------|
| `CLAUDE.md` | Added leading "PRIMARY PRODUCT OBJECTIVE — The Understanding Era" section; added Task Memory Rule and PM Operating Rule; added the qualifying question to Operational Discipline; reframed Core Philosophy, Reporting Requirements, and Long-Term Direction around understanding. |
| `PROJECT_VISION.md` | Rewritten lead: the product exists to explain unfamiliar VPS environments; added the framework and the input/output/goal distinction. |
| `GOALS_AND_NON_GOALS.md` | "The Goal" is now understanding; former goals reclassified as supporting inputs/outputs; added discovery/reporting-as-ends to Non-Goals. |
| `SYSTEM_PRINCIPLES.md` | Added "Understanding Is the Goal", "Answer + Confidence + Evidence", and "Repository History Is Operational Memory" principles. |
| `ROADMAP.md` | Added the Understanding-Era strategic frame and "Phase 6 — Understanding Layer (current focus)". |
| `TASK_LOG.md` | Task #201 recorded. |
| `DECISION_LOG.md` | Direction-change decisions recorded (2026-05-31). |

## What did NOT change

The safety and engineering guarantees are untouched: advisory-only / read-only,
"observe automatically, decide manually," human authority over decisions, evidence-first
determinism, and the VPS-first / solo-dev-first simplicity assumptions. The Understanding
Era reframes *purpose and priority* — not the constraints on how the system behaves.

## How to use this going forward

- Read `UNDERSTANDING_ERA.md` first; it is the charter.
- Apply the qualifying question to every proposed task.
- Produce understanding outputs in the Answer + Confidence + Evidence shape.
- Record every task and decision in the repository — it is the operational memory.
