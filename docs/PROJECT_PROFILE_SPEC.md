# Project Profile Specification — `reports/projects/`

Status: active · Version 1.0 · 2026-05-31
Governs: the structure and quality of Project Profiles, the headline output of the
Understanding Layer. See [`UNDERSTANDING_LAYER_MVP.md`](UNDERSTANDING_LAYER_MVP.md)
(the contract) and [`INDEX_VISION.md`](INDEX_VISION.md) (the table of contents).

---

## 1. What a Project Profile Is

A Project Profile is a single markdown document that explains one project on a VPS to
someone who has never seen it, using **observable evidence only** and the six-question
framework (WHO / WHAT / WHY / WHERE / WHEN / WHAT IF), each answered with
**Answer + Confidence + Evidence**.

One profile per project. Stored at `reports/projects/<project-slug>.md`. Indexed by
`reports/projects/INDEX.md`.

## 2. Audiences (design for all four)

A profile must be useful, from the same evidence, to:

| Audience | What they need from it |
|----------|------------------------|
| **Operator onboarding** | "I just inherited this VPS — what is this, where does it run, what breaks it?" |
| **CTO review** | "What do we run, who depends on it, where is the risk?" — without a meeting |
| **Investor review** | "What does this asset do, is it real, how active is it?" — credible because every claim is evidenced |
| **Acquisition due diligence** | "What are we buying, what are the dependencies and liabilities, what's the bus-factor?" — defensible because confidence and unknowns are explicit |

The common requirement across all four: **claims are evidenced, confidence is explicit,
and unknowns are stated rather than hidden.** That is what makes the document trustworthy
to a reader who cannot ask the builders.

## 3. Required Structure

```
# Project Profile

Project:   <name>
Generated: <timestamp>

## WHO        — Questions / Answer / Confidence / Evidence
## WHAT       — Questions / Answer / Confidence / Evidence
## WHY        — Questions / Answer / Confidence / Evidence
## WHERE      — Questions / Answer / Confidence / Evidence
## WHEN       — Questions / Answer / Confidence / Evidence
## WHAT IF    — Questions / Answer / Confidence / Evidence
```

Each of the six sections MUST contain:

- **Questions** — the standard questions for that dimension (verbatim from the framework).
- **Answer** — plain language.
- **Confidence** — High | Medium | Low (overall for the section).
- **Evidence** — a bulleted list of specific, independently-verifiable observations.

(WHERE should, when available, enumerate: repositories, services, containers, ports,
databases, external dependencies. Use only project-specific ports — never host-wide.)

## 4. Quality Rules

1. **Evidence first** — no claim without a cited source.
2. **Confidence on every section** — never omit it.
3. **Unknown is acceptable** — state it and why; do not pad with speculation.
4. **Hallucination is forbidden** — no invented purpose, owner, dependency, or date.
5. **Label inference** — runtime/heuristic attributions say so and lower confidence.
6. **Prefer fewer correct statements** over many speculative ones.
7. **Determinism** — same evidence → same profile; no LLM-invented prose.
8. **Self-contained** — a reader needs no other context; cross-reference incidents/INDEX
   by path, but the profile stands alone.

## 5. Evidence Sources

As defined in [`UNDERSTANDING_LAYER_MVP.md`](UNDERSTANDING_LAYER_MVP.md) §5: README and
docs, repo structure, source, manifests, service/compose files, project-specific ports,
processes, containers, logs, git history, incidents, daily reports, cost records,
workflow inferences, the project-context registry.

## 6. Known Evidence Limits (must be honored)

- **Host-wide port pollution** — the service scanner attributes all host ports to every
  project. Profiles use only project-specific ports (compose / package.json / unit files).
- **Runtime attribution is inference** — e.g. a bare `node` process attributed to a
  project is Medium confidence at best; say so.
- **Costs are estimates** — ingested-usage estimates, not authoritative billing; state it.

## 7. Lifecycle

- Profiles are regenerated as the underlying VPS changes; each carries a `Generated`
  timestamp so staleness is visible.
- A profile is an append-to-history artifact in the repo (operational memory): committed
  and pushed like any other task output.

## 8. Acceptance Test (per profile)

A reader from any of the four audiences in §2, given only this profile (and the INDEX),
can state what the project is, why it exists, who depends on it, where it runs, and what
happens if it disappears — and can see, for each claim, how confident to be and what it
rests on. If any of those is missing or unsupported, the profile fails review.

## 9. Reference Implementation

The first profiles (2026-05-31) — `reports/projects/INDEX.md`,
`quartermaster.md`, `lesia.md`, `hdt-web.md` — are the worked examples of this
specification.
