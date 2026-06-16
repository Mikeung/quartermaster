# Example output (synthetic)

> Illustrative only — the data below is **fabricated** to show the shape of what
> Quartermaster produces. Real output is generated from evidence on your own box.

## Cost advisor — agent API spend

_Advisory only — observes and explains spend; never throttles, pauses, or spends._

### Whole view — total spend per provider

**Total observed spend: $312.40**

| Provider | Spend | Source | Confidence |
|---|---|---|---|
| anthropic | $188.10 | provider_account_usage | High |
| openai | $121.30 | provider_account_usage | High |
| google | $3.00 | self_reported_ledger — no per-key account-usage API | Medium |

### Attribution — bound to agents by evidence

Attributed **$268.40** · Unattributed **$44.00**.

| Agent | Spend | Basis | Confidence | Evidence |
|---|---|---|---|---|
| `research-worker` | $188.10 | key_1to1 | High | anthropic key …a1b2 labelled 1:1 → research-worker |
| `summarizer` | $77.30 | agent_self_logged | Medium | summarizer logged this spend itself (412 events) |
| `ingest-bot` | $3.00 | agent_self_logged | Medium | ingest-bot logged this spend itself (impl) |

### Unattributed bucket — openai key …e5f6 — $44.00

- **Why unattributed:** unlabelled provider key — owner not declared.
- **Investigation (Medium confidence):** one on-box process (`python3.12`, pid 4242)
  held an outbound connection to openai while this spend clustered (2026-06-14 →
  2026-06-15). A candidate, not a confirmation.
- **Resolutions:**
  - **label_key_once** — if you know whose key …e5f6 is, label it once in
    `config/cost_advisor.yml` and run `scripts/load_cost_keys.py`. The mapping
    becomes sticky; all future spend attributes automatically.
  - **isolate_agent_key** — if it's shared, give the agent its own key so spend
    separates cleanly.

### Budget (human-declared)

Monthly `all` budget **$400.00** · spent **$312.40** (78%) → **ok** (warns at 80%).

---

## Incident — runaway agent cost (P0)

**Runaway cost: `research-worker.nightly_crawl` = $96.40 (74%) over 9.2h**

- **PROJECT CONTEXT:** research-worker — overnight web-research crawler (LLM-driven).
- **WHO:** research-worker · owner: data-team
- **COST:** $96.40 · burn $10.48/hr · claude-sonnet-4
- **WHY:** one workflow dominated spend across a long uninterrupted run.
- **SO WHAT:** unbudgeted overnight burn; confirm it was intended.
- **What to check next:**
  1. Was the nightly crawl supposed to run this long? (`journalctl -u research-worker`)
  2. Is there a loop/retry storm inflating calls? (per-call ledger in `data/spend/`)
  3. Consider a budget cap or kill-switch for this workflow.

_Advisory only — operational decisions require human review._
