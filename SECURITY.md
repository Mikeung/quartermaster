# Security & What It Touches

quartermaster is **advisory and read-only by design**. It observes a host
to explain it; it never modifies infrastructure, deploys, or remediates. This
document states exactly what it reads, what leaves the box, and how secrets are
handled, so you can run it on your own system with informed consent.

## Core guarantees

- **Read-only.** Scanners never write to, modify, or delete anything they inspect.
  The only paths the tool writes to are its own `data/` (SQLite store, state) and
  `reports/` (generated markdown).
- **Observe automatically, decide manually.** No autonomous remediation. Every
  finding is a recommendation for a human.
- **Evidence-bound.** Every claim carries an answer + confidence + the observable
  evidence behind it. "Unknown" is a valid answer; it does not guess.
- **Opt-in network.** It makes no outbound calls unless you configure them
  (Telegram delivery, optional LLM drafting, optional provider account-usage).

## What it reads (locally, read-only)

- **Processes & sockets:** `ps`, `ss`, `lsof` output — process inventory and
  active connections (`scanners/`, `economics/connection_evidence.py`).
- **systemd & docker:** `systemctl`, `journalctl`, `docker` for service/container
  state (`scanners/service_scanner.py`, `scanners/runtime_scanner.py`).
- **Filesystem:** git repositories you point it at, and host config such as
  `/etc/systemd/system/*.service` and `.env` file *permissions*. The security
  scanner reports the *presence* of world-readable secrets and credentials in
  unit files; matched secrets are **redacted** in findings, never echoed.
- **Kernel log:** `journalctl -k` for OOM events.

It needs only read access. It does **not** require root; without it, some checks
become no-ops rather than failing.

## What leaves the box (only if you enable it)

| Destination | Purpose | How to enable | Auth |
|---|---|---|---|
| `api.telegram.org` | Push alerts / digests | `TELEGRAM_ENABLED=true` + token/chat id | `TELEGRAM_BOT_TOKEN` (env) |
| `api.openai.com` | Optional meaning-layer drafting (manual script) | run `scripts/draft_meaning_layer.py` with `OPENAI_API_KEY` | `OPENAI_API_KEY` (env) |
| `api.anthropic.com` / `api.openai.com` | Cost advisor account-usage headline | set `ANTHROPIC_ADMIN_KEY` / `OPENAI_ADMIN_KEY` | usage-scoped key (env) |

With none of these set, the tool runs fully locally.

## Secret handling (hard rules)

- Secrets are read from **environment variables only** (via `.env`, which is
  gitignored). They are **never** logged, returned in API responses, written to
  reports, or committed.
- The cost advisor's provider keys never leave `economics/provider_usage.py`
  except as a last-4 `key_hint`; error messages are scrubbed of the key value.
- `.env` is gitignored. Copy `.env.example` → `.env` and fill in locally. Never
  commit a real token; if one is exposed, rotate it at the provider.
- **Set a secret without exposing it:** `python scripts/set_secret.py KEY_NAME`
  prompts for the value with the input hidden and writes it to `.env` at mode 600
  — no manual file editing, no value in shell history or logs.
- **Pre-commit secret scanner:** run `scripts/install_hooks.sh` once per clone to
  install a hook that blocks commits containing token/key-shaped strings
  (`scripts/secret_scan.py`; also runnable in CI).

## Reporting a vulnerability

Open a private security advisory on the GitHub repository, or email the
maintainer listed in `pyproject.toml`. Please do not file public issues for
security reports.
