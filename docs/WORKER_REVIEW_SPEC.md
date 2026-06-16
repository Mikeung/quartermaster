# Worker Review Specification — `reports/projects/reviews/`

Status: active · Version 1.0 · 2026-05-31
Governs: the structure and quality of **Worker Reviews** — the performance assessment that
completes the worker trilogy. See [`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md)
(*who* a worker is), [`AGENT_STORY_SPEC.md`](AGENT_STORY_SPEC.md) (*how* it became that),
and this spec (*is it doing its job?*).

---

## 1. What a Worker Review Is

A Profile answers **who** a worker is. A Story answers **how** it became that worker. A
Worker Review answers the question a CTO asks about every member of the team:

> **Is it doing its job?**

It is a performance review: the worker is treated as an employee, its stated purpose is its
job description, and the review judges — from observable evidence — whether it is delivering
on that purpose, how reliably it behaves, whether it is worth what it costs, what risks it
carries, and what the manager should do about it.

It is **not** a profile (it assumes who/what is known), **not** a story (it assumes the
history is known), and **not** an incident report (it judges the *whole worker*, not one
event). It is a verdict with a recommended action.

One review per worker. Stored at `reports/projects/reviews/<project-slug>.md`. Indexed by
`reports/projects/reviews/INDEX.md` (the CTO scorecard).

## 2. Why It Exists (relationship to the mission)

Understanding an unfamiliar VPS is not complete at "what is this and how did it get here."
The inheriting operator's next question is operational: *should I keep it, fix it, secure
it, fund it, or shut it down?* The Review turns the evidence base into a management
decision — the point of understanding.

## 3. Required Structure

```
# Worker Review — <name>

Worker:     <name>            (links to ../<slug>.md profile and ../stories/<slug>.md story)
Generated:  <timestamp>
The job:    <one-sentence job description — what it is accountable for>
Verdict:    <rating>  ·  Doing its job? YES | PARTIALLY | NO | UNKNOWN  ·  Review confidence: High|Medium|Low

## The Job              — what it is accountable for (its purpose as a job description)
## Is It Doing Its Job? — performance against that purpose, with evidence
## Reliability & Conduct— incidents, health, failures, operational discipline
## Cost & Value         — is it worth what it costs? (measured or Unknown)
## Risks & Liabilities  — standing concerns a manager must carry
## Verdict & Recommended Action — the rating, the action, and what to watch next
```

### Rating vocabulary (use exactly these)

| Rating | Meaning (employee analogy) |
|--------|----------------------------|
| **Performing** | Doing its job, meeting its purpose. A solid contributor. |
| **Performing — with concerns** | Delivering, but with material issues to manage. |
| **Underperforming** | Not adequately delivering on its stated purpose. |
| **At-Risk** | Delivering, but a critical failure or liability threatens it (or what it serves). Needs an improvement plan. |
| **Dormant / Not Performing** | Produces no output; on the payroll but idle. |
| **Cannot Assess** | Insufficient evidence to judge performance (Unknown). |

Every review states one rating plus the headline **Doing its job? YES/PARTIALLY/NO/UNKNOWN**
and a **Review confidence**.

## 4. Quality Rules (inherited from the Understanding contract)

1. **Evidence first** — every judgement cites observable evidence (incidents, cost ledger,
   git activity, runtime state, profile/story facts). No verdict without grounds.
2. **Unknown is acceptable** — if performance cannot be judged (no metrics, no git, idle
   service), say **Cannot Assess** and why; never invent a verdict.
3. **Fair, not flattering** — a CTO review names underperformance and liabilities plainly,
   and credits genuine delivery plainly. No grade inflation; no gratuitous harshness.
4. **Separate conduct from outcome** — a worker can deliver its job *and* carry a serious
   liability (e.g. exposed credentials); say both.
5. **Label inference** — "running state inferred from an open incident, not directly
   confirmed" lowers Review confidence.
6. **Actionable** — the recommended action must be concrete and within the advisory mandate
   (the system recommends; the human decides and acts).
7. **Declare conflicts** — when the system reviews *itself*, the review must say so.
8. **Self-contained** — readable alone; cross-reference profile/story/incidents by path.

## 5. Evidence Sources (read for *performance*)

Current incident record (open/resolved per worker, severity), cost ledger (spend vs.
value), git activity (commits, engineering bursts, last activity = is it being worked on),
runtime state (listening ports, unit `is-active`, process age = is it actually running),
last-intake / last-crawl / last-deploy timestamps (is it producing), the Profile (WHAT-IF
impact = how much its performance matters), and the Story (whether known failure modes
recurred).

## 6. Honored Evidence Limits

- **No metrics → Cannot Assess that dimension**, stated honestly (most workers have no
  throughput/SLA instrumentation).
- **Unmeasured cost is not zero cost** — say "cost Unknown" rather than implying free.
- **Running-state inference** (e.g. a service assumed up because an incident referenced its
  process) is Medium confidence at best; direct port/unit confirmation is High.

## 7. Acceptance Test (per review)

After reading the review, a new CTO can answer, for that worker: **is it doing its job, how
well, what's wrong with it, and what should I do about it** — and can see, for each
judgement, the evidence and how confident to be. If the verdict is unsupported or the
recommended action is missing, the review fails.

## 8. Lifecycle

Reviews are point-in-time, append-to-history operational-memory artifacts (committed and
pushed, timestamped). They are re-run when performance-relevant evidence changes — a new
critical incident, a cost event, a resumption or cessation of activity.

## 9. Reference Implementations

The first reviews (2026-05-31) under `reports/projects/reviews/` are the worked examples —
notably `lesia.md` (a strong performer with a corrected expensive incident), `hdt-web.md`
(At-Risk after a critical OOM), `deer-flow.md` (Cannot Assess / likely idle), and
`mempalace.md` (Dormant). `quartermaster.md` is the worked example of a declared
self-review.
