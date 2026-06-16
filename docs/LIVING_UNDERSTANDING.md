# Living Understanding — Keeping INDEX & Project Profiles Current

Status: design proposal · 2026-05-31
Scope: how the **INDEX** and **Project Profiles** stay synchronized with VPS reality, so an
operator always reads *current* understanding, not *historical* understanding. Constrained
to those two artifacts. No redesign of their format; no new understanding concepts; no new
health/drift/cost/recommendation features — this reuses the change-detection the system
already has. See [`UNDERSTANDING_LAYER_MVP.md`](UNDERSTANDING_LAYER_MVP.md),
[`PROJECT_PROFILE_SPEC.md`](PROJECT_PROFILE_SPEC.md), [`INDEX_DESIGN.md`](INDEX_DESIGN.md).

---

## 1. Living Understanding — the core idea

> **An understanding artifact is stale when the evidence it was generated from is no longer
> the latest evidence.**

Everything follows from that one sentence, because the system already:

- stores **append-only, timestamped snapshots** per project (`snapshots`, `scanned_at`, `project_id`),
- computes **drift** between snapshots (`memory/drift_detector.py`, `systemic_drift.py`, `DRIFT_SPEC.md`, `drift_X_to_Y` reports),
- tracks **git activity** per project (`scanners/git_activity_scanner.py`, `cognition/project_activity.py`),
- records **incidents** with project + `last_seen` (`memory/finding_store.py`, `reports/incidents/`),
- keeps a **cost ledger** (`memory/llm_store.py`, `llm_events`),
- holds **durable ownership/purpose** in the registry (`config/project_context.py`),
- runs a **periodic scan** already (`scripts/scheduled_scan.py`) and **auto-commits reports**.

So Living Understanding is not new machinery. It is: **stamp each artifact with the
evidence baseline it was built from, then on each scan compare current evidence to that
baseline using the detectors that already exist, and surface the result.**

### Two structural facts that shape the design

1. **INDEX is derived from {Project Profiles} + three aggregate signals** — the
   discovered-project set, the incident-severity set, and the cost ledger. So the INDEX is
   stale whenever *any* profile changes, *or* any of those three aggregates changes.
2. **Not every change is answer-changing.** A new commit arrives constantly but rarely
   changes the WHEN *answer* ("active daily since April"). Triggers must fire on
   **answer-changing deltas**, not raw evidence churn — otherwise the artifacts thrash. The
   one dimension that is intrinsically continuous (WHEN) is *recomputed* on regeneration,
   never treated as a staleness alarm.

---

## 2. What makes each dimension change — and which existing capability sees it

This is the heart: each question is sourced from specific evidence; the system already has
a detector for a change in that evidence.

| Dimension | Evidence it rests on | "It changed" signal | Existing capability | Volatility |
|-----------|----------------------|---------------------|---------------------|-----------|
| **WHO** | git authors, service `User=`, auth allow-domain, registry owner | a new commit author appears; registry owner edited; new user/auth in repo scan | `git_activity_scanner` (authors), `project_context.py`, repo scan delta | Low |
| **WHAT** | frameworks, language, `llm_sdks`, capabilities, entry points | drift in LLM/framework/docker/CI/language; new/removed entry point | **`drift_detector`** (exactly these classes), snapshot repo-scan delta | Low–Med |
| **WHY** | README/docs content, registry purpose | README/docs content-hash changes; registry purpose edited | snapshot file fingerprint, `project_context.py` | Very low (most durable) |
| **WHERE** | services, ports, DBs, env-key providers, domains, compose | new/removed service or port; new provider key; new DB; compose/unit change | drift (docker/CI), `service_scanner` ports, repo-scan `env_files`/`llm_sdks` delta | Medium |
| **WHEN** | last commit, activity window, last scan | *always* moving — recompute, don't alarm; alarm only on **pattern shift** (active→dormant or dormant→active) | `git_activity_scanner` / `project_activity` (runs every scan) | Continuous |
| **WHAT IF** | dependencies (from WHERE) + incidents + cost | new HIGH/CRITICAL incident for the project; dependency added/removed; runaway cost | `finding_store` (severity + project + `last_seen`), `llm_store`, WHERE deltas | Event-driven |

Read it as: *change in column 3, detected by column 4, invalidates that dimension's answer.*

---

## 3. Regeneration triggers — what refreshes the profile, the INDEX, or both

| Trigger (answer-changing) | Detected by (existing) | Profile | INDEX | Both |
|---------------------------|------------------------|:------:|:-----:|:----:|
| Project's snapshot drifts (WHAT/WHERE) | `drift_detector` | ✅ | — | if it changes a §2 flag → ✅ |
| New commit author / ownership change (WHO) | git_activity / registry | ✅ | — | if it changes §2 owner → ✅ |
| README/docs/purpose change (WHY/WHAT) | file fingerprint / registry | ✅ | — | — |
| New service / port / provider / DB (WHERE) | service_scan / repo-scan delta | ✅ | banner ~services, §3 providers | ✅ |
| Activity pattern shift active↔dormant (WHEN) | project_activity | ✅ | §2 ranking input | ✅ |
| New HIGH/CRITICAL incident for a project (WHAT IF) | finding_store | ✅ | §4 + §2 flag + bottom line | ✅ |
| New project discovered / project removed | snapshot project-set delta | ✅ (new profile) | §1 inventory + §2 ranking + coverage | ✅ |
| New cost / new spender / runaway | llm_store / economic finding | (WHAT IF) | §3 + banner + bottom line | ✅ |
| Incident severity set changes (any project) | finding_store | — | §4 + banner counts | — |

