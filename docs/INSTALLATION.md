# Installation & Running

quartermaster is a Linux-first, VPS-oriented, advisory tool. It reads your
host to explain it and never modifies anything outside its own `data/` and
`reports/` directories. Read [SECURITY.md](../SECURITY.md) before running.

## Requirements

- Linux (POSIX). The scanners shell out to `ps`, `ss`, `lsof`, `systemctl`,
  `journalctl`, `docker` where available — missing tools degrade to no-ops.
- Python 3.11+.
- No root required. Without elevated read access, some host checks become no-ops
  rather than failing.

## Install (local)

```bash
git clone https://github.com/Mikeung/quartermaster
cd quartermaster
python -m venv venv && . venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit locally; never commit .env
```

## First run

Point it at a directory and start the API, or use the CLI:

```bash
# Start the HTTP API (read-only intelligence over HTTP)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
# then, in another shell:
aom health
aom projects

# Or run a one-off scan cycle against your own projects:
QM_SCAN_TARGETS=/path/to/projectA,/path/to/projectB \
  python scripts/scheduled_scan.py
```

By default the scan targets are unset for a fresh checkout — set
`QM_SCAN_TARGETS` (comma-separated absolute paths) or edit
`_DEFAULT_SCAN_TARGETS` in `scripts/scheduled_scan.py`.

## Configuration

All configuration is via `.env` (see `.env.example`) plus operator-editable YAML:

- `config/cost_advisor.yml` — human-declared budget + provider key→agent labels.
- `config/operational_graph.yml` — declare dependencies/liveness/consequence for
  your own services (ships with examples; replace with your own).
- `config/check_playbook.yml` — "what to check" steps per finding type.

## Running on a schedule

The scan is a plain script; schedule it with cron (it is **not** a daemon):

```cron
0 */6 * * * cd /opt/quartermaster && QM_SCAN_TARGETS=/srv/app venv/bin/python scripts/scheduled_scan.py
```

## Docker

```bash
docker compose up --build      # serves the API on :8000, persists ./data
```

The container reads `.env` (via `env_file`) and persists the SQLite store to the
mounted `./data` volume.

## Telegram alerts (optional)

Set `TELEGRAM_ENABLED=true` and supply `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
in `.env`. With these unset, the tool runs fully locally and pushes nothing.
