# Management Briefing — Specification & Build

Status: built + delivered · 2026-05-31
Implementation: `scripts/management_briefing.py` · Cron: 09:00 Asia/Ho_Chi_Minh ·
Artifacts: `reports/briefings/YYYY-MM-DD.md`
Builds on existing intelligence only (no new scanners): the incident record, the LLM cost
ledger, the snapshot store, and the Project Profiles / INDEX.

---

## 0. The product, in one sentence

> At 09:00 every morning the CTO receives **one Telegram message** and, in 2–3 minutes,
> knows **what changed, what matters, and whether intervention is required** — without
> opening reports, incidents, profiles, or the VPS.

The Telegram message **is** the product. The markdown artifact under `reports/briefings/`
is its supporting record (operational memory).

If the CTO reads only one message today, it must answer: *what deserves attention, what can
be ignored, and what requires intervention.*

---

## 1. Management Briefing specification

**Audience:** a busy CTO managing the factory day-to-day — not an engineer.
**Budget:** readable in under 3 minutes; one screen of Telegram.
**Inputs (existing intelligence only):** incident record (`reports/incidents/index.md`),
cost ledger (`llm_events`), snapshot store (discovered projects), Project Profiles / INDEX.
**Principles:** deterministic (same data → same briefing; no LLM, no invented prose);
advisory (it recommends, the CTO decides); honest (names what is routine and what is unknown).

**Required structure** (both renderings carry all seven, in this order):

| Section | Answers | Content rule |
|---------|---------|--------------|
| **Factory Status** | "how is the factory?" | one verdict word + the headline numbers (projects, open incidents by severity, measured spend, coverage) |
| **Attention Required** | "do I need to engage today?" | YES/No + critical/high open + how many are *new since yesterday* and how many of those actually need attention |
| **Top Attention Items** | "what specifically?" | every open CRITICAL + HIGH, grouped, severity-first, decision-labelled; *(new)* tag for today's |
| **Safe To Ignore** | "what can I skip?" | self-activity (the monitor recording itself) + routine MEDIUM hygiene + "everything else" |
| **Biggest Risk** | "if I do nothing, what bites?" | the single highest-severity open event + the protective action |
| **Biggest Unknown** | "what don't we know?" | the largest evidence gap (today: unmeasured LLM spend) |
| **Manager Actions** | "what do I do?" | numbered, intervention-flagged; "None — steady state" when clean |

**Verdict word** (Factory Status): `ACTION NEEDED` if any CRITICAL open · `ATTENTION` if any
HIGH · else `STEADY`. Deterministic from the open-incident set.

---

## 2. Telegram message format

HTML parse-mode, ≤4096 chars (the client truncates safely; the real briefing is ~1.8k).
Bold section headers, severity emoji (🔴/🟠/🟡/⚪), one line per item, a closing pointer to
the full artifact. Template:

```
🏭 <b>Management Briefing — {date}</b>
<i>{weekday} 09:00 · Quartermaster</i>

<b>Factory status: {VERDICT}</b> — {N} projects · {M} open incidents ({sev pulse}) · ${spend} measured LLM spend · coverage {C}%.

<b>Attention required:</b> {YES|No} — {c} critical + {h} high open · {k} new since yesterday ({a} need attention, the rest routine).

<b>Top attention items</b>
🔴 <b>{project}</b>: {item}
🟠 <b>{subject}</b>: {item} <i>(new)</i>
…

<b>Safe to ignore</b>
• {routine class 1}
• {routine class 2}
• Everything not listed above.

<b>Biggest risk:</b> {one line + protective action}

<b>Biggest unknown:</b> {one line}

<b>Manager actions</b>
1. {action} <i>(why)</i> ⟵ <b>intervene</b>
2. {action} <i>(why)</i>
…

<i>Full briefing: reports/briefings/{date}.md · No reply needed if this all looks fine.</i>
```

---

## 3. Daily generation workflow

`scripts/management_briefing.py`, run once per day:

1. **Load** `.env` (same pattern as the daily report); take `now = UTC`.
2. **Gather** from existing stores — parse `reports/incidents/index.md` (open incidents by
   severity, today's vs carried-over); `llm_events` (total + per-project + per-provider +
   last-day spend, and which LLM projects are *instrumented*); snapshots (discovered-project
   count, excluding scan artifacts/parent dirs).
3. **Build** the deterministic briefing model: top items = every open CRITICAL + HIGH,
   grouped by (project, type) with management labels; safe-to-ignore = self-activity +
   routine MEDIUM; biggest risk = top open CRITICAL; biggest unknown = unmeasured-cost gap;
   actions = severity-led, intervention-flagged.
4. **Render** twice — Telegram HTML and the full markdown artifact.
5. **Write** `reports/briefings/{date}.md` (supporting record).

Determinism: no randomness, no LLM. Same incident record + ledger → identical briefing.

---

## 4. 09:00 delivery workflow

