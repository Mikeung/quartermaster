# Project Vision

**Quartermaster exists to explain unfamiliar VPS environments.**

A new operator should be able to understand a VPS — what exists, what it does, why it
exists, who works with it, where it lives, when it is active, and what happens if it
disappears — **without asking the original builders.**

> **Understanding is the goal.**
> Discovery is an input. Reports are an output.

Monitoring, observability, reporting, and incident handling are *supporting
capabilities*, not the product. See [`UNDERSTANDING_ERA.md`](UNDERSTANDING_ERA.md) for
the full governance charter.

## The purpose is not to control infrastructure

The purpose is to:
- explain unfamiliar systems to a newcomer
- restore visibility and preserve operational understanding
- reduce cognitive overload
- analyze LLM usage and costs
- continuously rebuild situational awareness

Core principles:
> Observe automatically. Decide manually.
> Before any work: "Does this improve understanding of an unfamiliar VPS?"

## The Understanding Framework

Every project should eventually answer **WHO / WHAT / WHY / WHERE / WHEN / WHAT IF**,
and every answer carries an **Answer + Confidence + Evidence**. Unknown is acceptable;
hallucination is not. The canonical output is the **Project Profile**
(`reports/projects/`).

## Long-term direction
- infrastructure understanding
- workflow reconstruction
- operational memory
- LLM intelligence analysis
- automated operational reviews
- recommendation generation

All of these serve the single goal: making an unfamiliar VPS explainable.
