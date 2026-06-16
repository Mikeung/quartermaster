# Worker Economics Specification — `reports/projects/economics/`

Status: active · Version 1.0 · 2026-05-31
Governs: the structure and quality of **Worker Economics** artifacts — the fifth lens in
the worker set. See [`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md) (*who*),
[`AGENT_STORY_SPEC.md`](AGENT_STORY_SPEC.md) (*how it became that*),
[`WORKER_REVIEW_SPEC.md`](WORKER_REVIEW_SPEC.md) (*is it doing its job*),
[`WORKER_HEALTH_SPEC.md`](WORKER_HEALTH_SPEC.md) (*can it keep doing its job*), and this
spec (*is it worth it*).

---

## 1. What Worker Economics Is

Worker Economics asks:

> **"Is it worth it?"** — what a worker costs, weighed against the value it appears to create.

It is deliberately separate from the other lenses:

- **Economics is not Health** — a worker can be healthy and expensive.
- **Economics is not Performance** — a worker can perform well and create little value.
- **Economics is not Cost** — a worker can cost money and still be worth keeping; the lens is
  cost *weighed against value*, not the cost number alone.

One economics artifact per worker. Stored at `reports/projects/economics/<project-slug>.md`.
Indexed by `reports/projects/economics/INDEX.md` — the standalone economic dashboard.

## 2. The Hardest Rule: Do Not Invent Value

The system measures some costs and **no revenue**. Therefore:

- **Do not invent revenue.** No worker has a revenue figure on record; do not assign one.
- **Do not invent ROI.** With no revenue and no quantified value, ROI cannot be computed —
  do not state one.
- **Do not invent business value.** Value is reported **only as observable signals**
  (e.g. "the only revenue-facing tool", "a live paying-client deliverable", "real per-brand
  user accounts", "accumulated output") and always labelled **apparent / unquantified**.
- **Unknown is the expected default.** Cost is instrumented for only a fraction of workers
  and value is quantified for none, so most economic positions are Low-confidence or Unknown.
  Say so plainly — an honest "economics unknown" is the correct output, not a guess.

## 3. The Four Questions Every Economics Artifact Must Answer

A CTO, reading only the economics artifacts (or only the INDEX), must be able to answer:

1. **What does it cost?** — measured LLM/cloud spend where instrumented; resource footprint;
   billing dependencies (paid providers it calls) as implied-but-unmeasured cost.
2. **What value does it appear to create?** — observable value signals only; no invented
   numbers.
3. **How confident are we?** — High / Medium / Low, reflecting how much is measured.
4. **Is the economics understood or unknown?** — explicitly: Understood / Partial / Unknown.

And across the fleet (the INDEX): which workers **create value**, which **consume
resources**, which are **economically unknown**, and which **deserve further investment**.

## 4. Required Structure

```
# Worker Economics — <name>

Worker:    <name>   (links to profile / story / review / health)
Generated: <timestamp>
Economic position: <verdict> · Cost: <measured $ | unmeasured | none> · Apparent value: <signal + level> · Economics understood? <Yes|Partial|No> · Confidence: <High|Medium|Low>

## What It Costs        — measured spend, resource footprint, billing dependencies (observable)
## What Value It Appears To Create — observable signals only; no invented revenue/ROI/value
## Confidence & What's Unknown    — what is measured vs. blind
## Economic Verdict     — worth it? and: invest / keep / instrument / divest / decide
```

### Economic-position vocabulary (use exactly these)

| Position | Meaning |
|----------|---------|
| **Value-positive (apparent)** | Observable value clearly present and plausibly exceeds observable cost (still unquantified). |
| **Worth-plausible, cost-blind** | Apparent value, but its cost is unmeasured — worth is likely but unproven. |
| **Cost-bearing, value-modest** | Consumes resources for modest or indirect apparent value. |
| **Net consumer (no demonstrated value)** | Consumes resources with no observable value. |
| **Negligible** | ~Zero cost and ~zero value (inert). |
| **Economically Unknown** | Too little is measured to judge worth at all. |

## 5. Evidence Sources (observable only)

The cost ledger (`llm_events` — measured LLM spend, by project/provider/day), resource
footprint (process RSS, from the live runtime probe), billing dependencies (which paid
providers/APIs a worker calls, from its config/code), and observable value signals (user
base, paying-client/deliverable status, active use, accumulated output, revenue-facing
position) drawn from profiles/reviews — but **reported as signals, never as invented
figures**.

## 6. Honored Evidence Limits

- **Cost instrumentation is partial** — only some workers emit `llm_events`; an uninstrumented
  worker's spend is **Unknown, not zero**. Say "unmeasured."
- **Value is unquantified everywhere** — there is no revenue or value figure for any worker;
  every value statement is an observable *signal*, explicitly apparent/unquantified.
- **Resource footprint ≠ dollar cost** — RSS/compute is a consumption proxy, not a billed
  amount; present it as such.
- **Measured cost may be stale** — cite the ledger date; treat the latest total as a floor.

## 7. Acceptance Test (the PASS gate)

**A CTO can understand the economic position of every worker by reading only the Worker
Economics artifacts (and the INDEX) — without reading profiles, stories, reviews, or health
reports.** For each worker they can state what it costs, what value it appears to create, how
confident that is, and whether its economics is understood or unknown; and across the fleet
they can name who creates value, who consumes resources, who is economically unknown, and who
deserves investment. If any of those is unanswerable from the artifacts alone, it fails.

## 8. Lifecycle

Point-in-time, append-to-history, timestamped; re-run when the cost ledger, instrumentation
coverage, or observable value signals change. Cite the ledger date so staleness is visible.

## 9. Reference Implementations

The first economics artifacts (2026-05-31) under `reports/projects/economics/` are the worked
examples — notably `lesia.md` (the only worker with both a measured cost and clear apparent
value), `seo-agent.md` (apparent value but a potentially-large *unmeasured* cost — the worst
blind spot), `deer-flow.md` (a net consumer with no demonstrated value), and `mempalace.md`
(negligible economics).
