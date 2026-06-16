# The Understanding Era — Governance Charter

Status: active · Adopted 2026-05-31 · Supersedes the "monitoring/observability/reporting"
framing of this project's purpose. This is the canonical statement of what AI
Operational Memory is *for*. Where any other governance document conflicts with this
one on **purpose or priority**, this document wins. (Safety and engineering rules in
[CLAUDE.md](CLAUDE.md) still bind absolutely — this charter never authorizes
autonomous action.)

---

## 1. New Product Definition

**Quartermaster exists to explain unfamiliar VPS environments.**

It is **not** a monitoring platform.
It is **not** an observability platform.
It is **not** a reporting platform.
It is **not** an incident platform.

Those are *supporting capabilities*, not the product.

- **Discovery is not the goal. Discovery is an input.**
- **Reports are not the goal. Reports are an output.**
- **Understanding is the goal.**

The system must let a new operator understand an unfamiliar VPS — what exists, what
it does, why it exists, who works with it, where it lives, when it is active, and
what happens if it disappears — **without asking the original builders.**

---

## 2. New Core Principle

Before approving or starting any work, ask:

> **"Does this improve understanding of an unfamiliar VPS?"**

If the answer is **no**, it is probably not the highest priority.

This question outranks "is it interesting", "is it technically elegant", and "is it
more data". More discovery, more scanning, and more reports are only valuable insofar
as they make an unfamiliar system **explainable to a newcomer**.

---

## 3. The Understanding Framework (6 Questions)

Every project on a VPS should eventually be explainable through six questions:

| Question | Asks |
|----------|------|
| **WHO** | Who works on it? Who uses it? Who depends on it? |
| **WHAT** | What is this project? |
| **WHY** | Why does it exist? What mission does it serve? |
| **WHERE** | Where does it live? (repos, services, containers, ports, databases, external deps) |
| **WHEN** | When is it active? When was it last modified? What is its activity pattern? |
| **WHAT IF** | What happens if it disappears / stops running / loses a dependency / drifts? |

### Every answer must contain three parts

1. **Answer** — the explanation in plain language.
2. **Confidence** — High · Medium · Low.
3. **Evidence** — the observable facts (files, scans, git history, incidents, logs) the answer rests on.

### Two hard rules

- **Unknown is acceptable.** "We cannot determine this from observable evidence" is a valid, useful answer.
- **Hallucination is not acceptable.** No invented purpose, no unsupported claim, no answer without evidence. Prefer fewer correct statements over many speculative ones.

The canonical realization of this framework is the **Project Profile**
(`reports/projects/`), introduced 2026-05-31.

---

## 4. New PM Rule

The PM focuses on **outcomes, not mechanics.**

PM should focus on:

- outputs
- understanding
- operator value
- investor value
- decision usefulness

PM should avoid:

- implementation details
- code structure
- architecture rabbit holes
- framework discussions

…unless explicitly required. Engineering decisions remain Claude Code's
responsibility (see [CLAUDE.md](CLAUDE.md) role definition); the PM judges whether the
*output* improves understanding and is useful to an operator/investor making decisions.

---

## 5. New Task Memory Rule

**Repository history is operational memory.**

> A task does not exist unless it is recorded.
> A decision does not exist unless it is recorded.

Every approved PM task must:

1. Create a markdown artifact (the durable output).
2. Update `TASK_LOG.md`.
3. Update `DECISION_LOG.md` when direction changes.
4. Commit changes.
5. Push changes.

This makes the repository itself the first thing a new operator can read to understand
the system — consistent with the product's own mission applied to itself.

---

## 6. What Does *Not* Change

The Understanding Era reframes **purpose and priority**. It does not relax the
project's foundational guarantees:

- **Advisory-only / read-only.** The system observes, analyzes, explains, and
  recommends. It never modifies infrastructure, deploys, self-modifies, or acts
  autonomously. (`CLAUDE.md` Read-Only Intelligence Rule.)
- **Observe automatically. Decide manually.** Humans remain responsible for decisions.
- **Evidence first, determinism, simplicity, observability.** Same engineering
  philosophy; same VPS-first, solo-dev-first assumptions.

Understanding is the new *goal*; the existing principles are *how* we reach it safely.

## Convergence, not completeness

The Observer maintains **Current Understanding, not Absolute Truth**: its success metric is how quickly it discovers and corrects its own mistakes (convergence), not % correct. Every conclusion carries Confidence, Evidence, Last verified, Contradictions found, and Revision history; belief changes are logged in `reports/projects/REVISIONS.md`. See [`docs/OBSERVER_CONVERGENCE.md`](docs/OBSERVER_CONVERGENCE.md).
