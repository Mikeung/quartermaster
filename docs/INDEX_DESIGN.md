# INDEX Redesign — From First Principles

Status: design proposal · 2026-05-31
Purpose: define **what the INDEX should be** for a Day-0 operator. Concretizes
[`INDEX_VISION.md`](INDEX_VISION.md) into a section-by-section design, informed by the
failed Day-0 audit (`reports/reality_check/2026-05-31_day0_index_review.md`).
Scope: operator understanding only. No implementation, architecture, scanners, or data
sources are discussed — only the information a newcomer needs and the order they need it.

Audience lens throughout: **CTO · Operator · Investor · Acquirer.** Not a developer's
table of contents.

---

## 1. Design Critique — why start from zero

The current INDEX behaves like a **directory**: an alphabetical list of profiles with a
"how to read" footnote. A directory assumes the reader already knows what they're looking
for and just needs to find it. **A Day-0 operator knows nothing and needs to be told what
to look for.** That is a different document.

The Day-0 audit showed the consequences: of the eight questions a newcomer must answer,
five were unanswerable from the INDEX (cost, health, importance, what-to-investigate,
what-to-read-next) and three only partial. The failure was not detail — the three
profiles it pointed to were strong — it was the **absence of an orientation layer**:
nothing was ranked, no money was shown, no danger was surfaced, no starting point was
given.

So the redesign reframes the artifact entirely:

> **INDEX is not a directory. INDEX is an executive briefing.**

An executive briefing leads with the conclusion, triages by importance, puts money and
risk near the top, is honest about what it doesn't know, and ends by telling the reader
exactly where to go next. Everything else in the repository — profiles, incidents, daily
reports — becomes **supporting documentation** that the briefing routes you to.

The briefing must survive three reading depths:
- **10 seconds** — the banner: one line on the state of the VPS.
- **30 seconds** — the bottom line: the single most important thing, the biggest risk, the biggest cost, the biggest unknown.
- **5 minutes** — the full briefing: own → important → money → health → unknown → where to start.

If the reader stops at any depth, what they've read is the *most important thing they
could have read in that time.* That is the inverted-pyramid test.

---

## 2. Design Principles

1. **Conclusion first.** Lead with the verdict, not the inventory. The reader earns
   detail by reading further; they should never have to assemble the headline themselves.
2. **Triage over completeness.** Rank everything by importance. An unranked list is the
   reader's problem to solve; a ranked list is the briefing doing its job.
3. **Money and danger ride at the top.** A CTO, investor, and acquirer all reach for cost
   and risk first. These get dedicated, scannable views — never buried in prose.
4. **Honest about the unknown.** State coverage, confidence, and gaps plainly. For an
   acquirer doing due diligence, "what we cannot yet explain" is as important as what we
   can. Silent omission reads as false completeness.
5. **Route, don't detail.** The INDEX summarizes and points. Depth lives in profiles and
   incident reports. Every number and flag links to where to read more.
6. **Scannable, not prose.** Flags, tiers, counts, and short lines — not paragraph cells.
   The 5-minute budget is a hard constraint on shape, not just length.
7. **One page.** If it doesn't fit on a page a newcomer can read in 5 minutes, it isn't
   the first page.

---

## 3. Proposed INDEX Structure

The briefing, top to bottom. Each section is ordered by *what a newcomer needs first*,
not by what is easiest to produce.

```
┌─ BANNER ───────────────────────────────────────────────── (10-second read)
│  VPS <scope> · generated <when> · N projects · M services · ~$X/day ·
│  ⚠ K open incidents (1 CRITICAL) · coverage P% · confidence summary
├─ THE BOTTOM LINE ──────────────────────────────────────── (30-second read)
│  3–5 sentences: most important system · biggest risk · biggest cost ·
│  biggest unknown · the one thing to do first.
├─ 1. WHAT I OWN ─────────────────────────────────────────────────────────
│  Inventory at a glance: projects (profiled / total), services, agents,
│  external dependencies, providers. Plus an honest coverage line.
├─ 2. WHAT MATTERS MOST ──────────────────────────────────────────────────
│  Priority-ranked project list. Per row: one-line "what it is" · criticality
│  tier · health flag · cost flag · owner · → profile link.
├─ 3. WHAT'S COSTING MONEY ───────────────────────────────────────────────
│  Total spend + trend · biggest spender · by project / by provider ·
│  unattributed spend called out. → cost detail / incidents.
├─ 4. WHAT'S UNHEALTHY ───────────────────────────────────────────────────
│  Open incidents by severity; CRITICAL/HIGH named with the at-risk system.
│  → incident reports.
├─ 5. WHAT'S UNKNOWN ─────────────────────────────────────────────────────
│  Undiscovered/unprofiled projects · unattributed cost · low-confidence
│  attributions · what the system cannot yet explain.
└─ 6. WHERE TO START ─────────────────────────────────────────────────────
   A numbered, prioritized list: investigate first → read next, each with a
   one-line reason and a link.
```

This is a layout of *information*, not a schema. The redesign claims only that these are
the things a Day-0 reader needs and the order they need them in.

---

## 4. Section-by-Section — what, why, and which question it answers

### Banner (the 10-second read)
- **What it contains:** the VPS scope, when the briefing was generated, and the four
  numbers that define the situation — how many projects, how many services, roughly how
  much it costs per period, and how many open incidents (with the worst severity called
  out) — plus a coverage/confidence figure.
- **Why it exists:** a newcomer's first need is a frame — *how big is this and is it on
  fire?* One line gives them that before they read anything else.
- **Questions answered:** **Q1 (what do I own)** at a glance, and a first signal toward
  **Q4 (unhealthy)** via the incident count.
- **Per audience:** CTO sizes the estate; investor/acquirer get scale and a risk pulse;
  operator learns instantly whether to panic.