- **Cron (installed):**
  ```
  # CRON_TZ below affects ONLY this trailing entry — existing UTC jobs are unchanged.
  CRON_TZ=Asia/Ho_Chi_Minh
  0 9 * * * /opt/quartermaster/venv/bin/python3 scripts/management_briefing.py --send --commit >> /var/log/ai-quartermaster-briefing.log 2>&1
  ```
  09:00 is the **CTO's local time** (Vietnam, UTC+7). The server runs UTC, so `CRON_TZ` is
  set on the **last** line of the crontab so it isolates the briefing and does not shift the
  pre-existing UTC scans/reports above it.
- **Send:** `--send` calls the existing `delivery.notifications.default_telegram_sender`,
  gated on `TELEGRAM_ENABLED` + token/chat — identical to the daily report, and a no-op if
  Telegram is disabled. Failure is graceful (never breaks generation).
- **Persist:** `--commit` writes + git-commits the markdown artifact (best-effort
  `pull --rebase --autostash` then push), so every briefing is preserved in operational memory.
- **Advisory boundary:** the job only *generates, sends, and records*. It changes no
  infrastructure. The scheduled Telegram send is the authorization the PM task grants.

---

## 5. Sample briefing (generated from current VPS data, 2026-05-31)

Generated by `scripts/management_briefing.py` (dry-run). Full artifact:
`reports/briefings/2026-05-31.md`. Telegram rendering:

```
🏭 Management Briefing — 2026-05-31
Sunday 09:00 · Quartermaster

Factory status: ACTION NEEDED — 8 projects · 36 open incidents (🔴1 🟠9 🟡24 ⚪2) · $100.21 measured LLM spend · coverage 100%.

Attention required: YES — 1 critical + 9 high open · 23 new since yesterday (5 need attention, the rest routine).

Top attention items
🔴 HDT Web: OOM kill: node terminated (anon-rss 3.7 GB)
🟠 Security: API keys stored in 4 service unit file(s) — rotate & lock down (new)
🟠 Cost (unattributed): Unattributed LLM burn-rate spike(s) (new)
🟠 Lesia: LLM spend runaway — verify the budget cap held

Safe to ignore
• 13 self-activity incidents — the monitor recording its own engineering/agent/deploy activity (expected; not a fault).
• 7 world-readable .env notices (MEDIUM) — real but routine file-permission hygiene.
• Everything not listed under Top Attention or Manager Actions below.

Biggest risk: HDT Web: OOM kill: node terminated (anon-rss 3.7 GB) — the highest-severity open event; confirm the service is up and protected.

Biggest unknown: True LLM spend. Only 1 of 5 LLM systems is metered ($100.21 measured); SEO Agent, DTV Agent, Telegram HUMINT, DeerFlow bill providers with no cost on record — spend there is unknown, not zero.

Manager actions
1. Confirm HDT Web is serving and add a memory cap + auto-restart. (CRITICAL outage with no recovery policy.) ⟵ intervene
2. Confirm Lesia's overnight LLM spend stayed within its cap. (A $100 runaway already fired once.)
3. Rotate credentials exposed in 4 systemd unit files. (HIGH — secrets readable on disk.) ⟵ intervene

Full briefing: reports/briefings/2026-05-31.md · No reply needed if this all looks fine.
```

Message length: 1,816 chars (well under the 4,096 limit).

---

## 6. Validation — "would a busy CTO understand what matters today in under 3 minutes?"

**PASS.**

Walking the questions the brief poses, against the sample above:

- **What changed?** "23 new since yesterday (5 need attention, the rest routine)" — and the
  carried-over CRITICAL OOM is *not* tagged "(new)", so today's signal is separated from
  the standing backlog.
- **What matters?** Factory Status verdict (`ACTION NEEDED`) + four Top Attention lines,
  severity-ordered, each a decision-labelled one-liner.
- **What can be ignored?** A named Safe-to-Ignore block (13 self-activity + 7 routine env
  notices) so the CTO isn't alarmed by the 24 MEDIUM/2 LOW noise.
- **What requires intervention?** Two Manager Actions explicitly flagged `⟵ intervene`
  (HDT Web recovery, credential rotation); the third is a quick confirm.
- **Time:** ~1.8k chars, one screen, scannable in well under 3 minutes.

It is read without opening any report, incident, profile, or the VPS — the message stands
alone, and the artifact link is there only if the CTO wants depth.

**Honest caveats** (disclosed, not blocking): the briefing is only as complete as its
inputs — cost is a floor (one of five LLM systems metered, surfaced as the Biggest Unknown),
and incident *ownership* is sometimes `UNKNOWN` (shown as "Security"/"Cost" subjects). These
are stated in the message, not hidden.

---

## 7. Success criteria — met

At 09:00 daily the CTO receives one Telegram message conveying **what changed, what matters,
and whether intervention is required**, generated automatically and deterministically from
existing intelligence and delivered automatically via cron — no report-reading or VPS access
required. Reverting is a one-line crontab removal; the generator is read-only/advisory.
