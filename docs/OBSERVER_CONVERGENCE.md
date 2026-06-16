# Observer Convergence — the Observer's operating philosophy & success metric

Status: active · Version 1.0 · 2026-05-31
Parent: [`UNDERSTANDING_ERA.md`](../UNDERSTANDING_ERA.md) (wins on purpose conflicts). This
document governs **how the Observer holds its conclusions** across every understanding output
(Profiles, Stories, Reviews, Health, Economics, KPI, Missions).

---

## 1. The Observer maintains Current Understanding, not Absolute Truth

The system is an **Observer**. Its job is not to be right; its job is to **become less wrong
over time**.

**Wrong model:**

> Observe → Understand → Complete knowledge

**Right model:**

> Observe → Discover → Realize mistakes → Correct understanding → Improve the factory map

Understanding is **never complete**. It is a *current best model* of the VPS, held with
explicit uncertainty, and continuously revised as evidence arrives. A conclusion that is later
proven wrong and corrected is **the system working as designed** — not a failure.

> Workers perform work. Managers make decisions. **The Observer maintains understanding.**

## 2. The Observer's KPI is convergence speed, not accuracy

The Observer is **not** measured on "% correct." It is measured on:

> **How quickly does it discover and correct its own mistakes?**

A healthy Observer continuously *reduces*:

- **Unknowns** — things it cannot yet answer.
- **False assumptions** — beliefs not grounded in current evidence.
- **Coverage gaps** — systems/workers it has not yet observed.
- **Misclassifications** — conclusions contradicted by new evidence.
- **Blind spots** — areas it does not know it isn't watching.

Reducing these — fast — is success. Surfacing a *new* unknown is also success (a blind spot
became a known gap). The metric is movement toward a less-wrong map, tracked in the
[Understanding Revision Log](../reports/projects/REVISIONS.md).

## 3. Every conclusion carries its uncertainty (the metadata standard)

Every understanding conclusion — in any lens — should be expressible with five fields. New and
regenerated artifacts must carry them; older artifacts are retrofitted as they are revisited.

| Field | Meaning |
|-------|---------|
| **Confidence** | High / Medium / Low — how strongly the evidence supports the claim. |
| **Evidence** | The specific, observable basis (paths, processes, configs, ledger rows…). |
| **Last verified** | The date the claim was last checked against live evidence (freshness). |
| **Contradictions found** | Evidence seen that conflicts with the claim (empty if none yet). |
| **Revision history** | Prior conclusions and why they changed ("believed X → evidence → now Y"). |

A conclusion with no `Last verified` is *stale until re-checked*; a conclusion with open
`Contradictions found` is *under revision*.

## 4. The belief-revision protocol (the Observer is allowed to be wrong out loud)

When new evidence contradicts a held conclusion, the Observer states it plainly and updates —
it does not hide the change:

> **"I believed X."** — the prior conclusion + its confidence.
> **"New evidence suggests Y."** — the contradicting evidence.
> **"Understanding updated."** — the new conclusion + confidence + last verified.

Each such update is appended to the [Understanding Revision Log](../reports/projects/REVISIONS.md)
and surfaced as an "Understanding updated" banner on the affected artifact, with the superseded
conclusion **retained** as revision history (never silently overwritten).

This applies to the Observer's own mistakes too: an over-claim it wrote (e.g. an unverified
detail) is retracted on evidence and logged, exactly like any other revision.

## 5. Mechanisms

- **[`reports/projects/REVISIONS.md`](../reports/projects/REVISIONS.md)** — the factory-wide,
  append-only Understanding Revision Log: every belief change, retraction, coverage gap opened,
  and misclassification corrected, with a convergence scoreboard.
- **Per-artifact "Understanding updated" banners** — when a lens conclusion is superseded, a
  banner records *previously → now → evidence → last verified* and links the revision log.
- **Living Understanding freshness** ([`LIVING_UNDERSTANDING.md`](LIVING_UNDERSTANDING.md)) —
  re-verifies conclusions when their underlying evidence changes, feeding `Last verified` and
  surfacing contradictions automatically (the path toward Month-12 auto-detection).
- **Mission Discovery + confirmation** ([`WORKER_KPI_SPEC.md`](WORKER_KPI_SPEC.md) §9) — an
  example of converging on a worker's mission rather than declaring it unknowable.

## 6. The desired trajectory (convergence, not perfection)

| Horizon | Factory map |
|---------|-------------|
| **Day 1** | Incomplete — many unknowns, low confidence, coverage gaps. |
| **Month 1** | Mostly correct — major workers profiled, big misclassifications caught. |
| **Month 6** | Highly reliable — confidence high where evidence is strong; gaps named. |
| **Month 12** | Self-correcting — detects new systems, mission drift, hidden dependencies, and stale assumptions **automatically** — not because it became perfect, but because it continuously observes, questions itself, and updates. |

## 7. Worked example (the canonical convergence story)

> **Memory Palace.** *Week-1 belief:* "Dormant / inert / negligible" (Low confidence — based on
> the empty `/srv/mempalace/{crawler,seo}` stores). *Later evidence:* `mempalace` is an
> installed v3.0.0 package with a **populated** store at `/root/.mempalace/palace/chroma`, read
> and written by SEO Agent, with its venv running two services. *Understanding updated:* "Active,
> populated shared-memory dependency" (High confidence). **The earlier conclusion was wrong; the
> correction is the success.** Logged in REVISIONS.md; banners added to the affected lenses.

This is what every conclusion in this system is allowed — and expected — to do.
