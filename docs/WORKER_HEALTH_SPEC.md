# Worker Health Specification — `reports/projects/health/`

Status: active · Version 1.0 · 2026-05-31
Governs: the structure and quality of **Worker Health** artifacts — the fourth and final
lens in the worker set. See [`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md) (*who*),
[`AGENT_STORY_SPEC.md`](AGENT_STORY_SPEC.md) (*how it became that*),
[`WORKER_REVIEW_SPEC.md`](WORKER_REVIEW_SPEC.md) (*is it doing its job*), and this spec
(*can it keep doing its job*).

---

## 1. What Worker Health Is

A Review asks **"Are you doing your job?"** Health asks a different question:

> **"Can you keep doing your job?"**

Health is the worker's **operational condition** — whether it is stable, recoverable, and
durable enough to continue, irrespective of whether the job it does is valuable, correct, or
mission-aligned. The two are deliberately independent:

- A worker can be **healthy and doing the wrong job** (stable, resilient — but pointless).
- A worker can be **unhealthy and doing the right job** (delivering real value — but one
  disk failure from losing it).

Health is **not** performance, **not** value, **not** mission alignment. Keep it separate.

One health artifact per worker. Stored at `reports/projects/health/<project-slug>.md`.
Indexed by `reports/projects/health/INDEX.md` — the standalone health dashboard.

## 2. Why It Exists

After identity, story, and review, the inheriting CTO's operational question is survival:
*will this still be running next week, and if not, why?* Health turns observable operational
reality into a prognosis and an attention decision.

## 3. The Four Questions Every Health Artifact Must Answer

A CTO, reading only the health artifact (or only the INDEX), must be able to answer:

1. **Is this worker healthy?** — the condition verdict.
2. **What threatens its health?** — the continuity risks, ranked.
3. **How likely is it to fail?** — the prognosis, and the most likely failure mode.
4. **Does it need attention?** — yes/no/urgent, and what to do.

## 4. Required Structure

```
# Worker Health — <name>

Worker:    <name>   (links to profile / story / review)
Generated: <timestamp>   (note any live-probe time)
Condition: <verdict> · Failure likelihood: Low|Medium|High|Unknown · Needs attention: No|Yes|Urgent · Confidence: High|Medium|Low

## Vital Signs            — the observable now: liveness, stability, recoverability, durability, dependencies, resource/exposure pressure
## What Threatens Its Health — continuity risks, ranked
## Prognosis             — how likely to fail, and how it would fail
## Attention             — does it need attention, what, how urgent
```

**Self-containment is mandatory** (see §7): restate the observable facts inside the artifact;
do not require the reader to open incidents, profiles, stories, or reviews.

### Condition vocabulary (use exactly these)

| Condition | Meaning |
|-----------|---------|
| **Healthy** | Stable, recoverable, durable — can keep doing its job. |
| **Healthy — with vulnerabilities** | Operating well, but carries latent continuity risks. |
| **Fragile** | Operating, but a single failure point could stop it or lose its work. |
| **Degraded** | A component is currently failing or down. |
| **Critical** | Active data-loss exposure, or imminent stop. |
| **Inert / Dormant** | Nothing running to fail (passive); health is about the data at rest. |
| **Unknown** | Cannot assess from available evidence. |

## 5. Health Dimensions (observable only — no invented metrics or KPIs)

Assess from **existing observable evidence**; never fabricate uptime %, SLAs, error rates,
or scores that are not actually measured.

- **Liveness** — is it running now? (process / unit `is-active` / listening port / uptime)
- **Stability** — crashes, restart loops, OOM history, failed states.
- **Recoverability** — does it self-heal? (auto-restart policy, supervision, redundancy) or
  is recovery manual-only?
- **Durability** — is its code/data safe? (git remote, backups, persistence vs. uncommitted
  work / no remote / empty stores).
- **Dependency health** — are the things it needs healthy? (a worker on a failed dependency
  is unhealthy even if its own process is up).
- **Resource & exposure pressure** — memory/disk pressure on the shared host; an unmanaged
  exposed surface that threatens continuity.

## 6. Quality Rules

1. **Observable evidence only** — every condition cites a real signal (process state,
   unit state, incident, git state, host resource state).
2. **No invented metrics / KPIs** — if a number isn't measured, don't state one; say Unknown.
3. **Health ≠ Review** — do not import performance/value judgements; a degraded health
   verdict on a valuable worker, or a healthy verdict on a useless one, is correct and
   expected.
4. **Separate the process from the data** — a worker whose process is up but whose work is
   undefended (uncommitted, no backup) is *unhealthy on durability*; say which.
5. **Unknown is acceptable** — unsupervised or unobservable workers get Unknown, stated.
6. **Label inference / probe time** — live-runtime claims carry the probe timestamp; stale
   inference lowers confidence.
7. **Actionable & advisory** — the attention call is concrete; the system recommends, the
   human acts.
8. **Declare self-assessment** when the system reports on its own health.

## 7. Acceptance Test (the PASS gate)

**A CTO can understand the operational condition of every worker by reading only the Worker
Health artifacts (and the INDEX) — without reading incidents, profiles, stories, or
reviews.** For each worker they can state: is it healthy, what threatens it, how likely it
is to fail, and whether it needs attention — each grounded in an observable signal. If any of
the four questions is unanswerable from the artifact alone, it fails.

## 8. Lifecycle

Health is the most time-sensitive lens — point-in-time, append-to-history, timestamped, and
re-run whenever runtime/resource/durability state changes. Each artifact records the live
probe time so staleness is visible.

## 9. Reference Implementations

The first health artifacts (2026-05-31) under `reports/projects/health/` are the worked
examples — notably `seo-agent.md` (**Degraded**: a failed dependency + inactive worker now),
`telegram-humint.md` (**Critical** on durability while its process is healthy — the
"unhealthy but doing the right job" case), `dtv-agent.md` (**Healthy** — the model:
sandboxed, self-restarting, low blast radius), and `mempalace.md` (**Inert/Dormant**).
