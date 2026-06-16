# INDEX Vision — The Table of Contents of the VPS

Status: vision / specification · Version 1.0 · 2026-05-31
Governs: `reports/projects/INDEX.md` and its evolution toward a full VPS index. See
[`UNDERSTANDING_LAYER_MVP.md`](UNDERSTANDING_LAYER_MVP.md) and
[`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md).

---

## 1. What the INDEX Is

The INDEX is **the table of contents of the VPS**. It is the **first report an operator
should read** — the single page that orients someone who has just been handed an
unfamiliar machine, and points them at what to read next.

If a Project Profile answers "what is *this* project?", the INDEX answers "what is *here
at all*, and where do I start?"

## 2. The Questions the INDEX Must Answer

The INDEX exists to answer, on one page:

- **What do I own?** — the VPS at a glance: scope, scale, how many projects.
- **What projects exist?** — every discovered project, one line each, linked to its Profile.
- **What agents exist?** — the automated/LLM agents running here (e.g. cron agents, coding agents) and what they act on.
- **What services exist?** — the running services and where they listen (project-attributed where possible).
- **What costs exist?** — known LLM/API spend, by project/provider, and any unattributed spend.
- **What should I read next?** — a prioritized reading order (e.g. open incidents first, then highest-risk profiles).

## 3. Design Principles

- **First contact.** Assume the reader knows nothing and has five minutes. The INDEX must
  be comprehensible cold.
- **Orientation, not detail.** It summarizes and links; depth lives in Project Profiles
  and incident reports.
- **Evidence-backed, confidence-aware.** Like profiles, INDEX claims rest on observed
  evidence; where coverage is partial, the INDEX says so (e.g. "3 of 5 projects
  discovered"). No silent truncation.
- **Points to the next read.** Its job is to route attention — surface what is urgent
  (open incidents, runaway cost) and what is foundational (the biggest/most-depended-on
  projects).
- **Honest about gaps.** Undiscovered projects, unattributed cost, and unregistered
  services are themselves operational signals and must be shown, not omitted.

## 4. Target Structure

```
# VPS INDEX — <host / scope>
Generated: <timestamp>   ·   Coverage: <N discovered / M believed-present>

## What do I own           — one-paragraph VPS overview (host, scale, project count)
## Projects                — table: project · what it is · owner/users · where · activity · link to Profile
## Agents                  — automated/LLM agents, what they run on, cadence, cost
## Services                — running services + (project-specific) ports, project-attributed
## Costs                   — spend by project/provider; unattributed remainder flagged
## Open incidents          — current incidents, newest/most-severe first (links)
## What to read next       — prioritized reading order with rationale
## Coverage & gaps         — what was NOT discovered or attributed, and why
```

## 5. Relationship to Project Profiles

- The INDEX is the **breadth** layer (everything, shallow); Project Profiles are the
  **depth** layer (one thing, complete).
- Every INDEX project row links to its Profile; every Profile is reachable from the INDEX.
- Reading order for a new operator: **INDEX → open incidents → highest-priority Profiles.**

## 6. MVP Status and Evolution

- **Today (MVP):** `reports/projects/INDEX.md` is a hand-curated table of contents over
  the delivered Project Profiles, plus how-to-read guidance and a coverage note.
- **Next:** auto-generate the INDEX from operational memory (snapshots, findings,
  llm_events, incidents, project-context registry) so it stays current as the VPS drifts —
  including the Agents / Services / Costs sections and the prioritized "what to read next".
- **Definition of done:** an operator who reads only the INDEX can answer the six
  questions of §2 and knows exactly which document to open next.

## 7. Success Test

Hand a new operator nothing but the INDEX. Within five minutes they can say: how many
projects exist, which ones matter most, what is currently on fire, what it costs, and
which document to read first. If they can't, the INDEX has not done its job.
