# Agent Story Specification — `reports/projects/stories/`

Status: active · Version 1.0 · 2026-05-31
Governs: the structure and quality of **Agent Stories**, the narrative companion to the
Project Profile. See [`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md) (what a worker
*is*) and [`UNDERSTANDING_LAYER_MVP.md`](UNDERSTANDING_LAYER_MVP.md) (the evidence
contract).

---

## 1. What an Agent Story Is

A Project **Profile** explains *what a worker is* — a structured, six-question snapshot of
its current state. A Profile does **not** explain *how a worker became what it is*.

An **Agent Story** is the missing narrative: how the original creator would explain this
worker's journey to a new CTO who just inherited it. It is the answer to:

> "If you inherited this worker today — where did it come from, how did it change, what
> went wrong and right along the way, and why does it look the way it does now?"

It is **not** a log, **not** a timeline, **not** raw git history. It is a *story* — a
short, readable narrative that turns evidence (commits, incidents, costs, profiles) into
understanding of the worker's *arc*.

One story per worker. Stored at `reports/projects/stories/<project-slug>.md`. Indexed by
`reports/projects/stories/INDEX.md`. Each story links to its Profile and back.

## 2. Why It Exists (relationship to the mission)

The Understanding Era charter asks whether a new operator can understand an unfamiliar VPS
*without asking the original builders*. A Profile answers "what is this." A Story answers
"how did it get here" — the context a successor normally only gets by talking to the
person who built it. The Story is how that conversation survives the builder leaving.

## 3. Required Structure

```
# Agent Story — <name>

Worker:    <name>            (links to ../<slug>.md profile)
Generated: <timestamp>
One-line:  <the worker's arc in a single sentence>

## Origin              — where it came from
## Evolution           — how it changed
## Major Turning Points — the moments that redefined it
## Lessons Learned     — what its history teaches an operator
## Current Identity    — what it is today, and why it looks this way
```

Each of the five sections is **prose** (not tables), but every factual claim must be
**traceable to evidence** — inline, in plain language ("its first commit, 2026-04-18, …",
"the $100.21 runaway incident on 2026-05-30, …"). A story may end with a short
**Evidence** footnote listing the concrete sources it drew on.

Each story carries a **Story Confidence** line (High / Medium / Low) reflecting how much
of the journey is evidenced versus inferred — separate from the Profile's per-section
confidence.

### Section meaning

- **Origin** — When and why it was created; who/what built it; what problem it was born to
  solve; its first observable state. (Evidence: first commit, initial README/CLAUDE.md,
  bootstrap commits, file-creation timestamps.)
- **Evolution** — How it grew or changed between origin and now: the phases, the shift in
  scope, the pace, periods of activity and dormancy. (Evidence: commit history, task logs,
  file mtimes, version notes.)
- **Major Turning Points** — The specific moments that changed what the worker *is*: an
  outage, a cost runaway, a rebuild, a mission redefinition, an abandonment. Name the date
  and the evidence. These are the load-bearing events of the narrative.
- **Lessons Learned** — What the worker's history teaches the inheriting operator: the
  recurring failure modes, the standing risks, the things that were hard-won. Grounded in
  what actually happened, not generic best practice.
- **Current Identity** — Who this worker is *today* and *why it looks this way* — closing
  the loop from origin through evolution to the present state in the Profile.

## 4. Quality Rules (inherited from the Profile contract)

1. **Evidence first** — no claim without a traceable source. Use real dates, commit
   subjects, incident names.
2. **Do not invent** — never fabricate an origin, motive, author, or turning point.
3. **Unknown is acceptable and expected** — many workers have no accessible git, no docs,
   no creator records. Where the journey is unevidenced, **say "Unknown" and why** — an
   honest "Origin: Unknown — no git history, no README; first observable trace is a
   file-creation timestamp of …" is a correct Story section, not a failure.
4. **Label inference** — runtime/heuristic attributions (e.g. a bare `node` process → a
   project) say so and lower Story Confidence.
5. **Narrative, not log** — synthesize evidence into an arc; do not paste commit dumps.
6. **Prefer fewer true sentences** over many speculative ones.
7. **Self-contained** — readable without other context; cross-reference the Profile and
   incidents by path.
8. **Determinism of evidence** — the same evidence supports the same story; the narrative
   is a faithful reading of the record, not creative writing.

## 5. Evidence Sources

Same observable sources as the Profile (see `UNDERSTANDING_LAYER_MVP.md` §5), read for
*change over time* rather than current state: git history (origin commit, phase commits,
authors, cadence, last activity), task/build logs, incident reports (turning points),
cost ledger (economic turning points), file-creation/modification timestamps (when git is
absent), README/CLAUDE.md/handoff docs (stated intent and rebuilds), and the
project-context registry.

## 6. Honored Evidence Limits

- **No git → journey is largely Unknown.** For workers without accessible git history
  (e.g. SEO Agent, Memory Palace, DTV Agent), Origin/Evolution rest on filesystem
  timestamps and docs only; confidence is Medium-to-Low and must say so.
- **Upstream vs. this-instance.** For third-party/OSS workers (e.g. DeerFlow), separate
  the *software's* well-evidenced history from *this deployment's* often-unknown local
  story.
- **Inference is surfaced, never laundered as fact.**

## 7. Acceptance Test (per story)

After reading the Story (and only the Story), a new CTO can state, in their own words:

1. **What this worker is today.**
2. **How it became that worker.**
3. **Why it looks the way it does now.**

…and can see, for each part of the journey, whether it rests on evidence or is explicitly
Unknown. If any of the three is missing or unsupported, the story fails review.

## 8. Lifecycle

Stories are append-to-history operational-memory artifacts: committed and pushed like any
other task output, each carrying a `Generated` timestamp so staleness is visible. They are
regenerated as new turning points occur (a major incident, a rebuild, an abandonment).

## 9. Reference Implementations

The first stories (2026-05-31) under `reports/projects/stories/` — `quartermaster.md`
(richest evidence: 199 commits, 209 tasks, 189 decisions), `lesia.md` (a cost-runaway and
its structural fix), `telegram-humint.md` (a 2-day rebuild now in uncommitted limbo), and
`mempalace.md` (a worked example of an honest mostly-Unknown story) — are the worked
examples of this specification.
</content>
</invoke>