**Rule of thumb:** *profile-only* = a single project's intrinsic facts changed.
*INDEX-only* = an aggregate (incident set, cost, counts) changed without changing a profile's
text. *Both* = a change that alters both a project's answer **and** how the INDEX ranks/flags
it (the common case for new services, new incidents, and newly-discovered projects).

INDEX regenerates from the profiles, so the order is always: **refresh affected profiles →
then regenerate INDEX** from the current profile set + the three aggregates.

---

## 4. Freshness indicators (it IS current)

Freshness is **recency of verification, not recency of generation.** An artifact untouched
for 30 days but checked against evidence an hour ago — with no change — is fresh.

A profile / INDEX is fresh when:

- It carries a **baseline stamp**: the source scan id + `scanned_at` it was generated from
  (INDEX also stamps the incident-set and cost-ledger state).
- A **last-verified stamp** ≥ the most recent scheduled scan, with verdict "evidence
  unchanged since baseline."
- For INDEX: the discovered-project set, incident-severity set, and cost ledger all match
  the values in the briefing.

Surface as a one-line header: `Verified CURRENT against scan #560 @ 2026-05-31 12:00 — no answer-changing evidence since Generated.`

## 5. Staleness indicators (it is OUT OF DATE)

A profile / INDEX is stale when any of:

- **Drift since baseline** — `drift_detector` reports a WHAT/WHERE change after the baseline scan.
- **Answer-changing delta** in any §2 row of the trigger table above.
- **New evidence after `Generated`** — a new commit author (WHO), a HIGH/CRITICAL incident
  for the project (WHAT IF), a new provider/service (WHERE), or an activity pattern shift (WHEN).
- **Discovered-set mismatch** (INDEX) — a project exists that has no profile, or a profiled
  project no longer scans.
- **Heartbeat exceeded** — not verified within a max-age window (e.g. one scan cycle), so
  even "no change" must be re-confirmed rather than assumed.

Surface, per dimension, *which* answer drifted: `STALE — WHERE changed (new service :9100) and WHAT IF changed (new HIGH incident) since 2026-05-31 12:00.`

## 6. Trust indicators (how much to believe it)

Trust = **existing Confidence × freshness × attribution basis.** No new confidence concept —
it composes the per-section Confidence the profiles already carry with two time/again facts:

- **Confidence** (High/Medium/Low) — already in every section.
- **Evidence age / last-verified** — a High-confidence answer built on 30-day-old, unverified
  evidence is less trustworthy than the same answer verified today; show both.
- **Attribution basis** — whether a load-bearing fact is inferred (e.g. OOM→HDT Web,
  :8001→DeerFlow are Medium runtime inferences; the registry records `basis`/`confidence`).

A useful one-line trust read per row: `High confidence · verified today · direct evidence`
vs `Medium confidence · 23 days stale · inferred ownership`.

---

## 7. The smallest viable approach

The true MVP is three additions, all reusing existing infrastructure, changing **no**
artifact format and adding **no** new understanding concept:

1. **Baseline stamp.** When a profile/INDEX is generated, record the evidence baseline in
   its header — the source `snapshot.id` + `scanned_at` (INDEX also stamps the incident-set
   hash and cost-ledger total). Profiles already have a `Generated` line; this extends it.

2. **Staleness check on the scan that already runs.** Inside `scheduled_scan.py`'s existing
   cycle, for each project compare current evidence to its baseline using detectors that
   already exist — `drift_detector` (WHAT/WHERE), `git_activity_scanner` (WHO/WHEN pattern),
   `finding_store` new HIGH/CRITICAL (WHAT IF), repo-scan provider/service delta (WHERE),
   and the discovered-project-set delta (INDEX). Emit a per-artifact verdict
   `CURRENT | STALE[dims]` into a small `reports/projects/STATUS.md` ledger **and** the
   one-line header on each artifact. This alone satisfies the success criterion: opening
   INDEX shows whether it reflects current reality and which parts drifted.

3. **Regeneration policy (advisory-safe).** When an *answer-changing* trigger (§3) fires,
   regenerate the affected profile(s), then the INDEX, deterministically from current
   evidence — exactly as incident/daily reports already auto-generate and auto-commit, so
   the change lands as a reviewable git diff (operational memory), never as a mutation of
   infrastructure. WHEN-only churn does **not** trigger regeneration; it is recomputed when
   some other trigger already fires, or refreshed on the heartbeat. (If a lighter first step
   is wanted, ship 1+2 only — detect-and-flag — and keep regeneration a human-approved action.)

What this explicitly does **not** add: no new scanners, no new drift classes, no new
health/cost/recommendation surfaces, no format changes. It is a thin synchronization loop
over capabilities the system already runs every scan.

---

## 8. Answering the brief's questions directly

- **How does the system know INDEX is outdated?** The discovered-project set, incident-severity
  set, or cost ledger no longer matches the INDEX's baseline stamp — or any underlying profile
  regenerated. All three aggregates already exist in the stores.
- **How does it know a Profile is outdated?** The project's latest snapshot drifts from the
  profile's baseline snapshot, a new commit author/incident/provider appears after `Generated`,
  or its activity pattern shifts — all via existing detectors.
- **WHO/WHAT/WHY/WHERE/WHEN/WHAT-IF changed?** Detected per the §2 evidence→signal→detector map.
- **What evidence triggers regeneration?** The answer-changing deltas in §3 (not raw churn).
- **What requires profile / INDEX / both?** The three columns of the §3 table; in short:
  intrinsic project change → profile; aggregate change → INDEX; service/incident/discovery
  change → both.

---

## 9. Success test

At any moment, an operator opening INDEX sees a verdict line stating it was verified current
against the latest scan — or exactly which projects/dimensions have drifted since it was
generated. They are therefore always reading **current VPS reality, or an explicit warning
that part of it has aged** — never silently reading history.
