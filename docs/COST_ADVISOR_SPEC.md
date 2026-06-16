# Cost Advisor — Agent API-Spend Advisor (the Economics slot)

**Status:** implemented 2026-06-15. Advisory-only, deterministic, evidence-cited,
opt-in. It observes and explains spend; it **never throttles, pauses, or spends**,
and it **never raises** — every collector degrades to a stated reason.

## What it answers

1. **Whole view (headline).** Total spend per provider, each tagged with its
   **source** and **confidence**: `provider_account_usage` (the authoritative
   number the provider will bill) > `self_reported_ledger` (what an agent logged
   about itself). The operator always knows how trustworthy each number is.
2. **Runaway / spike → money-critical.** Reuses the existing economic detector
   (`observability/economic.py`) and the existing money finding types
   (`spend_spike`, `runaway_agent_cost`, `abnormal_burn_rate`,
   `unknown_cost_owner`). These are intrinsic-critical in `cognition/push_policy.py`,
   so they route through the real-time push category and page fast, not at the digest.
3. **Trend + budget.** Spend over time + direction. Budget is **human-declared**
   (`config/cost_advisor.yml`): warn as approached (`budget_approaching`, P1),
   money-critical when exceeded (`budget_exceeded`, P0/intrinsic).

## Attribution — by evidence already on the box

Per provider, in precedence order:

- **Account usage with a per-key split** → attribute via **1:1 key labels**
  (`key_1to1`, High confidence). The operator declares a key→agent label once
  (`config/cost_advisor.yml` → `scripts/load_cost_keys.py`). The binding is
  `human_declared` and **sticky** — reconciliation never overwrites it (enforced
  by the `graph_store` invariant). Labelling a key is a **one-time tag, NOT a new key**.
- **Agent's own parseable ledger** (`data/spend/`, project_id) →
  `agent_self_logged`, Medium confidence.
- **Everything else → honestly "Unattributed."** WHO is never guessed.

Spend is bound to graph nodes: an attributed agent → its `repo:<agent>` node; a
labelled key → a `key:<provider>:<key_id>` node with an `ATTRIBUTED_TO` edge.

## Unattributed → investigable (recommendations-layer pattern, on money)

For each Unattributed bucket ≥ `UNATTRIBUTED_INVESTIGATE_MIN_USD`,
`cognition/cost_investigation.py` surfaces only what the evidence supports:

- which **key** spent it, **when** the spend clustered;
- which on-box **process** was calling that provider then — correlated from
  active outbound connections (`economics/connection_evidence.py`, read-only `ss`)
  + the process→agent registry (`config/project_context.py`);
- narrowed to **candidates with a confidence** (connection snapshots are
  point-in-time, provider spend is day-granular → never "High" from this alone,
  never a fabricated single owner).

Two deterministic resolutions:

- **`label_key_once`** — tag the key in `config/cost_advisor.yml`; it becomes
  `human_declared` and sticky.
- **`isolate_agent_key`** — for a shared key, give the agent its own key so spend
  separates and can be attributed with confidence.

## Provider account usage — key safety (hard line)

`economics/provider_usage.py` reads usage with a **usage-scoped key from env ONLY**
(var names in `config.observability_config.PROVIDER_USAGE_KEY_ENV`). The key value
is **never logged, never returned, never stored** — only a last-4 `key_hint` ever
leaves the module, and errors are scrubbed of the secret. With no key configured
(the current state), the provider view degrades to "unavailable" and the advisor
falls back to the self-reported ledger. The HTTP fetcher is injectable (testable
without network or a real key). GET only; read-only.

## Files

| File | Role |
|---|---|
| `economics/provider_usage.py` | provider account-usage reader (env-only key, never logged, never raises) |
| `economics/connection_evidence.py` | read-only on-box outbound connections, provider-tagged |
| `economics/key_registry.py` | parse key→agent labels + budget (pure) |
| `scripts/load_cost_keys.py` | load labels as `human_declared` graph bindings (sticky) |
| `config/cost_advisor.yml` | operator-declared budget + key labels |
| `cognition/cost_advisor.py` | deterministic core: whole view, attribution, trend, budget |
| `cognition/cost_investigation.py` | Unattributed bucket → candidates + resolutions |
| `reports/cost_advisor_report.py` | render the artifact |
| `scripts/cost_advisor_report.py` | gather live evidence, build, write `reports/economics/COST_ADVISOR.md` |
| `scripts/scheduled_scan.py` | `run_cost_advisor()` — opt-in, fail-safe wiring into the cycle |

## How it runs on real data (2026-06-15)

Real ledger: **$100.21**, 100% attributed to `lesia` (anthropic $30.50 / google
$69.70 / openai $0.01), all `self_reported_ledger` (no usage key configured → the
authoritative provider totals are not yet pulled). Zero unattributed spend in the
live ledger — every row is tagged. The Unattributed investigation was exercised
against the **real on-box connection snapshot** (38 connections, 1 provider-tagged
to anthropic), correctly narrowing to one candidate with Medium confidence and
offering the `label_key_once` resolution — never a fabricated owner.
