# Factory Coverage Specification — `reports/projects/COVERAGE.md`

Status: active · Version 1.0 · 2026-05-31
The **Eyes** of the system. Where the six worker lenses (Profile/Story/Review/Health/Economics/
KPI) answer *understanding*, Factory Coverage answers a prior, simpler question:

> **"What exists in the factory right now?"** — with confidence.

The goal is **visibility, not understanding.** A trustworthy factory map must first know *what
is there* before any lens explains it. If the system cannot list what exists with high
confidence, the Eyes are incomplete.

---

## 1. What Factory Coverage Is (and is not)

- **It is** a complete, evidence-based **inventory** of detected systems, each tagged with how
  well it is *managed* (represented by the six lenses) — so coverage gaps are visible.
- **It is not** a recommendation engine, a mission review, an Observer mechanic, or automation.
  It is the census that those depend on.

One report: `reports/projects/COVERAGE.md`. It is a **living map** governed by
[`OBSERVER_CONVERGENCE.md`](OBSERVER_CONVERGENCE.md): incomplete is expected, confidence is
explicit, and it gets less wrong over time.

## 2. Discovery Sources (sweep at least these)

Running processes · systemd services · Docker containers · open ports · nginx routes · cron
jobs · git repositories · databases · queues · active applications · long-running scripts.

**Evidence rule:** every entry cites the source(s) it was detected from. **Do not infer
ownership without evidence** — owner is `Unknown` unless a git author, domain, config, or
service account proves it.

## 3. Per-System Fields

| Field | Meaning |
|-------|---------|
| **Name** | Best identifier (service/container/process/domain). |
| **Type** | application / service / database / queue / proxy / object-store / search / script / data-artifact. |
| **Purpose** | If known (from evidence); else `Unknown`. |
| **Confidence** | High / Medium / Low — in the identification itself. |
| **Owner** | Only if evidenced (git author, domain, service user); else `Unknown`. |
| **Runtime status** | running / stopped / failed / down / N-A (passive). |
| **Management status** | see §4. |

## 4. Management Status

| Status | Definition |
|--------|------------|
| **Fully Managed** | Represented by all six lenses (Profile + Story + Review + Health + Economics + KPI). |
| **Partially Managed** | Some lenses exist, or it is named in the registry but not fully covered. |
| **Unmanaged** | It exists but has no lens representation. |
| **Unknown** | Detected but not yet identified (cannot even be named/located with confidence). |

## 5. Coverage Report Structure

`COVERAGE.md` contains:

1. **Detected-systems master table** — every system, all fields.
2. **Managed Inventory** — systems with the full six-lens set.
3. **Unmanaged Inventory** — systems that exist but are unrepresented.
4. **Unknown Inventory** — systems detected but not yet identified.
5. **Coverage Score** — a *visibility measure* (not a KPI): Known vs Detected, and Managed vs
   Detected, **with confidence**, plus the honest caveat that discovery is itself incomplete
   (the score is a floor).
6. **Requires Investigation** — the unknowns and anomalies a CTO should chase next.

## 6. Coverage Score (a visibility measure, not a KPI)

Report, with confidence:
- **Detected systems** (N) — distinct systems found across the sources.
- **Identified** (named + located) vs detected → *identification visibility*.
- **Fully Managed** vs detected → *management coverage*.
- **Unknown** count → the blind-spot residue.

It is a measure of *how much of the factory the Eyes can see*, not a performance grade.
Improving it means reducing Unknowns and Unmanaged over time (convergence), not hitting 100%.

## 7. Acceptance Test

A CTO, reading only `COVERAGE.md`, can answer: **what systems exist? which are managed? which
are unmanaged? which are unknown? which discoveries require investigation?** — without opening
any other lens.

## 8. Lifecycle

Point-in-time, timestamped, append-to-history; re-run when the sweep changes (new
process/container/port/route/repo). Each system row carries a confidence; the report carries a
`Last verified` and links new identifications/corrections to [`REVISIONS.md`](../reports/projects/REVISIONS.md).
