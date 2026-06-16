# Maintenance Guide

Routine and periodic maintenance procedures for Quartermaster.

---

## Retention Management

Snapshots accumulate over time. The retention engine prunes old snapshots according to policy.

**Retention policy axes:**
1. **Age**: delete snapshots older than `retention_days`
2. **Count**: keep only the `max_snapshot_count` most recent
3. **Safety floor**: `min_keep_count` snapshots are always preserved

**Default policy (standard profile):**
- Retention: 30 days
- Max count: 200 snapshots
- Min keep: 10 snapshots

### Checking Retention Status

```bash
# View current snapshot count and what retention would do (dry run)
curl http://localhost:8000/operations/retention
```

### Executing Retention

```bash
# Always dry-run first
curl "http://localhost:8000/operations/retention?dry_run=true"

# If the preview looks correct, execute
curl -X POST "http://localhost:8000/operations/retention/execute?dry_run=false"
```

The response includes a summary of what was deleted and how many snapshots remain.

### Automating Retention (Weekly)

```cron
# Run retention weekly (dry_run=false — only add after verifying dry run)
0 2 * * 0 curl -sX POST "http://localhost:8000/operations/retention/execute?dry_run=false" >> /var/log/ops-retention.log
```

---

## Backup Procedures

### Manual Backup

```bash
./scripts/backup.sh
# Creates: backups/operational_memory_YYYYMMDD_HHMMSS.db
```

### Automated Weekly Backup

```cron
0 3 * * 0 /opt/quartermaster/scripts/backup.sh
```

### Backup Retention

The backup script does not delete old backups. Manage them manually:

```bash
# List backups older than 30 days
find backups/ -name "*.db" -mtime +30

# Delete backups older than 30 days (review first)
find backups/ -name "*.db" -mtime +30 -delete
```

---

## Database Maintenance

### Check Database Size

```bash
curl http://localhost:8000/operations/storage
# or
ls -lh data/operational_memory.db
```

### SQLite Optimization

SQLite WAL mode is used by default. Periodic VACUUM can reclaim space after large deletions:

```bash
# While server is stopped:
sqlite3 data/operational_memory.db "VACUUM;"
```

---

## Log Rotation

If using systemd journald, logs are automatically rotated.

For file-based logs, configure logrotate:

```
/var/log/quartermaster/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

---

## Updating Dependencies

```bash
./scripts/update.sh
```

This pulls latest code and updates Python packages. Restart the server after updating:

```bash
sudo systemctl restart quartermaster
```

---

## Self-Check Schedule

Run the self-check report periodically to catch issues early:

```bash
curl http://localhost:8000/operations/selfcheck
```

The self-check tests:
1. Scheduler is running and healthy
2. Latest snapshot is fresh (not stale)
3. Snapshot schema validity
4. Snapshot count vs. retention limits
5. Disk and database storage pressure

---

## Periodic Maintenance Checklist

### Weekly
- [ ] Review `/operations/selfcheck` output
- [ ] Check `/operations/storage` for pressure
- [ ] Run retention dry-run: `GET /operations/retention?dry_run=true`
- [ ] Run backup: `./scripts/backup.sh`

### Monthly
- [ ] Review snapshot growth trend: `GET /operations/storage`
- [ ] Review scheduler health: `GET /operations/scheduler`
- [ ] Execute retention if snapshot count is above 80% of limit
- [ ] Review deployment readiness: `GET /operations/readiness/report`
- [ ] Prune backups older than 30 days

### After Updates
- [ ] Verify `/health` returns `ok`
- [ ] Run self-check: `GET /operations/selfcheck`
- [ ] Trigger a manual scan: `POST /scan`
- [ ] Check latest snapshot looks correct

---

## Troubleshooting

### Scans Not Running

1. Check scheduler: `GET /operations/scheduler`
2. Check logs: `journalctl -u quartermaster -n 50`
3. Verify scan target exists: `ls -la <SCAN_TARGETS>`
4. Check for consecutive error count > 5 in scheduler health

### Database Growing Too Fast

1. Check snapshot count: `GET /operations/storage`
2. Run retention preview: `GET /operations/retention?dry_run=true`
3. Reduce `SCAN_INTERVAL_SECONDS` or `MAX_SNAPSHOT_COUNT` in `.env`
4. Execute retention if > 80% capacity

### Server Won't Start

1. Check Python version: `python3 --version` (need 3.11+)
2. Check virtualenv: `source .venv/bin/activate`
3. Validate config: `python3 -c "from backend.config import settings; print(settings)"`
4. Check port availability: `ss -tlnp | grep 8000`
5. Check DB permissions: `ls -la data/`