### The Bottom Line (the 30-second read)
- **What it contains:** 3–5 plain sentences naming the single most important system, the
  biggest risk, the biggest cost, the biggest unknown, and the one thing to do first.
- **Why it exists:** the briefing must state its own conclusion. A reader who has only 30
  seconds should still leave with the right mental model, not a list to interpret.
- **Questions answered:** **Q2 (what is important)**, and previews **Q3, Q6, Q7**.
- **Per audience:** this is the paragraph an executive forwards. CTO gets the verdict;
  investor gets the thesis; acquirer gets the headline risk; operator gets their first move.

### 1. What I Own
- **What it contains:** an inventory snapshot — number of projects (profiled vs. total),
  services, agents, external dependencies and providers — with an explicit coverage line
  ("N of M projects explained; discovery known-incomplete").
- **Why it exists:** you cannot reason about an estate you can't count. This converts
  "some stuff is running" into a bounded inventory.
- **Questions answered:** **Q1 (what do I own).**
- **Per audience:** acquirer/investor get the asset inventory; CTO gets the surface area;
  operator gets the scope of their new responsibility.

### 2. What Matters Most
- **What it contains:** the projects, **ranked by importance**, one scannable row each:
  a one-line "what it is", a criticality tier, a health flag, a cost flag, the owner, and
  a link to the full profile.
- **Why it exists:** this is the heart of the briefing — it does the triage the reader
  cannot do themselves. Ranking *is* the value; a flat list would just relocate the work.
- **Questions answered:** **Q2 (important), Q5 (critical)**, and at-a-glance **Q3 (cost)
  and Q4 (health)** via the flags.
- **Per audience:** CTO sees where the business value and risk concentrate; investor sees
  the crown jewels; acquirer sees dependency and bus-factor signals; operator sees what to
  protect.

### 3. What's Costing Money
- **What it contains:** total spend and trend, the biggest spender, a breakdown by project
  and by provider, and any **unattributed** spend explicitly flagged.
- **Why it exists:** cost is a first-order question for every non-developer audience and
  was completely invisible in the failed INDEX. Money surprises are how operators get
  burned; this makes spend legible in one glance.
- **Questions answered:** **Q3 (what is costing money).**
- **Per audience:** CTO/finance see the run-rate; investor sees unit economics; acquirer
  sees liabilities and the quality of cost attribution; operator sees what to watch.

### 4. What's Unhealthy
- **What it contains:** open incidents summarized by severity, with the CRITICAL and HIGH
  ones named alongside the system they put at risk; links to the full incident reports.
- **Why it exists:** a newcomer must learn *immediately* if something is broken. In the
  failed INDEX a CRITICAL outage was a parenthetical; health deserves its own view.
- **Questions answered:** **Q4 (what is unhealthy).**
- **Per audience:** operator gets the on-call picture; CTO gets the risk register;
  acquirer gets the "what's currently on fire" disclosure.

### 5. What's Unknown
- **What it contains:** what the system has *not* explained — undiscovered or unprofiled
  projects, unattributed cost, low-confidence attributions, and anything it cannot yet
  account for.
- **Why it exists:** trust comes from declared limits. An honest briefing distinguishes
  "this is safe" from "we haven't looked here yet." Hiding gaps would make the page lie by
  omission.
- **Questions answered:** **Q6 (what is unknown).**
- **Per audience:** acquirer gets due-diligence honesty (the single most important
  audience for this section); CTO learns where the blind spots are; operator learns what
  not to assume is safe.

### 6. Where to Start
- **What it contains:** a short, **numbered, prioritized** list — investigate first, then
  read next — each item one line with the reason and a link (e.g. "1) the CRITICAL
  incident — a service is down; 2) the highest cost+criticality profile; 3) …").
- **Why it exists:** understanding must convert into action. The briefing's last job is to
  hand the reader a path so they never have to ask "okay… now what?"
- **Questions answered:** **Q7 (investigate first) and Q8 (read next).**
- **Per audience:** every audience gets a guided route; this is what makes INDEX *the
  first page* and everything else supporting documentation.

---

## 5. Success-Criteria Mapping

| Day-0 question | Answered by |
|----------------|-------------|
| 1. What do I own? | Banner + §1 What I Own |
| 2. What is important? | Bottom Line + §2 What Matters Most |
| 3. What is costing money? | §3 What's Costing Money (flagged in §2) |
| 4. What is unhealthy? | Banner pulse + §4 What's Unhealthy (flagged in §2) |
| 5. What is critical? | §2 What Matters Most (criticality tier) |
| 6. What is unknown? | §5 What's Unknown |
| 7. What should I investigate first? | §6 Where to Start |
| 8. What should I read next? | §6 Where to Start |

Every question now has a home, and the reading order (banner → bottom line → own →
important → money → health → unknown → where to start) matches the order a newcomer's
attention actually moves: *how big, how bad → what matters → money & danger → blind spots
→ go here next.*

---

## 6. What INDEX Is NOT (after this redesign)

- **Not a directory.** It does not list profiles for you to browse; it tells you which one
  to open and why.
- **Not a dashboard.** No live metrics or charts to monitor — it is a briefing you read
  once on arrival and re-read when the estate changes.
- **Not detail.** It never explains a project in full; that is the profile's job. The
  INDEX is breadth and triage; profiles are depth.
- **Not exhaustive.** It deliberately shows the most important things, names what it
  omits, and routes elsewhere for the rest.

---

## 7. Definition of Done

A new CTO who has never seen this VPS reads **only** the INDEX and, within 5 minutes, can
answer all eight Day-0 questions and state which document to open first. At that point the
INDEX is the first page anyone reads, and profiles, incidents, and reports are the
supporting documentation it routes them to.
