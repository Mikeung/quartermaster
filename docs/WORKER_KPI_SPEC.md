# Worker KPI Specification — `reports/projects/kpi/`

Status: active · Version 1.1 · 2026-05-31
Governs: the structure and quality of **Worker KPI** artifacts — the sixth lens, which
answers *"are we achieving what we set out to achieve?"* See the worker set:
[`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md) (who),
[`AGENT_STORY_SPEC.md`](AGENT_STORY_SPEC.md) (how it became that),
[`WORKER_REVIEW_SPEC.md`](WORKER_REVIEW_SPEC.md) (is it doing its job),
[`WORKER_HEALTH_SPEC.md`](WORKER_HEALTH_SPEC.md) (can it keep doing it),
[`WORKER_ECONOMICS_SPEC.md`](WORKER_ECONOMICS_SPEC.md) (is it worth it), and this spec
(is it doing what it was *supposed* to).

> **v1.1 — Mission Discovery (§9).** A missing mission is no longer a terminal "unassessable."
> The KPI layer now *discovers* a mission from evidence when none was declared, attaches
> confidence + evidence, and routes it through PM confirmation before the assessment proceeds.

---

## 1. What a Worker KPI Is

KPI here is **not metrics** and **not a dashboard**. It is the **comparison between a worker's
Mission and Observed Reality**:

> **Mission** — what the worker is supposed to do. It is either **Declared** (stated by the
> owner) or, where none was declared, **Discovered** (inferred from evidence, with confidence,
> and confirmed by the PM). See §9.
>
> **Observed Reality** — what the worker is actually doing, from the discovery captured across
> the other five lenses.

The KPI is the **gap analysis** between the two: alignment, gaps, drift, and unknowns. It
answers mission fulfillment, not activity.

One KPI artifact per worker (`reports/projects/kpi/<slug>.md`), one mission registry
(`reports/projects/kpi/MISSIONS.md`), indexed by `reports/projects/kpi/INDEX.md`.

## 2. The Hardest Rule: Use Only Evidenced Scope — Do Not Invent It

The comparison is only meaningful if the Mission is grounded, not imagined.

- **Do not invent goals.** A **Declared** mission uses only objectives stated in the worker's
  own evidence (`CLAUDE.md`, `README`, `REBUILD_SCOPE`, `PROJECT_REVIEW`,
  `GOALS_AND_NON_GOALS`, system-snapshot, in-code docstrings). A **Discovered** mission is
  inferred only from observable evidence (§9) and carries a confidence level — it must not
  assert ambition the evidence cannot support.
- **Do not invent success criteria.** If no targets/SLAs/audience were stated, say "success
  criteria undeclared" — do not assign one.
- **Unknown is acceptable**, but **"no declared mission" now triggers Discovery (§9)**, not a
  terminal "unassessable."

## 3. The Five Questions Every KPI Artifact Must Answer

1. **What was this worker supposed to do?** — its Mission (Declared or Discovered).
2. **What is it actually doing?** — Observed Reality.
3. **Is it on track?** — alignment of observed with mission.
4. **Is it drifting?** — divergence of observed from mission.
5. **What is still unknown?** — undeclared success criteria, unmeasured outcomes, open
   questions, and (for Discovered missions) the confidence and confirmation status.

## 4. Required Structure

```
# Worker KPI — <name>

Worker:    <name>   (links to profile / story / review / health / economics)
Generated: <timestamp>
Mission fulfillment: <verdict> · On track? Yes|Partly|No|Unassessable · Drift? None|Mild|Material|Unknown · Mission: Declared|Discovered(<conf>)|Confirmed · Confidence: High|Medium|Low

## Mission              — Declared or Discovered; if Discovered, state confidence, evidence, and confirmation status (§9)
## Observed Reality     — what it is actually doing (cross-layer discovery)
## Expected vs Observed — alignment, gaps, drift
## Still Unknown        — undeclared criteria, unmeasured outcomes, open questions
## KPI Verdict          — on track? drifting? mission fulfilled? (mark "provisional" if mission is Discovered-unconfirmed)
```

Self-containment is mandatory (§8): restate mission and observed reality inside the artifact.

### Verdict vocabulary (use exactly these)

| Verdict | Meaning |
|---------|---------|
| **On Track (Aligned)** | Observed reality matches the mission; it is being delivered. |
| **Partially Aligned** | Core mission met, but objectives partly unmet. |
| **Drifting** | Observed reality is diverging from the mission. |
| **Stalled (not fulfilling mission)** | A mission exists (declared or discovered), but the worker is not delivering it. |
| **Mission Unconfirmed (provisional)** | Mission was Discovered, not yet PM-confirmed; the verdict stands provisionally. |
| **Unknown** | Insufficient evidence even to discover a mission. |

## 5. Evidence Sources

**Declared mission:** the worker's own intent documents. **Observed reality:** the discovery
in the other five lenses. **Discovered mission (§9):** profiles, stories, workflows, runtime
behavior, architecture, git history, configs, dependencies, and the other lenses.

## 6. Honored Evidence Limits

- **Software scope ≠ deployment scope** — for OSS/third-party workers, the upstream project's
  mission is not this deployment's; discover the *local* mission.
- **Implicit/discovered missions are weaker than declared ones** — lower confidence; flag it.
- **No outcome metrics → fulfillment is qualitative** — "on track" means "doing the mission's
  activity," not "hitting a declared target," unless criteria were stated.

## 7. Acceptance Test (the PASS gate)

A CTO can understand mission fulfillment for every worker by reading only the KPI artifacts
(and the INDEX/registry) — without reading the other lenses. For each worker they can state
what it was supposed to do, what it is doing, whether it is on track, whether it is drifting,
and what is still unknown — with the mission sourced (Declared or Discovered+confidence) and
unknowns stated. The KPI layer is **complete only when every worker has a Declared or a
Discovered mission, each with confidence and evidence** (§9).

## 8. Lifecycle

Point-in-time, append-to-history, timestamped; re-run when the mission changes (a new mission
doc, a discovery, or a PM confirmation) or observed reality diverges.

## 9. Mission Discovery & Confirmation (integral to this layer)

KPI requires a mission to compare against. Every worker must therefore have **either** a
**Declared Mission** **or** a **Discovered Mission** — never neither.

**When no mission is declared, the KPI layer does not stop at "unassessable." It runs the
discovery-and-confirmation workflow:**

1. **Discover.** Infer a candidate mission from observable evidence only — profiles, stories,
   workflows, runtime behavior, architecture, git history, configs, dependencies, and the
   other five lenses. Discovery describes what the worker *is and does*; it must not invent
   ambition the evidence cannot support.
2. **Present confidence + evidence.** Every Discovered mission carries a **confidence**
   (High/Medium/Low) and the specific **evidence** behind it. A Low-confidence discovered
   mission is a valid result; so is "the evidence cannot support any mission → the PM should
   declare one or decommission the worker."
3. **Request PM confirmation.** A Discovered mission is **provisional** until the PM confirms
   it. The PM may **Confirm** (ratify as-is), **Revise** (correct it), or **Reject** (no real
   mission — a decommission decision).
4. **Continue assessment.** KPI fulfillment is then assessed against the mission —
   **provisionally** while Discovered-unconfirmed (verdict marked provisional), and
   **definitively** once Confirmed/Revised.

**Mission provenance (record on every worker):**

| Provenance | Meaning |
|------------|---------|
| **Declared** | Stated by the owner in the worker's own docs (treated as authoritative). |
| **Discovered (provisional)** | Inferred from evidence with confidence; awaiting PM confirmation. |
| **Confirmed** | A Discovered mission the PM has ratified (or a Declared mission the PM has endorsed). |
| **Rejected** | The PM judged there is no real mission → decommission candidate. |

**The mission registry** (`reports/projects/kpi/MISSIONS.md`) records, for every worker, the
mission text, provenance, confidence, evidence, and confirmation status. It is the **stable
foundation** on which KPI, Economics, Recommendations, and future Manager Feedback operate —
those layers consume the registry's confirmed missions.

## 10. Reference Implementations

The first KPI artifacts (2026-05-31) under `reports/projects/kpi/` are the worked examples —
`quartermaster.md` and `lesia.md` (Declared missions, assessable directly);
`hdt-web.md` and `dtv-agent.md` (Discovered missions, higher confidence); and `deer-flow.md`
and `mempalace.md` (Discovered missions, Low confidence — the worked examples of discovering
a mission where none was declared, then routing it to PM confirmation). The registry
`MISSIONS.md` is the worked example of the stable-foundation output.
