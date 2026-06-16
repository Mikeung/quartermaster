# Deployment Guide

This guide covers deploying Quartermaster on a single VPS.

---

## Requirements

- Python 3.11+
- SQLite 3.35+ (ships with Python 3.11)
- 256 MB RAM minimum (512 MB recommended)
- 1 GB disk (for database + reports)
- Linux (Ubuntu 22.04 LTS recommended)

---

## First-Time Setup

```bash
git clone <repo-url> quartermaster
cd quartermaster
./scripts/bootstrap.sh
```

The bootstrap script:
1. Verifies Python 3.11+
2. Creates a virtualenv at `.venv/`
3. Installs all dependencies
4. Creates `data/` and `data/reports/` directories
5. Copies `.env.example` → `.env` if not present

---

## Configuration

Copy `.env.example` to `.env` and review:

```bash
cp .env.example .env
nano .env
```

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Set to `production` on VPS |
| `DEBUG` | `false` | `true` enables /docs and /redoc |
| `DB_PATH` | `data/operational_memory.db` | SQLite path |
| `SCAN_INTERVAL_SECONDS` | `300` | Seconds between scans |
| `SCAN_TARGETS` | `.` | Comma-separated paths to scan |
| `REPORTS_DIR` | `data/reports` | Where markdown reports are written |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | `json` | `json` for structured logs, `text` for human-readable |

---

## Deployment Profiles

Three built-in profiles match common VPS configurations:

| Profile | Interval | Retention | Snapshots | Use Case |
|---------|----------|-----------|-----------|----------|
| `minimal` | 15 min | 7 days | 50 max | Low-resource VPS, infrequent monitoring |
| `standard` | 5 min | 30 days | 200 max | Standard production (recommended) |
| `extended` | 2 min | 90 days | 1000 max | High-activity repos, deep visibility |

Profiles are starting points — individual `.env` settings override them at runtime.

---

## Starting the Server

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

For production with auto-restart (systemd):

```ini
# /etc/systemd/system/quartermaster.service
[Unit]
Description=Quartermaster
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/quartermaster
ExecStart=/opt/quartermaster/.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10
EnvironmentFile=/opt/quartermaster/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable quartermaster
sudo systemctl start quartermaster
```

---

## Health Check

```bash
./scripts/healthcheck.sh
# or
curl http://localhost:8000/health
```

---

## Updating

```bash
./scripts/update.sh
# then restart
sudo systemctl restart quartermaster
```

---

## Backup

```bash
./scripts/backup.sh
# creates backups/operational_memory_YYYYMMDD_HHMMSS.db
```

SQLite WAL mode allows hot backups — no need to stop the server.

---

## Restore

Stop the server first, then:

```bash
sudo systemctl stop quartermaster
./scripts/restore.sh backups/operational_memory_20260101_120000.db
sudo systemctl start quartermaster
```

---

## Firewall

The API server binds to `127.0.0.1` (localhost only) by default behind a reverse proxy.

If exposing directly, restrict to trusted IPs:

```bash
ufw allow from <your-ip> to any port 8000
```

---

## nginx Reverse Proxy (optional)

```nginx
server {
    listen 80;
    server_name ops.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## What This System Does NOT Do

- Modify infrastructure autonomously
- Deploy code or restart services
- Self-heal or self-update
- Replace operator judgment

All findings are advisory. All decisions are human.
