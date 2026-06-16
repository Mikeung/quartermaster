"""Deterministic thresholds for economic, project, and agent observability.

Every threshold here is a fixed, documented constant. No threshold is learned,
adapted, or randomised. Two runs over the same input always produce the same
findings. This module is the single source of truth for all detection cut-offs
so calibration is one edit, not a hunt across files.

Philosophy (CLAUDE.md): observe automatically, decide manually. These constants
only decide what is *surfaced* to a human — never what action is taken.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Detection window
# ---------------------------------------------------------------------------
# Daily report cadence is 24h; detection windows align with it so a finding
# corresponds to "what happened since the last daily report".
WINDOW_HOURS: int = 24
WINDOW_DAYS: int = 1


# ---------------------------------------------------------------------------
# PHASE A — Economic observability
# ---------------------------------------------------------------------------
# Spend is read in USD from the llm_events store (estimated_cost column).
# All comparisons are against deterministic absolute floors and trailing medians.

# spend_spike: a window's spend exceeds SPIKE_FACTOR × trailing median daily spend.
# A min-USD floor prevents tiny baselines from making any spend look like a spike.
SPEND_SPIKE_FACTOR: float = 3.0
SPEND_SPIKE_MIN_USD: float = 10.0
SPEND_SPIKE_BASELINE_DAYS: int = 7        # trailing window for the median baseline

# Absolute daily-spend severity bands (USD) — used when no baseline exists yet.
DAILY_SPEND_WARN_USD: float = 20.0        # MEDIUM
DAILY_SPEND_HIGH_USD: float = 50.0        # HIGH

# abnormal_burn_rate: sustained USD/hour over the window.
BURN_RATE_WARN_USD_PER_HR: float = 2.0    # MEDIUM
BURN_RATE_HIGH_USD_PER_HR: float = 5.0    # HIGH

# runaway_agent_cost: one workflow/agent dominates spend AND burns for many hours.
RUNAWAY_MIN_USD: float = 25.0
RUNAWAY_MIN_HOURS: float = 6.0            # sustained, uninterrupted activity span
RUNAWAY_SINGLE_WORKFLOW_SHARE: float = 0.6   # ≥60% of window spend from one workflow

# economic_anomaly (umbrella): a provider/project that had ~zero spend in the
# baseline suddenly appears, or spend lands outside expected bounds.
ANOMALY_NEW_SPENDER_MIN_USD: float = 5.0  # ignore trivial first-time spenders

# Providers the economic layer understands cost for.
SUPPORTED_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "google", "gemini")

# --- Cost accountability (hotfix 2026-05-30) -------------------------------
# WHO owns a project's/agent's spend. Maps the spend attribution key (project_id
# / agent name, lowercased) to the accountable human owner. Unmapped actors
# resolve to the agent name as a best-effort owner; truly unknown spend (no
# project_id at all) raises unknown_cost_owner. Extend as ownership is assigned.
COST_OWNER_MAP: dict[str, str] = {}

# unknown_cost_owner: spend at/above this much in the window that CANNOT be
# attributed to any project_id/agent raises a HIGH finding. The operator must
# never discover paid consumption before the system can explain ownership.
UNKNOWN_COST_OWNER_MIN_USD: float = 5.0


# ---------------------------------------------------------------------------
# COST ADVISOR — provider-account usage, attribution, budget (the Economics slot)
# ---------------------------------------------------------------------------
# The cost advisor pulls TOTAL spend per provider from the provider's own
# account-usage API (the authoritative headline), attributes it to agents by
# evidence (per-key usage where a key maps 1:1 to an agent, or an agent's own
# parseable ledger), and surfaces everything else honestly as "Unattributed".
# It observes and explains spend; it never throttles, pauses, or spends.

# Provider account-usage is read with a USAGE-SCOPED key supplied via env ONLY.
# These are the env VAR NAMES the reader looks up; the value is never logged,
# never written to a record, and never committed. Absent var → the provider's
# account-usage view degrades to "unavailable" and the advisor falls back to the
# self-reported ledger (data/spend/) for that provider. Opt-in by construction.
PROVIDER_USAGE_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_ADMIN_KEY",   # Anthropic Admin API (usage/cost report)
    "openai": "OPENAI_ADMIN_KEY",         # OpenAI Usage API (organization costs)
}
# Providers with no per-key account-usage cost API the advisor can read. Their
# spend is sourced from the self-reported ledger only; never silently dropped.
PROVIDER_USAGE_UNSUPPORTED: tuple[str, ...] = ("google", "gemini")

# Network timeout (seconds) for a provider account-usage GET. Read-only.
PROVIDER_USAGE_TIMEOUT_S: float = 20.0

# Budget is HUMAN-DECLARED (config/cost_advisor.yml), never inferred. The advisor
# warns as a declared budget is APPROACHED and raises a money-critical when it is
# EXCEEDED. These fractions only decide what is surfaced — never any action.
BUDGET_APPROACHING_FRACTION: float = 0.8   # warn at ≥80% of a declared budget
# Unattributed provider/key spend at/above this in the window opens an
# investigation (which key, when clustered, who was calling that provider then).
UNATTRIBUTED_INVESTIGATE_MIN_USD: float = 5.0


# ---------------------------------------------------------------------------
# PHASE B — Project (engineering) observability  [git-based]
# ---------------------------------------------------------------------------
# All counts are over WINDOW_HOURS unless stated. Evidence is always the raw
# commit/file counts and the commit shortlog — never inferred.

# project_activity: any repo with at least this many commits in the window.
PROJECT_ACTIVITY_MIN_COMMITS: int = 1

# engineering_burst: high-volume engineering in the window (either threshold trips it).
ENGINEERING_BURST_COMMITS: int = 12
ENGINEERING_BURST_FILES: int = 25

# subsystem_rebuild: a single subsystem (top-2 path components) accounts for a
# dominant share of changed files, and the absolute count is non-trivial.
SUBSYSTEM_REBUILD_FILE_SHARE: float = 0.5
SUBSYSTEM_REBUILD_MIN_FILES: int = 8
SUBSYSTEM_PATH_DEPTH: int = 2             # how many path components name a "subsystem"

# deployment_event: commits that touch deploy infrastructure or say so in the message.
DEPLOY_PATH_MARKERS: tuple[str, ...] = (
    "deploy", "dockerfile", "docker-compose", "compose.yaml", "compose.yml",
    ".github/workflows", "k8s", "helm", "ansible", "terraform", "fly.toml",
    "procfile", "render.yaml", "vercel.json",
)
DEPLOY_MESSAGE_MARKERS: tuple[str, ...] = (
    "deploy", "release", "rollout", "ship ", "publish", "hotfix", "go live",
)


# ---------------------------------------------------------------------------
# PHASE C — Agent observability
# ---------------------------------------------------------------------------
# An "agent" is a non-interactive actor: an AI coding agent (aider/claude), a
# scheduled automation, or a bot. Attribution is deterministic and pattern-based;
# the matched pattern is recorded as evidence.

# Git author name/email substrings that mark a commit as agent-authored.
# "your name" is the un-personalised git default that Lesia's automated
# (aider-driven) commits carry — see DECISION_LOG.
AGENT_AUTHOR_PATTERNS: tuple[str, ...] = (
    "your name", "aider", "claude", "bot", "automation", "agent",
    "github-actions", "noreply",
)
# Commit-message prefixes/markers that mark a commit as automated even when the
# author is a human git identity (e.g. quartermaster's own cron commits).
AGENT_MESSAGE_PATTERNS: tuple[str, ...] = (
    "quartermaster:", "[bot]", "automated", "auto-commit", "chore(release)",
)

# agent_burst: agent-attributed commits in the window at/above this count.
AGENT_BURST_COMMITS: int = 12

# agent_runtime: continuous activity span (first→last agent event) at/above this
# many hours is notable — long unattended runs are where cost/risk accrue.
AGENT_RUNTIME_NOTABLE_HOURS: float = 6.0

# agent_cost: spend attributed to a single agent/project at/above this in window.
AGENT_COST_NOTABLE_USD: float = 10.0


# ---------------------------------------------------------------------------
# Spend ledger
# ---------------------------------------------------------------------------
# Observe-only contract: quartermaster READS spend records that producers drop into
# this directory as JSON Lines. quartermaster never writes into producer projects.
SPEND_LEDGER_DIRNAME: str = "spend"      # under data/
SPEND_IMPORT_STATE_FILE: str = "spend_import_state.json"  # under data/


# ---------------------------------------------------------------------------
# Real-time notification layer (PRIORITY ZERO)
# ---------------------------------------------------------------------------
# Reduces awareness latency from hours (daily report) to minutes. Priority is a
# deterministic lookup by finding_type — never severity-guessed. Dedup is keyed
# on the deterministic finding_id, so finding identity + recurrence semantics are
# preserved end-to-end.

# finding_type -> notification priority. Push notification is an explicit
# allowlist: anything unmapped falls back to NOTIFY_DEFAULT_PRIORITY (P2 = daily
# report only, never pushed). This keeps the real-time channel bounded and
# trustworthy — advisory recommendations and catalogue findings do not page the
# operator; only the listed operational events do.
NOTIFICATION_PRIORITY: dict[str, str] = {
    # --- P0: immediate (bypasses quiet hours) ---
    "spend_spike": "P0",
    "economic_anomaly": "P0",
    "runaway_agent_cost": "P0",
    "abnormal_burn_rate": "P0",
    "unknown_cost_owner": "P0",          # spend with no owner — page immediately
    "budget_exceeded": "P0",             # a human-declared budget was exceeded
    "kernel_oom_kill": "P0",
    "dependency_unreachable": "P0",
    "port_exposed_publicly": "P0",       # public exposure
    "deployment_event": "P0",
    "subsystem_rebuild": "P0",
    "engineering_burst": "P0",
    "agent_cost": "P0",                  # agent cost spike
    "agent_burst": "P0",                 # Lesia / automation burst
    # --- P1: batched digest (respects quiet hours) ---
    "repeated_service_restart": "P1",    # restart bursts
    "budget_approaching": "P1",          # nearing a declared budget — warn, don't storm
    "monitor_stale": "P1",
    "agent_runtime": "P1",
    "stable_listener_disappeared": "P1",
    "service_disappeared": "P1",
    "credential_in_unit_file": "P1",     # HIGH but persistent/known → batched, not stormed
    "world_readable_env_file": "P1",
    # --- P2: daily report only (never push-notified) ---
    "project_activity": "P2",
    "agent_activity": "P2",
    "coverage_gap": "P2",
    "insufficient_context": "P2",        # suppressed recommendation — report, don't page
}
NOTIFY_DEFAULT_PRIORITY: str = "P2"

# Dedup cooldown: after notifying a finding, suppress the SAME finding_id until
# this many hours pass — unless it escalates or reactivates (those bypass cooldown).
# Long cooldowns are the primary anti-storm guard.
NOTIFY_COOLDOWN_HOURS_P0: float = 12.0
NOTIFY_COOLDOWN_HOURS_P1: float = 24.0

# Per-run rate cap: at most this many P0 alerts sent individually; the remainder
# collapse into one aggregate "+N more P0 events" line (storm prevention).
NOTIFY_MAX_P0_PER_RUN: int = 6
# Max P1 findings itemised in a single batched digest (rest summarised as a count).
NOTIFY_P1_DIGEST_MAX: int = 12

# Quiet hours (UTC). P0 ALWAYS bypasses these (the motivating case is overnight
# $100 spend). P1 digests are deferred until the window ends.
NOTIFY_QUIET_HOURS_ENABLED: bool = True
NOTIFY_QUIET_HOURS_START: str = "22:00"
NOTIFY_QUIET_HOURS_END: str = "08:00"

# Runtime state/audit files (under data/, gitignored).
NOTIFY_STATE_FILE: str = "notification_state.json"   # dedup state, keyed by finding_id
NOTIFY_LOG_FILE: str = "notification_log.jsonl"      # append-only decision audit trail
